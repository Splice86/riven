"""Simple pub/sub event bus.

Modules publish events; consumers subscribe. Errors in handlers are swallowed
so a crashing subscriber can't break the publishing module.

Usage:
    # Consumer subscribes at startup
    from events import subscribe, publish
    subscribe("file_replaced", my_handler)

    # Module emits during normal operation
    publish("file_replaced", path=rel_path, content=content)
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger("events")

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
    """Remove all handlers. Pass an event name to clear only that event."""
    global _handlers
    if event is None:
        _handlers.clear()
    elif event in _handlers:
        del _handlers[event]
