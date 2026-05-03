"""Pub/sub event bus + distributed file lock registry.

Provides two interconnected systems:

  1. Event Bus: lightweight pub/sub. Modules publish events; consumers subscribe.
     Errors in handlers are swallowed so a crashing subscriber can't break the
     publishing module.

  2. Lock Registry: exclusive advisory locks on files. Any editor (Riven or human)
     must acquire a lock before mutating a file, then release it when done.
     Waiters sleep on an async condition until the lock is free.

Usage:
    # Events
    from events import register_handler, publish
    register_handler("file_changed", my_handler)
    publish("file_changed", path=rel_path, start=10, end=20, content=...)

    # Locks
    from events import acquire_lock, release_lock, get_lock_state
    async with acquire_lock(path, holder="session-abc"):
        ...  # edit the file
    # lock auto-released
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("events")

# ─── Lock Registry ─────────────────────────────────────────────────────────────

@dataclass
class LockInfo:
    """Describes who holds an exclusive lock on a file.

    Also acts as an async context manager so callers can use:
        async with acquire_lock(path, holder) as lock_info:
            ...  # edit the file
        # lock auto-released
    """
    path: str
    holder: str           # session_id for Riven, "human:{name}" for browsers
    instance_id: str | None = None
    context: str = ""     # e.g. "replace_text", "David editing"
    acquired_at: float = field(default_factory=time.time)

    async def __aenter__(self) -> "LockInfo":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await release_lock(self.path, self.holder)


# Alias for asyncio.TimeoutError so callers can catch a named exception
LockTimeoutError = asyncio.TimeoutError

from contextlib import asynccontextmanager


_locks: dict[str, LockInfo] = {}          # path → LockInfo
_locks_lock: asyncio.Lock | None = None       # lazily initialized per-event-loop


def _get_locks_lock() -> asyncio.Lock:
    """Return the Lock for serializing _locks access, creating it if needed.

    Created per-event-loop to avoid asyncio primitives being bound to the
    first loop that existed at module-import time.
    """
    global _locks_lock
    if _locks_lock is None or (_locks_lock._loop is not None and _locks_lock._loop is not asyncio.get_running_loop()):
        _locks_lock = asyncio.Lock()
    return _locks_lock


def get_lock_state(path: str) -> LockInfo | None:
    """Return the current lock for a path, or None if unlocked."""
    return _locks.get(path)


def is_browser_lock(lock: LockInfo) -> bool:
    """Return True if the lock holder looks like a browser editor instance.
    
    Browser instances use instance IDs starting with 'ed-' (e.g. 'ed-abc12345').
    Riven session IDs are generally longer UUID-like strings.
    """
    return lock.holder.startswith('ed-')


def get_all_locks() -> dict[str, LockInfo]:
    """Return a copy of the current lock table."""
    return dict(_locks)


@asynccontextmanager
async def acquire_lock(
    path: str,
    holder: str,
    timeout: float = 30.0,
    context: str = "",
    instance_id: str | None = None,
) -> LockInfo:
    """Acquire an exclusive lock on path for holder.

    If the file is locked by someone else, waits up to `timeout` seconds for it
    to become available. Raises asyncio.TimeoutError if the wait expires.
    Other clients see "X is editing this file" and Riven sees "timed out".

    Usage (preferred — auto-releases on any exit from the block):
        async with acquire_lock(path, holder) as lock_info:
            ...  # edit the file
        # lock auto-released (even on exception)

    Or (manual):
        lock = await acquire_lock(path, holder)  # note: await, not async with
        try:
            ...
        finally:
            await release_lock(path, holder)
    """
    start = time.time()
    async with _get_locks_lock():
        while path in _locks:
            existing = _locks[path]
            if existing.holder == holder:
                # Re-entrant: already held by us — just refresh timestamp
                existing.acquired_at = time.time()
                yield existing
                return
            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"Timed out waiting for lock on {path} "
                    f"(held by {existing.holder}: {existing.context})")
            logger.debug(
                f"[events] waiting for lock on {path} "
                f"(held by {existing.holder}, timeout={remaining:.1f}s)")
            # Release the lock, yield to event loop, re-acquire
            await asyncio.sleep(min(remaining, 0.05))

        lock_info = LockInfo(
            path=path,
            holder=holder,
            instance_id=instance_id,
            context=context,
            acquired_at=time.time(),
        )
        _locks[path] = lock_info
        logger.debug(f"[events] lock acquired: {path} by {holder}")

    # Publish AFTER releasing the lock to avoid deadlock with handlers
    publish("lock_acquired", path=path, holder=holder, context=context)
    yield lock_info

    # Auto-release when exiting the context manager block
    await release_lock(path, holder)


async def release_lock(path: str, holder: str) -> bool:
    """Release a lock. Idempotent — returns True if released, False if not held."""
    async with _get_locks_lock():
        current = _locks.get(path)
        if current is None:
            return False
        if current.holder != holder:
            logger.warning(
                f"[events] release_lock mismatch: {path} held by "
                f"{current.holder}, caller={holder}")
            return False
        lock_context = current.context
        del _locks[path]
        logger.debug(f"[events] lock released: {path} by {holder}")
    # Publish OUTSIDE the lock to avoid deadlock (same reason as above).
    publish("lock_released", path=path, holder=holder, context=lock_context)
    return True


# ─── Awareness Registry ─────────────────────────────────────────────────────────
# Tracks which clients have which files open (for multi-user awareness display).

_awareness: dict[str, dict] = {}   # client_id → {session_id, instance_id, open_files, name}


def update_awareness(client_id: str, data: dict) -> None:
    """Update or merge awareness data for a client. Keys: session_id,
    instance_id, open_files (list[str]), name (str)."""
    _awareness.setdefault(client_id, {}).update(data)


def get_awareness(path: str | None = None) -> list[dict]:
    """Return all awareness entries. If path is given, only clients with that file open."""
    result = []
    for cid, data in _awareness.items():
        if path is None or path in data.get("open_files", []):
            result.append({"client_id": cid, **data})
    return result


def remove_awareness(client_id: str) -> None:
    _awareness.pop(client_id, None)


# ─── Pub/Sub Event Bus ──────────────────────────────────────────────────────────

# event → list of (handler, is_async)
_handlers: dict[str, list[tuple[Callable, bool]]] = {}


def subscribe(event: str, handler: Callable) -> None:
    """Register a handler for an event.

    Handler is called with the keyword arguments passed to publish().
    Duplicates are allowed (a handler can be registered multiple times).
    """
    is_async = asyncio.iscoroutinefunction(handler)
    _handlers.setdefault(event, []).append((handler, is_async))
    logger.debug(f"[events] subscribed '{event}' → {handler.__name__} (async={is_async})")


def unsubscribe(event: str, handler: Callable) -> None:
    """Remove a specific handler from an event."""
    if event not in _handlers:
        return
    _handlers[event] = [
        (h, ia) for h, ia in _handlers[event] if h != handler
    ]
    if not _handlers[event]:
        del _handlers[event]


# Aliases for a more descriptive API
register_handler = subscribe
unregister_handler = unsubscribe


def publish(event: str, **data: Any) -> None:
    """Fire an event to all registered handlers.

    Sync handlers run immediately. Async handlers are scheduled as fire-and-forget
    tasks so publish() itself never blocks or awaits.
    """
    if event not in _handlers:
        return

    for handler, is_async in _handlers[event]:
        try:
            if is_async:
                _run_async(handler, event, data)
            else:
                handler(**data)
        except Exception as e:
            logger.warning(f"[events] handler '{handler.__name__}' raised for '{event}': {e}")


def _run_async(handler: Callable, event: str, data: dict) -> None:
    """Run an async handler. Uses the running loop if available, or spawns a thread."""
    try:
        loop = asyncio.get_running_loop()
        asyncio.create_task(_safe_await(handler, event, data))
    except RuntimeError:
        # No running loop — spin one up in a background thread
        thread = threading.Thread(
            target=_run_in_thread,
            args=(handler, event, data),
            daemon=True,
        )
        thread.start()


def _run_in_thread(handler: Callable, event: str, data: dict) -> None:
    """Execute an async handler in a new event loop (no loop available in thread)."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_safe_await(handler, event, data))
    except Exception as e:
        logger.warning(f"[events] async handler '{handler.__name__}' raised for '{event}': {e}")
    finally:
        loop.close()


async def _safe_await(handler: Callable, event: str, data: dict) -> None:
    """Await a handler, logging any errors."""
    try:
        await handler(**data)
    except Exception as e:
        logger.warning(f"[events] async handler '{handler.__name__}' raised for '{event}': {e}")


def clear(event: str | None = None) -> None:
    """Remove all handlers and optionally all locks. Pass an event name to clear
    only that event's handlers."""
    global _handlers
    if event is None:
        _handlers.clear()
        _locks.clear()
    elif event in _handlers:
        del _handlers[event]


# Register Riven's event handlers so they are ready when events is imported.
# Import from web.editor.editor which calls _init_riven_events() on its own import.
from web.editor.editor import _init_riven_events
_init_riven_events()
