"""HTTP API for the web file editor.

Provides endpoints the file module calls to drive live updates,
highlights, and messages in connected browser editors.

These are all fire-and-forget — errors are logged but not surfaced
to the caller to avoid coupling the file module to editor failures.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import editor
from .config import get_root_dir, MAX_FILE_SIZE

logger = logging.getLogger("web.editor.api")

router = APIRouter(tags=["web.editor.api"])

# ─── Request models ───────────────────────────────────────────────────────────

class UpdateRequest(BaseModel):
    path: str  # Relative path from project root


class HighlightRequest(BaseModel):
    path: str
    start: int = 1  # 1-based inclusive
    end: int = 1    # 1-based inclusive
    label: str = ""


class SpeakRequest(BaseModel):
    text: str
    path: str = ""  # Optional — filters to clients watching this file


class SaveRequest(BaseModel):
    path: str      # Relative path from project root
    content: str   # New file content


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/update")
async def api_update(req: UpdateRequest):
    """Broadcast a file's current content to all editors watching the path."""
    try:
        await editor.broadcast_update(req.path)
    except Exception as e:
        logger.warning(f"[WebEditor API] update failed for {req.path}: {e}")
    return {"ok": True}


@router.post("/highlight")
async def api_highlight(req: HighlightRequest):
    """Highlight a line range on all editors showing the file."""
    try:
        await editor.broadcast_highlight(req.path, req.start, req.end, req.label)
    except Exception as e:
        logger.warning(f"[WebEditor API] highlight failed for {req.path}: {e}")
    return {"ok": True}


@router.post("/speak")
async def api_speak(req: SpeakRequest):
    """Show a toast message on all editors (optionally filtered by path)."""
    try:
        if req.path:
            await editor.broadcast_speak(req.path, req.text)
        else:
            await editor.broadcast_global_speak(req.text)
    except Exception as e:
        logger.warning(f"[WebEditor API] speak failed: {e}")
    return {"ok": True}


@router.post("/save")
async def api_save(req: SaveRequest):
    """Write content to disk and broadcast the change to all other clients."""
    if len(req.content.encode('utf-8')) > MAX_FILE_SIZE:
        raise HTTPException(413, f"Content too large. Max: {MAX_FILE_SIZE // 1024} KB")

    root = get_root_dir()
    full = os.path.join(root, req.path)

    if not os.path.isfile(full):
        raise HTTPException(404, f"File not found: {req.path}")

    try:
        with open(full, "w", encoding="utf-8") as f:
            f.write(req.content)
    except Exception as e:
        raise HTTPException(500, f"Write failed: {e}")

    logger.info(f"[WebEditor] Saved {req.path} ({len(req.content)} bytes)")

    # Broadcast updated content to ALL clients watching this file
    # (including the saver, so their serverContent gets synced)
    await editor.broadcast_update(req.path)

    return {"ok": True}


# ─── Debug endpoints ──────────────────────────────────────────────────────────

@router.get("/tree")
async def api_tree():
    """Return the current file tree (debugging)."""
    return editor.get_file_tree()
