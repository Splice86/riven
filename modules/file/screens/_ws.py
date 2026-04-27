"""WebSocket route for screen streaming — /module/file/screens/stream."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import _broadcaster as bc
from ._registry import ScreenConnection, registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["file.screens"])


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
      2. Client sends {"type": "register", "uid": "...", "session_id": "..."}
         - If uid is new, the server generates one and returns it
         - If uid exists, binding state is restored from DB
      3. If the screen was previously bound, a "snapshot" message is sent immediately
      4. Server sends "bound"/"released"/"diff" messages as events occur
      5. Client can send: touch, snapshot_request, release

    Query params (optional):
      session_id: Pre-seed the session ID for registration auto-fill
    """
    await ws.accept()

    # Extract query params
    query_params = dict(ws.query_params)
    session_hint = query_params.get("session_id", "")

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
                # First message: client identifies itself
                uid = msg.get("uid", "")
                capacity = int(msg.get("capacity_lines", 30))
                client_name = msg.get("client_name", "Screen")

                if not uid:
                    uid = secrets.token_hex(4)  # 8 hex chars

                # Create connection object (partial — binding comes from memory)
                screen = ScreenConnection(
                    uid=uid,
                    ws=ws,
                    capacity_lines=capacity,
                    client_name=client_name,
                )

                # Register in registry (in-memory only)
                await registry.connect(screen)

                logger.info(f"[Screens] Registered: uid={uid} client={client_name}")

                # Send ack
                await ws.send_text(json.dumps({
                    "type": "registered",
                    "uid": uid,
                    "bound_path": screen.bound_path or "",
                    "bound_section": screen.bound_section or None,
                    "bound_version": screen.bound_version,
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
                        # screen has no bound path — respond gracefully so client isn't left hanging
                        await ws.send_text(json.dumps({
                            "type": "snapshot", "status": "idle",
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
                # Screens can also self-bind via WS (alternative to screen_bind tool)
                if screen:
                    path = msg.get("path", "")
                    section = msg.get("section", "")
                    try:
                        ok = await registry.bind(screen.uid, path, section)
                        if ok:
                            # Re-fetch screen so bound_* fields are up to date
                            screen = await registry.get(screen.uid)
                            await ws.send_text(json.dumps({
                                "type": "bound",
                                "path": path,
                                "section": section,
                                "version": screen.bound_version,
                            }))
                            # Push content immediately so screen doesn't need a refresh
                            await bc.send_snapshot(screen)
                        else:
                            await ws.send_text(json.dumps({
                                "type": "error", "message": "Failed to bind to file", "status": "error"
                            }))
                    except Exception as e:
                        await ws.send_text(json.dumps({
                            "type": "error", "message": str(e), "status": "error"
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
