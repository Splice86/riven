"""Riven-facing screen management tools.

Called by Riven via the tool interface. All state is in-memory
via the registry — no DB needed.
"""
from __future__ import annotations

import logging
import os

from . import _broadcaster as bc
from ._registry import registry

logger = logging.getLogger(__name__)


async def screen_list() -> str:
    """List all connected screens, regardless of session."""
    screens = await registry.list_all()

    if not screens:
        return "No screens connected. Open the screen page in a browser tab."

    lines = [f"Screens ({len(screens)}):", ""]
    for s in screens:
        status = "🟢 bound" if s.bound_path else "⚪ idle"
        path_str = s.bound_path or "(not bound)"
        lines.append(f"  {status} [{s.uid}] {s.client_name}")
        lines.append(f"      bound: {path_str}")
        lines.append("")

    return "\n".join(lines).strip()


async def screen_bind(
    path: str,
    screen_uid: str,
) -> str:
    """Bind a screen to a file, enabling live edit broadcasts."""
    from modules import get_session_id
    from modules.file.memory import track_screen_bound

    session_id = get_session_id()
    screen = await registry.get(screen_uid)
    if not screen:
        return f"[ERROR] Screen UID '{screen_uid}' not found. Open a screen page first."

    ok = await registry.bind(screen_uid, path)
    if not ok:
        return f"[ERROR] Failed to bind screen {screen_uid}"

    # Record binding in memory so broadcast can find it by path
    track_screen_bound(session_id, path, screen_uid)

    # Notify the client — registry.bind() updates screen.bound_* in-place, so
    # the screen object we already have is up-to-date. No re-fetch needed.
    await bc.broadcast_bind(screen)  # → client sets currentPath + setFilePath
    await bc.send_snapshot(screen)   # → client renders content
    # Update the shared SnapshotStore so subsequent diffs use this as the
    # baseline instead of an empty store
    abs_path = os.path.abspath(path)
    bc.snapshots.update(abs_path, screen.bound_version)

    return f"Bound screen {screen_uid} → {path}"


async def screen_release(screen_uid: str) -> str:
    """Release a screen from its current binding."""
    from modules import get_session_id
    from modules.file.memory import track_screen_unbound

    screen = await registry.get(screen_uid)
    if not screen:
        return f"[ERROR] Screen UID '{screen_uid}' not found. Open a screen page first."

    was_path = screen.bound_path
    ok = await registry.release(screen_uid)
    if not ok:
        return f"[ERROR] Failed to release screen {screen_uid}"

    # Remove from memory binding list
    if was_path:
        session_id = get_session_id()
        track_screen_unbound(session_id, was_path, screen_uid)

    return f"Released screen {screen_uid}" + (f" from {was_path}" if was_path else "")

async def screen_status(screen_uid: str) -> str:
    """Get the current status of a specific screen."""
    screen = await registry.get(screen_uid)
    if not screen:
        return f"Screen UID '{screen_uid}' not found."

    lines = [
        f"Screen: {screen.client_name} [{screen.uid}]",
        f"  Status: {'🟢 bound' if screen.bound_path else '⚪ idle'}",
        f"  Bound path: {screen.bound_path or '(none)'}",
        f"  Bound version: {screen.bound_version}",
    ]
    return "\n".join(lines)
