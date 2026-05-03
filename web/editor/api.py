"""HTTP API for the web file editor.

Provides endpoints the file module calls to drive live updates,
highlights, and messages in connected browser editors.

These are all fire-and-forget — errors are logged but not surfaced
to the caller to avoid coupling the file module to editor failures.
"""

from __future__ import annotations

import logging
import os
import subprocess
import textwrap
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
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
    holder: str = ""  # Lock holder — must match the current lock owner


class LockRequest(BaseModel):
    holder: str           # Who is acquiring the lock
    context: str = ""     # What operation is being performed
    timeout: float = 30.0  # Max seconds to wait for the lock


class AwarenessRequest(BaseModel):
    session_id: str | None = None
    cursor: int | None = None
    label: str = ""


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
            await editor.broadcast_to_all({"type": "toast", "text": req.text})
    except Exception as e:
        logger.warning(f"[WebEditor API] speak failed: {e}")
    return {"ok": True}


@router.post("/save")
async def api_save(req: SaveRequest):
    """Write content to disk, auto-commit to git, and broadcast the change."""
    if len(req.content.encode('utf-8')) > MAX_FILE_SIZE:
        raise HTTPException(413, f"Content too large. Max: {MAX_FILE_SIZE // 1024} KB")

    # Enforce lock ownership: editor must hold the lock to save.
    # If the lock is held by someone else (or no one), reject the edit.
    if req.holder:
        import events as _ev
        if _ev is not None:
            state = _ev.get_lock_state(req.path)
            logger.info(f"[SAVE] holder={req.holder} lock_state={state.holder if state else 'NONE'}")
            if state is None:
                raise HTTPException(409, f"No lock held on {req.path} — acquire one first")
            if state.holder != req.holder:
                raise HTTPException(409,
                    f"Lock held by {state.holder} — cannot save. "
                    f"Wait for it to be released.")

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

    # Auto-commit the save to git so undo can roll back to this point.
    _auto_commit(req.path, req.content)

    # Release the lock now that we're done editing.
    if req.holder:
        import events as _ev
        if _ev is not None:
            try:
                await _ev.release_lock(req.path, req.holder)
                await editor.broadcast_lock_update(req.path)
                logger.info(f"[LOCK] Released after save: holder={req.holder} path={req.path}")
            except Exception as e:
                logger.warning(f"[WebEditor API] release after save failed for {req.path}: {e}")

    return {"ok": True}


def _to_rel(path: str) -> str:
    """Convert an absolute path to a path relative to the editor root."""
    root = get_root_dir()
    if path.startswith(root + '/'):
        return path[len(root) + 1:]
    return path


def _auto_commit(rel_path: str, content: str) -> None:
    """Commit the saved file to git, best-effort.

    This makes undo work: each save becomes a git checkpoint the user can
    roll back to with a single undo operation.
    """
    root = get_root_dir()
    full = os.path.join(root, rel_path)
    if not os.path.isfile(full):
        return

    # Ensure git user is set — author name appears in `git log`
    _ensure_git_user(root)

    filename = rel_path.split('/')[-1]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    msg = textwrap.dedent(f"""\
        Edit: {filename}

        Editor auto-save ({ts})
        Path: {rel_path}
        Size: {len(content)} bytes
    """).strip()

    try:
        subprocess.run(
            ["git", "add", rel_path],
            cwd=root,
            capture_output=True,
            check=False,
        )
        cp = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if cp.returncode == 0:
            logger.info(f"[WebEditor] Auto-committed {rel_path}")
        elif "nothing to commit" in cp.stderr.lower() or "nothing to commit" in cp.stdout.lower():
            logger.debug(f"[WebEditor] No changes to commit for {rel_path}")
        else:
            logger.warning(f"[WebEditor] git commit failed for {rel_path}: {cp.stderr.strip()}")
    except Exception as e:
        logger.warning(f"[WebEditor] _auto_commit exception for {rel_path}: {e}")


