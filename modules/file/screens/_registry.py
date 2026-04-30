"""In-memory registry for screen state.

Screens are ephemeral — tied to the current Riven session.
No DB persistence. State lives here as long as the server is running.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastapi import WebSocket

from . import constants as C

import logging

logger = logging.getLogger(__name__)


# Session-scoped sync-accessible cache for {screens} context injection.
# Updated synchronously (no lock needed — only written by async connect/disconnect
# after each yields, and read by the sync context builder between calls).
_session_screens: dict[str, list[dict]] = {}


class ScreenConnection:
    __slots__ = (
        "uid",
        "ws",
        "session_id",
        "bound_path",
        "bound_version",
        "client_name",
    )

    def __init__(
        self,
        uid: str,
        ws: WebSocket,
        session_id: str = "",
        bound_path: str = "",
        bound_version: int = 0,
        client_name: str = "Screen",
    ):
        self.uid = uid
        self.ws = ws
        self.session_id = session_id
        self.bound_path = bound_path
        self.bound_version = bound_version
        self.client_name = client_name

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "session_id": self.session_id,
            "bound_path": self.bound_path,
            "bound_version": self.bound_version,
            "client_name": self.client_name,
        }


class ScreenRegistry:
    _connections: dict[str, ScreenConnection] = {}
    _lock = asyncio.Lock()
    _version: dict[str, int] = {}  # path -> edit version counter

    async def connect(self, screen: ScreenConnection) -> None:
        async with self._lock:
            self._connections[screen.uid] = screen
        _session_screens.setdefault(screen.session_id, []).append(screen.to_dict())
        logger.info(f"[Screens] Connected: uid={screen.uid} session={screen.session_id} client={screen.client_name}")

    async def disconnect(self, uid: str) -> None:
        async with self._lock:
            screen = self._connections.pop(uid, None)
        if screen:
            for lst in _session_screens.values():
                lst[:] = [s for s in lst if s["uid"] != uid]
        logger.info(f"[Screens] Disconnected: uid={uid}")

    async def get(self, uid: str) -> Optional[ScreenConnection]:
        async with self._lock:
            return self._connections.get(uid)

    async def get_by_path(self, path: str) -> list[ScreenConnection]:
        """Find all screens bound to a path.

        Path is normalized before comparison to handle relative vs absolute
        path variants (e.g. './foo.py' vs '/abs/foo.py').
        """
        abs_path = os.path.abspath(path)
        async with self._lock:
            return [s for s in self._connections.values() if s.bound_path == abs_path]

    async def list_all(self) -> list[ScreenConnection]:
        async with self._lock:
            return list(self._connections.values())

    def _resolve(self, uid: str) -> Optional[ScreenConnection]:
        """Resolve a screen by UID without acquiring the lock.

        Used internally by methods that already hold the lock.
        """
        return self._connections.get(uid)

    async def bind(
        self,
        uid: str,
        path: str,
    ) -> bool:
        async with self._lock:
            screen = self._connections.get(uid)
            if not screen:
                return False

            # Always store normalized absolute path to avoid mismatches
            # when comparing paths passed as relative vs absolute
            abs_path = os.path.abspath(path)
            screen.bound_path = abs_path
            # Increment version atomically
            current = self._version.get(abs_path, 0)
            self._version[abs_path] = current + 1
            screen.bound_version = current + 1

            self._sync_session_cache(screen)

        logger.info(f"[Screens] Bound: uid={uid} path={abs_path}")
        return True

    async def release(self, uid: str) -> bool:
        async with self._lock:
            screen = self._resolve(uid)
            if not screen:
                return False
            screen.bound_path = ""
            screen.bound_version = 0

            self._sync_session_cache(screen)

        logger.info(f"[Screens] Released: uid={uid}")
        return True

    def _sync_session_cache(self, screen: ScreenConnection) -> None:
        """Mutate the stale cache entry in _session_screens to match ScreenConnection.

        Called after bind/release to keep the context cache in sync.
        """
        session_list = _session_screens.get(screen.session_id)
        if not session_list:
            return
        for entry in session_list:
            if entry.get("uid") == screen.uid:
                entry["bound_path"] = screen.bound_path
                entry["bound_version"] = screen.bound_version
                return

    async def touch(self, uid: str) -> bool:
        """Update a screen's last-seen (keepalive)."""
        async with self._lock:
            screen = self._resolve(uid)
            return screen is not None

    async def get_version(self, path: str) -> int:
        async with self._lock:
            return self._version.get(os.path.abspath(path), 0)

    async def bump_version(self, path: str) -> int:
        async with self._lock:
            abs_path = os.path.abspath(path)
            current = self._version.get(abs_path, 0)
            self._version[abs_path] = current + 1
            return current + 1


registry = ScreenRegistry()


def get_session_screens_sync(session_id: str) -> list[dict]:
    """Sync read of session screens — called by screen_context()."""
    return _session_screens.get(session_id, [])
