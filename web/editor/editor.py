"""File watcher + WebSocket server for the web editor.

Handles:
  - Walking the project directory and building a file tree
  - Watching files for changes (via watchdog + periodic fallback)
  - Serving file content over WebSocket
  - Broadcasting file changes to all connected clients watching a path
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .config import (
    EXCLUDE_PATTERNS,
    INCLUDE_EXTENSIONS,
    MAX_FILE_SIZE,
    POLL_INTERVAL,
    WS_HEARTBEAT_INTERVAL,
    get_root_dir,
)

try:
    import events
except ImportError:
    events = None  # web editor running standalone

logger = logging.getLogger("web.editor")

router = APIRouter(tags=["web.editor"])


# ─── Root directory (resolved per-call to respect RV_PROJECT_ROOT / cwd) ───────
def EDITOR_ROOT() -> str:
    """Return the project root — resolved at call time, not import time.

    This ensures that RV_PROJECT_ROOT and working-directory changes are picked up
    without restarting the server.
    """
    return get_root_dir()

# ─── Connected WebSocket clients ──────────────────────────────────────────────
# Each client tracks which path(s) they have open so we can broadcast
# only to clients that care.
class _Client:
    __slots__ = ("ws", "open_paths", "uid", "session_id", "instance_id")

    def __init__(self, ws: WebSocket, uid: int):
        self.ws = ws
        self.open_paths: set[str] = set()
        self.uid = uid
        self.session_id: str | None = None
        self.instance_id: str | None = None


_clients: dict[int, _Client] = {}
_client_uid_counter = 0
_clients_lock = asyncio.Lock()

# ─── Awareness state (who is editing which file) ──────────────────────────────
# Maps rel_path -> list of {session_id, instance_id, color}
_awareness: dict[str, list[dict]] = {}


async def _add_client(ws: WebSocket) -> _Client:
    global _client_uid_counter
    async with _clients_lock:
        client = _Client(ws, _client_uid_counter)
        _clients[_client_uid_counter] = client
        _client_uid_counter += 1
        return client


async def _remove_client(uid: int) -> None:
    async with _clients_lock:
        _clients.pop(uid, None)


async def _broadcast(msg: dict, filter_path: str | None = None) -> None:
    """Send a message to all connected clients.

    If filter_path is set, only send to clients that have that path open.
    """
    raw = json.dumps(msg)
    async with _clients_lock:
        for client in list(_clients.values()):
            if client.ws.client_state != WebSocketState.CONNECTED:
                continue
            if filter_path and filter_path not in client.open_paths:
                continue
            try:
                await client.ws.send_text(raw)
            except Exception:
                pass


# ─── File tree ────────────────────────────────────────────────────────────────

def _should_include(name: str) -> bool:
    """Return True if a file should appear in the tree."""
    if name in EXCLUDE_PATTERNS:
        return False
    for pat in EXCLUDE_PATTERNS:
        if pat.startswith("*") and name.endswith(pat[1:]):
            return False
    return True


def _walk_dir(abs_dir: str, max_depth: int = 3, depth: int = 0) -> list[dict]:
    """Recursively build a file tree starting from abs_dir (absolute path)."""
    items = []

    try:
        entries = sorted(os.listdir(abs_dir), key=lambda n: (not os.path.isdir(os.path.join(abs_dir, n)), n))
    except PermissionError:
        return []

    for name in entries:
        if not _should_include(name):
            continue

        full = os.path.join(abs_dir, name)

        if os.path.isdir(full):
            children = []
            if depth + 1 < max_depth:
                children = _walk_dir(full, max_depth, depth + 1)
            file_count = _count_files(children)
            items.append({
                "type": "dir",
                "name": name,
                "path": full,
                "count": str(file_count) if file_count else "",
                "children": children,
            })
        else:
            ext = os.path.splitext(name)[1].lower()
            if INCLUDE_EXTENSIONS and ext not in INCLUDE_EXTENSIONS:
                continue

            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0

            if size > MAX_FILE_SIZE:
                continue

            items.append({
                "type": "file",
                "name": name,
                "path": full,
            })

    return items


def _count_files(tree: list[dict]) -> int:
    """Count files in a tree (recursively)."""
    count = 0
    for item in tree:
        if item["type"] == "file":
            count += 1
        elif item["type"] == "dir":
            count += _count_files(item.get("children", []))
    return count


def get_file_tree(abs_dir: str) -> list[dict]:
    """Return the file tree starting from abs_dir (must be an absolute path)."""
    if not abs_dir or not os.path.isabs(abs_dir):
        abs_dir = EDITOR_ROOT()
    return _walk_dir(abs_dir)


# ─── File content ─────────────────────────────────────────────────────────────

def read_file_content(path: str) -> tuple[str, str]:
    """Read a file's content.

    path may be absolute or relative (to EDITOR_ROOT).
    Returns (content, error). One is always None.
    """
    full = path if os.path.isabs(path) else os.path.join(EDITOR_ROOT(), path)
    try:
        if not os.path.isfile(full):
            return "", f"File not found: {path}"
        size = os.path.getsize(full)
        if size > MAX_FILE_SIZE:
            return "", f"File too large ({size // 1024} KB). Limit: {MAX_FILE_SIZE // 1024} KB"
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            return f.read(), ""
    except Exception as e:
        return "", str(e)


# ─── File watcher ─────────────────────────────────────────────────────────────

_watch_event_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
# Tuples of (rel_path, event_type) — event_type is "change" or "delete"


async def _fs_watcher_loop() -> None:
    """Background loop that watches the filesystem and queues change events.

    Uses watchdog when available, falls back to periodic polling.
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileDeletedEvent
    except ImportError:
        logger.warning("[WebEditor] watchdog not installed — falling back to polling")
        await _polling_watcher_loop()
        return

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.is_directory:
                return
            rel = os.path.relpath(event.src_path, EDITOR_ROOT()).replace(os.sep, "/")
            _watch_event_queue.put_nowait((rel, "change"))

        def on_deleted(self, event):
            if event.is_directory:
                return
            rel = os.path.relpath(event.src_path, EDITOR_ROOT()).replace(os.sep, "/")
            _watch_event_queue.put_nowait((rel, "delete"))

    handler = _Handler()
    observer = Observer()
    observer.schedule(handler, EDITOR_ROOT(), recursive=True)
    observer.start()
    logger.info(f"[WebEditor] File watcher started (watchdog) on {EDITOR_ROOT()}")

    try:
        while True:
            await asyncio.sleep(POLL_INTERVAL)
    except asyncio.CancelledError:
        observer.stop()
        observer.join(timeout=2)
        raise