def _ensure_git_user(repo_root: str) -> None:
    """Set git user.email if not already configured in the repo.

    Needed so commits don't fail with 'please tell me who you are'.
    """
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return  # already configured
        subprocess.run(
            ["git", "config", "user.email", "riven@localhost"],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["git", "config", "user.name", "Riven Editor"],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
    except Exception:
        pass


# ─── Undo ─────────────────────────────────────────────────────────────────────


@router.post("/undo")
async def api_undo(path: str = Query(default=""), session_id: str = Query(default="")):
    """Revert a file to its last committed state via `git checkout HEAD -- <path>`.

    Returns the file content after undo so the editor can display it immediately.
    """
    if not path:
        raise HTTPException(400, "path is required")

    root = get_root_dir()
    full = os.path.join(root, path)

    if not os.path.isfile(full):
        raise HTTPException(404, f"File not found: {path}")

    # Check the file has a commit history
    cp = subprocess.run(
        ["git", "log", "--oneline", "-n1", "--", path],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0 or not cp.stdout.strip():
        raise HTTPException(409, f"No git history for {path} — cannot undo")

    last_commit = cp.stdout.strip()

    # Perform the revert
    try:
        result = subprocess.run(
            ["git", "checkout", "HEAD", "--", path],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise HTTPException(500, f"git checkout failed: {result.stderr.strip()}")
    except Exception as e:
        raise HTTPException(500, f"Undo failed: {e}")

    # Read the reverted content
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        raise HTTPException(500, f"Could not read reverted file: {e}")

    logger.info(f"[WebEditor] Undo on {path} → back to commit: {last_commit}")

    # Broadcast the reverted content to all clients watching this file
    await editor.broadcast_update(path)

    return {
        "ok": True,
        "path": path,
        "content": content,
        "commit": last_commit,
    }


# ─── Lock endpoints ───────────────────────────────────────────────────────────

@router.get("/lock/{path:path}")
async def api_get_lock(path: str):
    """Return the current lock state for a file."""
    try:
        import events as _ev
        if _ev is None:
            return {"locked": False}
        state = _ev.get_lock_state(path)
        if state:
            return {"locked": True, "state": {"holder": state.holder, "context": state.context}}
        return {"locked": False}
    except Exception as e:
        logger.warning(f"[WebEditor API] get_lock failed for {path}: {e}")
        return {"locked": False, "error": str(e)}


@router.post("/lock/{path:path}")
async def api_acquire_lock(path: str, req: LockRequest):
    """Acquire a write lock on a file."""
    try:
        import events as _ev
        if _ev is None:
            raise HTTPException(503, "Events system not available")
        # First, check if this holder already holds the lock (re-entrant / heartbeat).
        # If so, just refresh it — don't re-acquire through the generator.
        if _ev.refresh_lock(path, req.holder):
            rel = _to_rel(path)
            logger.info(f"[LOCK] Refreshed: holder={req.holder} path={rel}")
            await editor.broadcast_lock_update(rel)
            return {"ok": True, "lock": {"path": path, "holder": req.holder, "refreshed": True}}

        # New acquisition — use the context manager to hold the lock during
        # the broadcast, then let it close so the lock stays in _locks.
        gen = _ev.acquire_lock(path, req.holder, timeout=req.timeout,
                               context=req.context)
        lock_info = await gen.__aenter__()
        rel = _to_rel(path)
        logger.info(f"[LOCK] Acquired (held): holder={req.holder} path={rel}")
        await editor.broadcast_lock_update(rel)
        # Don't call __aexit__ — we intentionally keep the lock alive.
        # The generator will close here, but the lock stays in _locks.
        return {"ok": True, "lock": lock_info}
    except Exception as e:
        logger.warning(f"[WebEditor API] acquire_lock failed for {path}: {e}")
        raise HTTPException(409, str(e))


@router.delete("/lock/{path:path}")
async def api_release_lock(path: str, holder: str = Query(default="")):
    """Release the write lock on a file."""
    try:
        import events as _ev
        if _ev is None:
            return {"ok": True}
        await _ev.release_lock(path, holder)
        rel = _to_rel(path)
        logger.info(f"[LOCK] Released: holder={holder} path={rel}")
        await editor.broadcast_lock_update(rel)
        return {"ok": True}
    except FileNotFoundError:
        # Lock already gone — that's fine, treat as success
        return {"ok": True}
    except Exception as e:
        logger.warning(f"[WebEditor API] release_lock failed for {path}: {e}")
        return {"ok": False, "error": str(e)}


@router.patch("/lock/{path:path}")
async def api_refresh_lock(path: str, holder: str = Query(default="")):
    """Lightweight heartbeat to extend the lock expiry."""
    try:
        import events as _ev
        if _ev is None:
            return {"ok": True}
        rel = _to_rel(path)
        refreshed = _ev.refresh_lock(rel, holder)
        if refreshed:
            logger.debug(f"[LOCK] Refreshed: holder={holder} path={rel}")
            return {"ok": True, "refreshed": True}
        # Lock doesn't exist or is held by someone else
        logger.debug(f"[LOCK] Refresh failed: holder={holder} path={rel} not found")
        raise HTTPException(404, f"No active lock held by {holder} on {rel}")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[WebEditor API] refresh_lock failed for {path}: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/awareness/{path:path}")
async def api_update_awareness(path: str, req: AwarenessRequest):
    """Update awareness (cursor position, label) for a file being edited."""
    try:
        import events as _ev
        if _ev is not None:
            _ev.publish("awareness_updated", path=path, session_id=req.session_id,
                        cursor=req.cursor, label=req.label)
        if req.session_id:
            await editor.broadcast_to_all({
                "type": "awareness",
                "path": path,
                "session_id": req.session_id,
                "cursor": req.cursor,
                "label": req.label,
            })
    except Exception as e:
        logger.warning(f"[WebEditor API] awareness update failed for {path}: {e}")
    return {"ok": True}


# ─── Debug endpoints ──────────────────────────────────────────────────────────

@router.get("/tree")
async def api_tree():
    """Return the current file tree (debugging)."""
    return editor.get_file_tree(get_root_dir())
