"""Per-module SQLite storage for file tracking.

Self-contained: owns its own DB file, no imports from lower-level code.

Tables:
- open_files    (id, session_id, keyword, path, content, line_start, line_end, created_at)
                UNIQUE(session_id, keyword) — one entry per file per session
- file_changes  (id, session_id, path, change_type, diff, success, created_at)
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from config import get

# =============================================================================
# Database path & thread-local connections
# =============================================================================

_DB_PATH = None
_LOCAL = threading.local()


def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        base = os.path.expanduser(get("debug_dir", "~/.riven/logs"))
        db_dir = os.path.dirname(base)
        os.makedirs(db_dir, exist_ok=True)
        db_name = get("file_module.db_name", "riven_file") + ".db"
        _DB_PATH = os.path.join(db_dir, db_name)
    return _DB_PATH


@contextmanager
def _conn():
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
        CREATE TABLE IF NOT EXISTS open_files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT    NOT NULL,
            keyword     TEXT    NOT NULL,
            path        TEXT    NOT NULL,
            content     TEXT,
            line_start  INTEGER,
            line_end    INTEGER,
            created_at  TEXT    NOT NULL,
            UNIQUE(session_id, keyword)
        );
        CREATE INDEX IF NOT EXISTS idx_open_files_session
            ON open_files(session_id);

        CREATE TABLE IF NOT EXISTS file_changes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT    NOT NULL,
            path         TEXT,
            change_type  TEXT,
            diff         TEXT,
            success      INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_changes_session
            ON file_changes(session_id);
    """)


# =============================================================================
# Open files
# =============================================================================

def set_open_file(
    session_id: str,
    keyword: str,
    path: str,
    content: str = "",
    line_start: int | None = None,
    line_end: int | None = None,
) -> bool:
    """Upsert an open file entry for a session.

    keyword is typically "open_file:{filename}" for uniqueness.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO open_files
                    (session_id, keyword, path, line_start, line_end, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, keyword)
                DO UPDATE SET path         = excluded.path,
                              line_start   = excluded.line_start,
                              line_end     = excluded.line_end,
                              content      = excluded.content,
                              created_at   = excluded.created_at
                """,
                (session_id, keyword, path, line_start, line_end, content, now),
            )
        return True
    except Exception:
        return False


def get_open_files(
    session_id: str,
    keyword: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Get open files for a session.

    Args:
        session_id: Session ID to filter by
        keyword: If provided, prefix-match on keyword (e.g. "open_file:")
                 If None, returns all open files for session
        limit: Max rows to return
    """
    try:
        with _conn() as conn:
            if keyword is None:
                rows = conn.execute(
                    """
                    SELECT * FROM open_files
                    WHERE session_id=?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM open_files
                    WHERE session_id=? AND keyword LIKE ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (session_id, keyword + "%", limit),
                ).fetchall()

            return [_row(r) for r in rows]
    except Exception:
        return []


def delete_open_file(session_id: str, keyword: str) -> bool:
    """Remove an open file entry by session + keyword."""
    try:
        with _conn() as conn:
            conn.execute(
                "DELETE FROM open_files WHERE session_id=? AND keyword=?",
                (session_id, keyword),
            )
        return True
    except Exception:
        return False


def delete_open_file_by_path(session_id: str, path: str) -> bool:
    """Remove all open file entries matching session + path."""
    try:
        with _conn() as conn:
            conn.execute(
                "DELETE FROM open_files WHERE session_id=? AND path=?",
                (session_id, path),
            )
        return True
    except Exception:
        return False


def delete_all_open_files(session_id: str) -> int:
    """Remove all open file entries for a session. Returns row count."""
    try:
        with _conn() as conn:
            cur = conn.execute(
                "DELETE FROM open_files WHERE session_id=?",
                (session_id,),
            )
        return cur.rowcount
    except Exception:
        return 0


def get_open_file_by_keyword(session_id: str, keyword: str) -> dict | None:
    """Get a single open file entry by its keyword."""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM open_files WHERE session_id=? AND keyword=? LIMIT 1",
                (session_id, keyword),
            ).fetchone()
        return _row(row) if row else None
    except Exception:
        return None


# =============================================================================
# File changes
# =============================================================================

def add_file_change(
    session_id: str,
    path: str,
    change_type: str,
    diff: str = "",
    success: bool = True,
) -> bool:
    """Record a file change (replace_text, batch_edit, etc.)."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO file_changes
                    (session_id, path, change_type, diff, success, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, path, change_type, diff, int(success), now),
            )
        return True
    except Exception:
        return False


def get_file_changes(
    session_id: str,
    path: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Get file changes for a session, optionally filtered by path."""
    try:
        with _conn() as conn:
            if path is None:
                rows = conn.execute(
                    """
                    SELECT * FROM file_changes
                    WHERE session_id=?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM file_changes
                    WHERE session_id=? AND path=?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (session_id, path, limit),
                ).fetchall()

            return [_row(r) for r in rows]
    except Exception:
        return []


# =============================================================================
# Helpers
# =============================================================================

def _row(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict.

    sqlite3.Row is indexable (like a tuple) and also supports column-name
    access (like a dict) but does NOT have a .get() method, so we use
    row["col"] for all accesses.
    """
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "keyword": row["keyword"] if "keyword" in row.keys() else None,
        "path": row["path"],
        "content": row["content"] if "content" in row.keys() else None,
        "line_start": row["line_start"] if "line_start" in row.keys() else None,
        "line_end": row["line_end"] if "line_end" in row.keys() else None,
        "change_type": row["change_type"] if "change_type" in row.keys() else None,
        "diff": row["diff"] if "diff" in row.keys() else None,
        "success": bool(row["success"]) if "success" in row.keys() else True,
        "created_at": row["created_at"],
    }
