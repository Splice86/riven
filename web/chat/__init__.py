"""Riven Chat UI module - web interface for conversational AI.

Provides:
- Session management (session IDs stored client-side)
- Shard selection
- Chat endpoints
"""

from .api import register_routes

__all__ = ["register_routes"]
