"""Per-module SQLite storage for workflow state.

Self-contained: owns its own DB file at ~/.riven/riven_workflow.db.

Tables:
- workflow_states  (id, session_id, workflow_id, current_stage_index,
                    step_states, step_notes, dynamic_stages,
                    dynamic_steps, started_at, saved_at)
                    UNIQUE(session_id) — one active workflow per session.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from config import get

# 'riven' root logger — logs land in ~/.riven/logs/riven.log.
logger = logging.getLogger("riven.workflow.db")

# =============================================================================
# Database path & thread-local connections
# =============================================================================

_DB_PATH: str | None = None
_LOCAL = threading.local()


def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        base = os.path.expanduser(get("debug_dir", "~/.riven/logs"))
        db_dir = os.path.dirname(base)
        os.makedirs(db_dir, exist_ok=True)
        _DB_PATH = os.path.join(db_dir, "riven_workflow.db")
    return _DB_PATH


@contextmanager
def _conn() -> sqlite3.Connection:
    """Thread-local SQLite connection (auto-commits, auto-closes)."""
    db_path = _get_db_path()
    if not hasattr(_LOCAL, "conn") or _LOCAL.conn is None:
        _LOCAL.conn = sqlite3.connect(db_path, check_same_thread=False)
        _LOCAL.conn.row_factory = sqlite3.Row
        _init_db(_LOCAL.conn)
    try:
        yield _LOCAL.conn
        _LOCAL.conn.commit()
    except Exception:
        _LOCAL.conn.rollback()
        raise


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_states (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          TEXT    NOT NULL UNIQUE,
            workflow_id         TEXT    NOT NULL,
            current_stage_index INTEGER NOT NULL DEFAULT 0,
            step_states         TEXT,                             -- JSON dict
            step_notes          TEXT,                             -- JSON dict
            dynamic_stages      TEXT,                             -- JSON list
            dynamic_steps       TEXT,                             -- JSON dict keyed by stage
            started_at          TEXT    NOT NULL,
            saved_at            TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_workflow_session
            ON workflow_states(session_id);
        CREATE INDEX IF NOT EXISTS idx_workflow_saved
            ON workflow_states(saved_at);
    """)


# =============================================================================
# Internal helpers
# =============================================================================

def _row(r: sqlite3.Row) -> dict:
    result = {
        "id": r["id"],
        "session_id": r["session_id"],
        "workflow_id": r["workflow_id"],
        "current_stage_index": r["current_stage_index"],
        "step_states": _maybe_json(r["step_states"]),
        "step_notes": _maybe_json(r["step_notes"]),
        "dynamic_stages": _maybe_json(r["dynamic_stages"]),
        "dynamic_steps": _maybe_json(r["dynamic_steps"]),
        "started_at": r["started_at"],
        "saved_at": r["saved_at"],
    }
    return result


def _maybe_json(val: str | None) -> dict | list | None:
    if val is None:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None


# =============================================================================
# CRUD
# =============================================================================

def upsert(
    session_id: str,
    workflow_id: str,
    current_stage_index: int,
    step_states: dict | None,
    step_notes: dict | None,
    dynamic_stages: list | None,
    dynamic_steps: dict | None,
    started_at: str,
    saved_at: str,
) -> None:
    """Upsert a workflow state for a session (insert or replace)."""
    try:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO workflow_states
                    (session_id, workflow_id, current_stage_index,
                     step_states, step_notes, dynamic_stages,
                     dynamic_steps, started_at, saved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    workflow_id         = excluded.workflow_id,
                    current_stage_index = excluded.current_stage_index,
                    step_states         = excluded.step_states,
                    step_notes          = excluded.step_notes,
                    dynamic_stages      = excluded.dynamic_stages,
                    dynamic_steps       = excluded.dynamic_steps,
                    saved_at            = excluded.saved_at
                """,
                (
                    session_id,
                    workflow_id,
                    current_stage_index,
                    _d(step_states),
                    _d(step_notes),
                    _d(dynamic_stages),
                    _d(dynamic_steps),
                    started_at,
                    saved_at,
                ),
            )
    except sqlite3.Error as e:
        logger.error("[WF-DB] upsert failed for session=%s: %s", session_id, e, exc_info=True)
        raise


def load(session_id: str) -> Optional[dict]:
    """Load the active workflow state for a session, or None."""
    MAX_AGE_HOURS = 24
    try:
        with _conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM workflow_states
                WHERE session_id = ?
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None

        r = _row(row)
        # Check age
        saved_at = r["saved_at"]
        if saved_at:
            try:
                saved_time = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - saved_time).total_seconds() / 3600
                if age_hours > MAX_AGE_HOURS:
                    delete(session_id)
                    return None
            except Exception:
                pass
        return r
    except sqlite3.Error as e:
        logger.error("[WF-DB] load failed for session=%s: %s", session_id, e, exc_info=True)
        return None


def delete(session_id: str) -> None:
    """Remove the workflow state for a session."""
    try:
        with _conn() as conn:
            conn.execute(
                "DELETE FROM workflow_states WHERE session_id = ?",
                (session_id,),
            )
    except sqlite3.Error as e:
        logger.error("[WF-DB] delete failed for session=%s: %s", session_id, e, exc_info=True)


def list_all() -> list[dict]:
    """Return all workflow states across all sessions."""
    try:
        with _conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_states
                ORDER BY saved_at DESC
                """,
            ).fetchall()
        return [_row(r) for r in rows]
    except sqlite3.Error as e:
        logger.error("[WF-DB] list_all failed: %s", e, exc_info=True)
        return []


def count() -> int:
    """Count active workflow states."""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM workflow_states",
            ).fetchone()
        return row["n"] if row else 0
    except sqlite3.Error:
        return 0


def get_session_for_workflow_id(workflow_id: str) -> Optional[str]:
    """Return the session_id that has a given workflow active, if any."""
    try:
        with _conn() as conn:
            row = conn.execute(
                """
                SELECT session_id FROM workflow_states
                WHERE workflow_id = ?
                LIMIT 1
                """,
                (workflow_id,),
            ).fetchone()
        return row["session_id"] if row else None
    except sqlite3.Error:
        return None


# =============================================================================
# Serialisation helpers
# =============================================================================

def _d(val: dict | list | None) -> str | None:
    return json.dumps(val) if val is not None else None
