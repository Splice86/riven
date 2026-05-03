"""Memory tracking helpers for file operations.

Provides functions for tracking file changes and open files
in the local SQLite store (modules.file.db).
"""

from __future__ import annotations

import hashlib
import os

from .db import add_file_change, get_file_changes, get_open_files


def hash_content(content: str) -> str:
    """Generate a short hash of content for change tracking."""
    return hashlib.md5(content.encode('utf-8')).hexdigest()[:8]


def _count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken if available, else rough estimate."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except (ImportError, Exception):
        # Rough fallback: ~4 chars per token for typical code/text
        return len(text) // 4


def track_file_change(
    session_id: str,
    path: str,
    change_type: str,
    diff: str = "",
    success: bool = True,
) -> bool:
    """Record a file change in the DB.

    Args:
        session_id: Current session ID
        path: Path to the modified file
        change_type: Type of change (replace_text, batch_edit, delete_snippet, etc.)
        diff: The diff content
        success: Whether the change succeeded
    """
    try:
        return add_file_change(session_id, path, change_type, diff, success)
    except Exception:
        return False


def get_file_history(session_id: str, path: str | None = None) -> list[dict]:
    """Get file change history for a session.

    Args:
        session_id: Current session ID
        path: Optional path to filter by

    Returns:
        List of file change records
    """
    return get_file_changes(session_id, path=path, limit=50)


def format_file_history(memories: list[dict]) -> str:
    """Format file change records into human-readable string."""
    if not memories:
        return "No file changes recorded in this session."

    lines = ["📝 File Change History:", ""]

    for mem in memories:
        path = mem.get("path", "unknown")
        change_type = mem.get("change_type", "unknown")
        success = mem.get("success", True)
        diff = mem.get("diff", "")
        filename = path.split("/")[-1] if "/" in path else path

        status = "✅" if success else "❌"
        lines.append(f"  {status} {filename} ({change_type})")
        if diff:
            diff_preview = diff[:100].replace("\n", " ")
            lines.append(f"      {diff_preview}")

    lines.append("")
    lines.append(f"Total: {len(memories)} change(s)")

    return "\n".join(lines)
