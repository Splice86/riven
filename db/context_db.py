"""Context database — session-scoped conversation storage via SQLite.

Schema:
    messages(id, session_id, role, content, token_count,
             tool_call_id, function, created_at)

Owns its own DB file at ~/.riven/core.db. Thread-safe via thread-local connections.
No summarization, no tags — just a clean message log with token counts.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

# 'riven' root logger is configured by riven_core.logging_config (api.py / core.py).
# Use it directly so logs land in ~/.riven/logs/riven.log.
logger = logging.getLogger("riven.db")

# =============================================================================
# DB path & thread-local connections
# =============================================================================

_DB_PATH: str | None = None
_LOCAL = threading.local()


def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        riven_dir = os.path.expanduser("~/.riven")
        os.makedirs(riven_dir, exist_ok=True)
        _DB_PATH = os.path.join(riven_dir, "core.db")
    return _DB_PATH


@contextmanager
def _conn() -> sqlite3.Connection:
    """Thread-local SQLite connection — auto-commits, auto-closes."""
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
        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT    NOT NULL,
            role         TEXT    NOT NULL,
            content      TEXT    NOT NULL,
            token_count  INTEGER NOT NULL DEFAULT 0,
            tool_call_id TEXT,
            function     TEXT,
            created_at   TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, created_at);
    """)


# =============================================================================
# Token counting
# =============================================================================

def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken if available, else rough estimate."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # ~4 chars per token for typical code/text
        return max(1, len(text) // 4)


# =============================================================================
# Module-level helpers (convenience wrappers around ContextDB)
# =============================================================================

def add(
    role: str,
    content: str,
    session: str,
    tool_call_id: Optional[str] = None,
    function: Optional[str] = None,
) -> int:
    """Add a message to a session. Returns the new row ID."""
    return ContextDB().add(role, content, session, tool_call_id, function)


def get_history(session: str, limit: int = 200) -> list[dict]:
    """Fetch all messages for a session ordered by created_at.
    
    Note: prefer get_history_by_tokens() for LLM context to enforce the
    message.token_limit budget.
    """
    return ContextDB().get_history(session, limit=limit)


def _get_message_token_limit() -> int:
    """Read message.token_limit from config (0 = no limit)."""
    try:
        from config import get
        raw = get("message.token_limit", 0)
        return int(raw) if raw else 0
    except Exception:
        return 0


def get_history_by_tokens(session: str, limit: int = 200) -> tuple[list[dict], int, int, bool]:
    """Fetch messages oldest→newest, trimming from the start until total tokens
    fit within the message.token_limit budget.
    
    Args:
        session: session ID
        limit: hard cap on row count (safety valve, defaults to 200)
    
    Returns:
        (messages, total_tokens, total_messages, was_trimmed)
        - messages: trimmed message list oldest→newest
        - total_tokens: sum of token_count for the returned messages
        - total_messages: total messages in DB before trimming
        - was_trimmed: True if any messages were dropped
    """
    db_limit = _get_message_token_limit()
    if db_limit <= 0:
        # No limit — behave like the old get_history
        msgs = ContextDB().get_history(session, limit=limit)
        total = sum(m.get("token_count", 0) for m in msgs)
        return msgs, total, len(msgs), False
    
    # Fetch oldest-first (ASC) so we can drop from the front
    all_msgs = ContextDB().get_history(session, limit=limit)
    total_messages = len(all_msgs)
    
    if not all_msgs:
        return [], 0, 0, False
    
    # Walk from newest to oldest, accumulating tokens until we hit the limit.
    # Keep messages from that point onward.
    running_tokens = 0
    kept_start = len(all_msgs)  # index of first kept message (0 = keep all)
    
    for i in range(len(all_msgs) - 1, -1, -1):
        tokens = all_msgs[i].get("token_count", 0)
        if running_tokens + tokens <= db_limit:
            running_tokens += tokens
        else:
            kept_start = i + 1
            break
    
    kept = all_msgs[kept_start:]
    was_trimmed = kept_start > 0
    return kept, running_tokens, total_messages, was_trimmed


def delete_session(session: str) -> int:
    """Delete all messages for a session. Returns rows deleted."""
    return ContextDB().delete_session(session)


# =============================================================================
# ContextDB — main interface
# =============================================================================

class ContextDB:
    """Owns the context DB connection. Thread-safe, lazy-init.

    All storage goes through an instance so the DB path can be overridden
    for testing (via constructor arg).
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path
        self._local = threading.local()

    def _open(self) -> sqlite3.Connection:
        """Open a connection for this thread (lazy, one per thread)."""
        path = self._db_path or _get_db_path()
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            _init_db(self._local.conn)
        return self._local.conn

    @contextmanager
    def _conn(self):
        """Context manager for transactional access."""
        conn = self._open()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    def add(
        self,
        role: str,
        content: str,
        session: str,
        tool_call_id: Optional[str] = None,
        function: Optional[str] = None,
    ) -> int:
        """Insert a message. Returns the new row ID."""
        token_count = _count_tokens(content)
        created_at = datetime.now(timezone.utc).isoformat()
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO messages
                        (session_id, role, content, token_count,
                         tool_call_id, function, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (session, role, content, token_count,
                     tool_call_id, function, created_at),
                )
                return cur.lastrowid or 0
        except sqlite3.Error as e:
            logger.error("[DB] Failed to INSERT for session=%s role=%s: %s", session, role, e, exc_info=True)
            raise

    def get_history(self, session: str, limit: int = 200) -> list[dict]:
        """Fetch all messages for a session ordered by created_at ASC."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT id, session_id, role, content, token_count,
                           tool_call_id, function, created_at
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (session, limit),
                ).fetchall()
            return [_row(r) for r in rows]
        except sqlite3.Error as e:
            logger.error("[DB] Failed to SELECT for session=%s: %s", session, e, exc_info=True)
            raise

    def delete_session(self, session: str) -> int:
        """Delete all messages for a session. Returns row count."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM messages WHERE session_id = ?",
                (session,),
            )
            return cur.rowcount

    # -------------------------------------------------------------------------
    # Stats (useful for debugging / UI)
    # -------------------------------------------------------------------------

    def session_stats(self, session: str) -> dict:
        """Return token count and message count for a session."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as count, COALESCE(SUM(token_count), 0) as tokens
                FROM messages WHERE session_id = ?
                """,
                (session,),
            ).fetchone()
        return {"count": row["count"], "tokens": row["tokens"]}


# =============================================================================
# Helpers
# =============================================================================

def _row(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to a plain dict."""
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "token_count": row["token_count"],
        "tool_call_id": row["tool_call_id"],
        "function": row["function"],
        "created_at": row["created_at"],
    }
