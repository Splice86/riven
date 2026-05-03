"""Chat UI API - session management and shard selection.

Session IDs are generated client-side and stored in browser localStorage.
This module provides endpoints for shard discovery and session reset.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import yaml

from config import get

logger = logging.getLogger("web.chat.api")

router = APIRouter(prefix="/api/v1/chat", tags=["web.chat.api"])

# ─── Shard discovery ──────────────────────────────────────────────────────────

def _load_shards() -> list[dict]:
    """Load all shard configs for the dropdown."""
    shards_dir = os.path.join(os.path.dirname(__file__), "..", "..", "shards")
    shards = []
    
    if os.path.isdir(shards_dir):
        for filename in sorted(os.listdir(shards_dir)):
            if not filename.endswith(".yaml"):
                continue
            filepath = os.path.join(shards_dir, filename)
            try:
                with open(filepath) as f:
                    data = yaml.safe_load(f)
                    if data and "name" in data:
                        shards.append({
                            "name": data.get("name"),
                            "display_name": data.get("display_name", data["name"]),
                            "description": data.get("description", ""),
                        })
            except Exception as e:
                logger.warning(f"Failed to load shard {filename}: {e}")
    
    return shards


@router.get("/shards")
def list_shards():
    """List available shards for the dropdown."""
    shards = _load_shards()
    default = get("default_shard", "codehammer")
    return {
        "shards": shards,
        "default": default,
    }


# ─── Session management ───────────────────────────────────────────────────────

class ResetRequest(BaseModel):
    session_id: str


@router.post("/reset")
def reset_session(req: ResetRequest):
    """Reset a session by clearing its context from Context DB."""
    from db import delete_session

    try:
        delete_session(session=req.session_id)
    except Exception as e:
        logger.warning(f"Context DB reset failed: {e}")

    return {"ok": True}


@router.delete("/session/{session_id}")
def delete_session_endpoint(session_id: str):
    """Delete a session and all its context."""
    from db import delete_session

    try:
        rows = delete_session(session=session_id)
    except Exception as e:
        raise HTTPException(500, f"Context database error: {e}")

    return {"ok": True, "session_id": session_id, "deleted": rows}


# ─── Route registration ───────────────────────────────────────────────────────

def register_routes(app):
    """Register chat UI routes with the main FastAPI app."""
    app.include_router(router)
    logger.info("[Chat API] Registered routes under /api/v1/chat")
