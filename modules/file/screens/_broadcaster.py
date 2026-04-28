"""Broadcast engine — sends snapshots and diffs to connected screens.

This module is imported by the file module's edit hooks and by the
WebSocket handler. All sends go through the registry's WebSocket connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import WebSocket

from . import constants as C
from ._registry import ScreenConnection, registry
from ._diff import FileSnapshot, SnapshotStore

logger = logging.getLogger(__name__)

# Module-level snapshot store (shared across the broadcaster and WS handler)
snapshots = SnapshotStore()


# =============================================================================
# Message builders
# =============================================================================

def _build_message(msg_type: str, **kwargs) -> str:
    """Build a JSON WebSocket message."""
    return json.dumps({"type": msg_type, **kwargs}, ensure_ascii=False)


def _build_snapshot(path: str, version: int) -> Optional[dict]:
    """Build a full snapshot message for a file.

    Always reads from disk so every snapshot reflects the current state.
    """
    snap = FileSnapshot.from_path(path, version)
    if snap is None:
        return None

    lines = snap.slice()
    return {
        "path": path,
        "version": version,
        "total_lines": len(snap.lines),
        "lines": lines,
    }


def _build_diff(diff) -> dict:
    """Build a diff message from a LineDiff."""
    return {
        "path": diff.path,
        "old_version": diff.old_version,
        "new_version": diff.new_version,
        "total_lines": diff.total_lines,
        "sections": diff.sections,
    }


# =============================================================================
# Broadcast primitives
# =============================================================================

async def _send(ws: WebSocket, msg: str) -> bool:
    """Send a message to a WebSocket. Returns True on success."""
    try:
        await ws.send_text(msg)
        return True
    except Exception:
        return False


async def _send_to_all(screens: list[ScreenConnection], msg: str) -> tuple[int, int]:
    """Send a message to all screens in the list.

    Returns (sent, failed).
    """
    sent, failed = 0, 0
    for screen in screens:
        ok = await _send(screen.ws, msg)
        if ok:
            sent += 1
        else:
            failed += 1
    return sent, failed


# =============================================================================
# Snapshot broadcast (on bind or reconnect)
# =============================================================================

async def send_snapshot(screen: ScreenConnection) -> bool:
    """Send a full file snapshot to a single screen.

    Used when:
    - A screen binds to a file
    - A screen reconnects and was previously bound
    - A screen requests a full refresh via "snapshot_request"
    """
    if not screen.bound_path:
        return False

    # Normalize path
    path = os.path.abspath(screen.bound_path)

    payload = _build_snapshot(
        path=path,
        version=screen.bound_version,
    )

    if payload is None:
        msg = _build_message(
            "snapshot",
            status="error",
            path=screen.bound_path,
            error=f"File not found: {screen.bound_path}",
        )
    else:
        msg = _build_message("snapshot", **payload)

    return await _send(screen.ws, msg)


async def send_snapshot_to_uid(screen_uid: str) -> bool:
    """Send a snapshot to a specific screen by UID.

    Used to push content to a newly registered or newly bound screen.
    """
    screen = await registry.get(screen_uid)
    if not screen or not screen.bound_path:
        return False
    return await send_snapshot(screen)


async def send_snapshots_for_path(path: str) -> int:
    """Send snapshots to ALL screens bound to a path (all sessions).

    Called when a file is opened so any already-bound screens get the content.
    Returns the number of screens notified.
    """
    path = os.path.abspath(path)
    screens = await registry.get_by_path(path)
    if not screens:
        return 0

    # Update the snapshot store so compute_diff uses fresh content going forward
    version = await registry.get_version(path)
    snapshots.update(path, version)

    count = 0
    for screen in screens:
        ok = await send_snapshot(screen)
        if ok:
            count += 1
        else:
            logger.warning(f"[Screens] Failed to send snapshot to screen {screen.uid}")
    logger.debug(f"[Screens] send_snapshots_for_path: {path} → {count} screen(s)")
    return count


# =============================================================================
# Diff broadcast (on file edit)
# =============================================================================

async def broadcast_edit(path: str, uids: list[str]) -> tuple[int, int]:
    """Broadcast a file edit to specific screens watching a file.

    Increments the file version, computes diff, and sends to matching screens.

    Args:
        path: Absolute path of the edited file
        uids: List of screen UIDs to send the diff to

    Returns:
        (sent, failed) count
    """
    path = os.path.abspath(path)

    # Get the previous version from the stored snapshot so the diff metadata is accurate
    prev_snap = snapshots.get(path)
    old_version = prev_snap.version if prev_snap else 0

    # Compute diff against the snapshot store (increments version atomically)
    diff = snapshots.compute_diff(path, old_version=old_version, new_version=new_version)

    if diff is None:
        logger.warning(f"[Screens] broadcast_edit: could not load file {path}")
        return 0, 0

    if not diff.sections:
        # No actual changes (might be a save without modifications)
        return 0, 0

    # Increment registry version, collect screens, and update their versions
    # — all under a SINGLE lock to avoid a double-lock deadlock with bump_version
    async with registry._lock:
        new_version = await registry.bump_version(path)
        screens = []
        for uid in uids:
            screen = registry._connections.get(uid)
            if screen and screen.bound_path == path:
                screen.bound_version = new_version
                screens.append(screen)

    msg = _build_message("diff", **_build_diff(diff))
    sent, failed = await _send_to_all(screens, msg)

    logger.debug(f"[Screens] broadcast_edit: {path} v{new_version} → {sent} screen(s)")
    return sent, failed


# =============================================================================
# Bind/Release notification broadcasts
# =============================================================================

async def broadcast_bind(screen: ScreenConnection) -> None:
    """Notify a screen that it has been bound to a file.

    Sends a 'bound' message (screen should then request snapshot).
    """
    msg = _build_message(
        "bound",
        path=screen.bound_path,
        version=screen.bound_version,
    )
    await _send(screen.ws, msg)


async def broadcast_release(screen: ScreenConnection) -> None:
    """Notify a screen that it has been released."""
    msg = _build_message("released", path=screen.bound_path)
    await _send(screen.ws, msg)


async def broadcast_release_for_path(path: str) -> int:
    """Notify all screens bound to a path that the file has been closed.

    Used when a file is closed — screens should clear their content and go idle.
    Returns the number of screens notified.
    """
    path = os.path.abspath(path)
    screens = await registry.get_by_path(path)
    count = 0
    for screen in screens:
        # Release from registry and notify
        await registry.release(screen.uid)
        ok = await _send(screen.ws, _build_message("released", path=path))
        if ok:
            count += 1
        else:
            logger.warning(f"[Screens] Failed to notify screen {screen.uid} of close")
    if count > 0:
        logger.info(f"[Screens] Released {count} screen(s) for closed file: {path}")
    else:
        logger.debug(f"[Screens] broadcast_release_for_path: {path} → 0 screens (no match in registry)")
    return count

