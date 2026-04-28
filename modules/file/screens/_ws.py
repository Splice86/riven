"""WebSocket route for screen streaming — /module/file/screens/stream."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import _broadcaster as bc
from ._registry import ScreenConnection, registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["file.screens"])

# ---------------------------------------------------------------------------
# UID assignment
#
# Two concerns, addressed separately:
#
#   1. Per-session counter — ensures every new WebSocket connection gets a
#      globally unique UID within that session, even when multiple tabs open
#      simultaneously or Chrome duplicates a tab.
#
#   2. Connection-level restore — id(ws) is used to persist the UID across
#      messages on the *same* WebSocket connection (reconnect after a blip).
# ---------------------------------------------------------------------------

# {session_id: next_counter}  — thread-safe via asyncio.Lock
_session_seed: dict[str, int] = {}

# {id(ws): uid}  — persists uid across messages on the same WS connection
_ws_uid: dict[int, str] = {}

# Module-level lock to serialise uid assignment and protect _session_seed
_uid_lock = asyncio.Lock()


def _session_prefix(session_id: str) -> str:
    """Build a short prefix from the session ID for readable UIDs."""
    return session_id[:8].upper() if session_id else "ANON"


async def _assign_uid(session_id: str) -> str:
    """Atomically assign the next UID for a session.

    Format: {prefix}-{counter:04d}  e.g.  ABCDEF01-0003
    """
    global _session_seed

    prefix = _session_prefix(session_id)

    async with _uid_lock:
        counter = _session_seed.get(session_id, 0) + 1
        _session_seed[session_id] = counter
        return f"{prefix}-{counter:04d}"


@router.get("/module/file/screens/")
async def screen_client_page():
    """Serve the screen client HTML page.

    Screens visit this URL to get the live file view client.
    The page auto-connects to the WebSocket using relative URL.
    """
    import os
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    html_path = os.path.join(static_dir, "screen.html")

    if os.path.exists(html_path):
        from fastapi.responses import FileResponse
        return FileResponse(html_path, media_type="text/html")

    return {
        "error": "screen.html not found",
        "path": html_path,
        "hint": "Mount the file module static directory or visit /module/file/screens/stream directly",
    }


# =============================================================================
# WebSocket endpoint
# =============================================================================

@router.websocket("/module/file/screens/stream")
async def screen_stream(ws: WebSocket):
    """Handle a screen WebSocket connection.

    Protocol:
      1. Client connects (no auth required — screens are low-privilege)
      2. Client sends {"type": "register", "session_id": "...", "client_name": "..."}
         - Client NEVER sends a uid — the server is always authoritative
         - Server assigns the next UID from the session counter and sends it back
      3. Server sends "registered" with the assigned uid + any current binding state
      4. Server sends "bound"/"released"/"diff" messages as events occur
      5. Client can send: touch, snapshot_request, release

    Query params (optional):
      session_id: Used as the counter namespace for UID generation
    """
    await ws.accept()

    # Extract session_id from query params (must be present for UID assignment)
    query_params = dict(ws.query_params)
    session_id = query_params.get("session_id", "")

    # Track ws_id for uid restore across messages on this connection
    ws_id = id(ws)

    screen: Optional[ScreenConnection] = None

    try:
        while True:
            # Receive next message (with timeout for keepalive)
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
            except asyncio.TimeoutError:
                # Keepalive: send a no-op ping/pong
                if screen:
                    await ws.send_text(json.dumps({"type": "ping"}))
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            msg_type = msg.get("type", "")

            if msg_type == "register":
                client_name = msg.get("client_name", "Screen")

                # -----------------------------------------------------------
                # UID derivation — server is ALWAYS authoritative
                #
                # Check if this WS already has a uid from a prior message
                # (blip reconnect within the same WebSocket session).
                # Otherwise assign the next one from the session counter.
                # -----------------------------------------------------------
                uid = _ws_uid.get(ws_id)
                is_reconnect = uid is not None

                if uid is None:
                    uid = await _assign_uid(session_id)
                    _ws_uid[ws_id] = uid
                    logger.info(f"[Screens] Assigned uid={uid} session={session_id} client={client_name}")
                else:
                    logger.info(f"[Screens] Restored uid={uid} session={session_id} client={client_name} (reconnect)")

                # Create and register the connection
                screen = ScreenConnection(
                    uid=uid,
                    ws=ws,
                    client_name=client_name,
                )
                await registry.connect(screen)

                # Send the server-assigned uid back to the client so it can
                # persist to localStorage for browser-refresh recovery
                await ws.send_text(json.dumps({
                    "type": "registered",
                    "uid": uid,
                    "bound_path": screen.bound_path or "",
                    "bound_version": screen.bound_version,
                    "reconnect": is_reconnect,
                }))

            elif msg_type == "ping":
                if screen:
                    await ws.send_text(json.dumps({"type": "pong"}))
                else:
                    await ws.send_text(json.dumps({"type": "error", "message": "Not registered"}))

            elif msg_type == "touch":
                if screen:
                    await registry.touch(screen.uid)
                    await ws.send_text(json.dumps({"type": "pong"}))
                else:
                    await ws.send_text(json.dumps({"type": "error", "message": "Not registered"}))

            elif msg_type == "snapshot_request":
                if screen:
                    ok = await bc.send_snapshot(screen)
                    if not ok:
                        await ws.send_text(json.dumps({
                            "type": "snapshot",
                            "status": "idle",
                            "path": screen.bound_path or "",
                            "message": "No file bound. Use screen_bind to bind first.",
                        }))
                else:
                    await ws.send_text(json.dumps({"type": "error", "message": "Not registered"}))

            elif msg_type == "release":
                if screen:
                    await registry.release(screen.uid)
                    await ws.send_text(json.dumps({
                        "type": "released",
                        "was_bound": bool(screen.bound_path),
                    }))

            elif msg_type == "bind":
                if screen:
                    path = msg.get("path", "")
                    try:
                        ok = await registry.bind(screen.uid, path)
                        if ok:
                            screen = await registry.get(screen.uid)
                            await ws.send_text(json.dumps({
                                "type": "bound",
                                "path": path,
                                "version": screen.bound_version,
                            }))
                            await bc.send_snapshot(screen)
                        else:
                            await ws.send_text(json.dumps({
                                "type": "error",
                                "message": "Failed to bind to file",
                                "status": "error",
                            }))
                    except Exception as e:
                        await ws.send_text(json.dumps({
                            "type": "error",
                            "message": str(e),
                            "status": "error",
                        }))
                else:
                    await ws.send_text(json.dumps({"type": "error", "message": "Not registered"}))

            else:
                await ws.send_text(json.dumps({"type": "error", "message": f"Unknown message type: {msg_type}"}))

    except WebSocketDisconnect:
        logger.info(f"[Screens] WebSocket disconnected: uid={screen.uid if screen else '?'}")

    finally:
        if screen:
            await registry.disconnect(screen.uid)
        # Clean up so we don't leak ws_ids after disconnect
        _ws_uid.pop(ws_id, None)