async def _polling_watcher_loop() -> None:
    """Fallback: poll filesystem for changes every POLL_INTERVAL seconds."""
    # Track file mtimes
    mtimes: dict[str, float] = {}

    while True:
        try:
            for item in _walk_flat(EDITOR_ROOT()):
                rel_path = item["path"]
                full = os.path.join(EDITOR_ROOT(), rel_path)
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    mtime = 0

                prev = mtimes.get(rel_path)
                if prev is not None and mtime != prev and mtime > prev:
                    _watch_event_queue.put_nowait((rel_path, "change"))
                mtimes[rel_path] = mtime
        except Exception as e:
            logger.debug(f"[WebEditor] Polling error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


def _walk_flat(root: str, rel: str = "") -> list[dict]:
    """Flatten walk returning only files with their relative paths."""
    items = []
    try:
        entries = os.listdir(os.path.join(root, rel) if rel else root)
    except PermissionError:
        return []
    for name in sorted(entries):
        if not _should_include(name):
            continue
        full = os.path.join(root, rel, name) if rel else os.path.join(root, name)
        if os.path.isdir(full):
            items.extend(_walk_flat(root, os.path.join(rel, name) if rel else name))
        else:
            ext = os.path.splitext(name)[1].lower()
            if INCLUDE_EXTENSIONS and ext not in INCLUDE_EXTENSIONS:
                continue
            items.append({"path": os.path.join(rel, name) if rel else name})
    return items


async def _broadcast_loop() -> None:
    """Process the watch event queue and broadcast changes to clients."""
    while True:
        try:
            rel_path, event = await _watch_event_queue.get()
        except asyncio.CancelledError:
            break

        if event == "change":
            content, err = read_file_content(rel_path)
            if err:
                logger.debug(f"[WebEditor] Error reading {rel_path}: {err}")
                continue
            await _broadcast({
                "type": "content",
                "path": rel_path,
                "content": content,
            }, filter_path=rel_path)
        elif event == "delete":
            # Notify clients — they might want to show "file deleted"
            await _broadcast({
                "type": "toast",
                "text": f"<strong>{rel_path}</strong> was deleted or moved.",
            }, filter_path=rel_path)


_watcher_task: Optional[asyncio.Task] = None
_broadcast_task: Optional[asyncio.Task] = None


async def _start_watchers() -> None:
    global _watcher_task, _broadcast_task
    if _watcher_task is not None or _broadcast_task is not None:
        return
    _watcher_task = asyncio.create_task(_fs_watcher_loop())
    _broadcast_task = asyncio.create_task(_broadcast_loop())


async def _stop_watchers() -> None:
    global _watcher_task, _broadcast_task
    for task in (_watcher_task, _broadcast_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _watcher_task = None
    _broadcast_task = None


# ─── HTTP routes ──────────────────────────────────────────────────────────────

@router.get("/")
async def editor_page():
    """Serve the editor HTML client."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    html_path = os.path.join(static_dir, "editor.html")
    if os.path.exists(html_path):
        from fastapi.responses import FileResponse
        return FileResponse(html_path, media_type="text/html")
    return {"error": "editor.html not found"}


# ─── WebSocket route ──────────────────────────────────────────────────────────

# ─── Riven events integration ──────────────────────────────────────────────

_COLOR_PALETTE = [
    "#e06c75", "#98c379", "#e5c07b", "#61afef",
    "#c678dd", "#56b6c2", "#be5046", "#1aaa85",
]


async def _on_file_changed(path: str, content: str, start: int | None = None,
                           end: int | None = None, who: str | None = None) -> None:
    """Handle file_changed events from Riven's file module.

    Broadcasts updated content to all web editor clients watching the file,
    and optionally highlights the changed region.
    """
    await _broadcast({
        "type": "content",
        "path": path,
        "content": content,
        "source": "riven",  # tells frontend it's a Riven edit, not user
    }, filter_path=path)
    if start and end:
        label = f"Riven" if not who else who.split("-")[0]
        await broadcast_highlight(path, start, end, label=label)


async def _on_lock_acquired(path: str, holder: str, context: str) -> None:
    """Handle lock_acquired events — update awareness, warn other editors."""
    logger.debug(f"[WebEditor] Lock acquired on {path} by {holder} ({context})")
    # Add holder to awareness
    if path not in _awareness:
        _awareness[path] = []
    # Avoid duplicates
    if not any(h["session_id"] == holder for h in _awareness[path]):
        color = _COLOR_PALETTE[len(_awareness[path]) % len(_COLOR_PALETTE)]
        _awareness[path].append({"session_id": holder, "color": color})
    await _broadcast({
        "type": "awareness",
        "path": path,
        "awareness": _awareness[path],
    }, filter_path=path)


async def _on_lock_released(path: str, holder: str, context: str) -> None:
    """Handle lock_released events — remove from awareness."""
    logger.debug(f"[WebEditor] Lock released on {path} by {holder} ({context})")
    if path in _awareness:
        _awareness[path] = [h for h in _awareness[path] if h["session_id"] != holder]
        if not _awareness[path]:
            del _awareness[path]
    await _broadcast({
        "type": "awareness",
        "path": path,
        "awareness": _awareness.get(path, []),
    }, filter_path=path)


async def _on_awareness_updated(path: str, session_id: str | None = None,
                                 cursor: int | None = None, label: str = "") -> None:
    """Handle awareness_updated events — broadcast live cursor/selection."""
    if not session_id:
        return
    if path not in _awareness:
        _awareness[path] = []
    # Update cursor position for this session
    for h in _awareness[path]:
        if h["session_id"] == session_id:
            h["cursor"] = cursor
            h["label"] = label
            break
    else:
        color = _COLOR_PALETTE[len(_awareness[path]) % len(_COLOR_PALETTE)]
        _awareness[path].append({"session_id": session_id, "color": color,
                                 "cursor": cursor, "label": label})
    await _broadcast({
        "type": "awareness",
        "path": path,
        "awareness": _awareness[path],
    }, filter_path=path)


def _init_riven_events() -> None:
    """Register event handlers. Safe to call multiple times."""
    if events is None:
        return
    events.register_handler("file_changed", _on_file_changed)
    events.register_handler("lock_acquired", _on_lock_acquired)
    events.register_handler("lock_released", _on_lock_released)
    events.register_handler("awareness_updated", _on_awareness_updated)
    logger.debug("[WebEditor] Riven event handlers registered")


_init_riven_events()


@router.websocket("/ws")
async def editor_ws(ws: WebSocket):
    await ws.accept()
    client = await _add_client(ws)
    uid = client.uid
    session_id = None
    instance_id = None

    # Start watchers on first connection
    await _start_watchers()

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=WS_HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            # Capture instance_id and session_id from the first message
            if instance_id is None:
                instance_id = msg.get("instance_id")
                if instance_id:
                    client.instance_id = instance_id
                    logger.debug(f"[WebEditor] Client {uid} is editor instance {instance_id}")

            if session_id is None:
                session_id = msg.get("session_id") or msg.get("session")
                if session_id:
                    client.session_id = session_id
                    logger.debug(f"[WebEditor] Client {uid} associated with session {session_id}")

            if msg_type in ("list", "refresh"):
                abs_path = msg.get("abs_path", "") or EDITOR_ROOT()
                tree = get_file_tree(abs_path)
                await ws.send_text(json.dumps({
                    "type": "tree",
                    "files": tree,
                    "abs_path": abs_path,
                }))

            elif msg_type == "navigate":
                abs_path = msg.get("abs_path", "") or EDITOR_ROOT()
                tree = get_file_tree(abs_path)
                await ws.send_text(json.dumps({
                    "type": "tree",
                    "files": tree,
                    "abs_path": abs_path,
                }))

            elif msg_type == "open":
                path = msg.get("path", "")
                client.open_paths.add(path)
                content, err = read_file_content(path)
                if err:
                    await ws.send_text(json.dumps({"type": "toast", "text": f"Error: {err}"}))
                else:
                    await ws.send_text(json.dumps({
                        "type": "content",
                        "path": path,
                        "content": content,
                    }))

            elif msg_type == "pong":
                pass  # keepalive acknowledged

    except WebSocketDisconnect:
        logger.debug(f"[WebEditor] Client {uid} disconnected")

    finally:
        await _remove_client(uid)
        # NOTE: we don't stop watchers on disconnect — other clients may be connected


# ─── Programmatic broadcast API (called by api.py) ────────────────────────────

async def broadcast_update(rel_path: str) -> None:
    """Broadcast a file's current content to clients watching rel_path.

    Called by the API layer when the file module makes an edit.
    """
    content, err = read_file_content(rel_path)
    if err:
        logger.debug(f"[WebEditor] broadcast_update error for {rel_path}: {err}")
        return
    await _broadcast({
        "type": "content",
        "path": rel_path,
        "content": content,
    }, filter_path=rel_path)


async def broadcast_highlight(rel_path: str, start: int, end: int, label: str = "") -> None:
    """Broadcast a line highlight to clients watching rel_path."""
    await _broadcast({
        "type": "highlight",
        "path": rel_path,
        "start": start,
        "end": end,
        "label": label,
    }, filter_path=rel_path)


async def broadcast_speak(rel_path: str, text: str) -> None:
    """Broadcast a toast message to clients watching rel_path."""
    await _broadcast({
        "type": "toast",
        "text": text,
    }, filter_path=rel_path)


async def broadcast_to_all(msg: dict) -> None:
    """Broadcast a message to ALL connected clients (no path filter)."""
    await _broadcast(msg, filter_path=None)


async def broadcast_global_speak(text: str) -> None:
    """Broadcast a toast message to ALL clients (no filtering)."""
    await _broadcast({"type": "toast", "text": text})
