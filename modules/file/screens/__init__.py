"""Screen subsystem for the file module.

Exposes live file view broadcasts to remote screens via WebSocket.
Screens register with a UID (in-memory, session-scoped), and
Riven binds them to files for live diff streaming.

Components:
  - _registry:  In-memory tracking of active WebSocket connections
  - _diff.py:    Line-level diffing engine
  - _broadcaster: Broadcast primitives (snapshot/diff/bind/release)
  - _ws.py:      FastAPI WebSocket route
  - _tools.py:   Riven tool functions (screen_list, screen_bind, etc.)
  - constants.py: Keyword and SQL query constants
  - _db.py:      Stub shim (no-op, kept for compat)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

# Re-export for convenience
from . import constants as C
from . import _broadcaster as broadcaster
from . import _db as _db_stub  # kept so existing imports don't break
from ._broadcaster import broadcast_edit, broadcast_release_for_path, send_snapshot_to_uid, send_snapshots_for_path
from ._registry import registry
from ._tools import screen_bind, screen_list, screen_release, screen_status, screen_highlight

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Module-level flag: enables screen broadcasting for this session
# Set to True by the file module on first edit if screens are registered
_screen_broadcast_enabled = False


def register_routes(app: "FastAPI") -> None:
    """Register WebSocket and HTTP routes for the screens subsystem."""
    from . import _ws
    app.include_router(_ws.router)
    logger.info("[Screens] WebSocket routes registered at /module/file/screens/stream")


def enable_broadcast() -> None:
    """Enable screen broadcasts for this process."""
    global _screen_broadcast_enabled
    _screen_broadcast_enabled = True
    logger.info("[Screens] Broadcast enabled")


def is_broadcast_enabled() -> bool:
    """Check if screen broadcasts are enabled."""
    return _screen_broadcast_enabled
