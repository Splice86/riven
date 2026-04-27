"""Memory tracking helpers for file operations.

Provides functions for tracking file changes and open files
in the MemoryDB session store.
"""

from __future__ import annotations

import json
import os

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.memory_utils import _set_memory as SetMemoryFunc, _search_memories as SearchMemoriesFunc
else:
    # These will be imported at runtime to avoid circular imports
    SetMemoryFunc = None
    SearchMemoriesFunc = None

try:
    from .constants import MEMORY_KEYWORD_PREFIX, make_open_file_keyword, build_search_query, PROP_SCREEN_UIDS, PROP_PATH, PROP_FILENAME
except ImportError:
    # Running as standalone module
    from constants import MEMORY_KEYWORD_PREFIX, make_open_file_keyword, build_search_query



def _get_search_memories():
    """Lazy import to avoid circular dependencies.
    
    Import from modules.memory_utils to ensure tests can mock it.
    Tests patch modules.memory_utils._search_memories.
    """
    from modules.memory_utils import _search_memories
    return _search_memories


def _get_delete_memory():
    """Lazy import to avoid circular dependencies."""
    from modules.memory_utils import _delete_memory
    return _delete_memory


def _get_set_memory():
    """Lazy import to avoid circular dependencies."""
    from modules.memory_utils import _set_memory
    return _set_memory


def hash_content(content: str) -> str:
    """Generate a short hash of content for change tracking.
    
    Args:
        content: The content to hash
        
    Returns:
        8-character MD5 hash
    """
    return hashlib.md5(content.encode('utf-8')).hexdigest()[:8]


def track_file_change(
    session_id: str,
    path: str,
    change_type: str,
    diff: str,
    success: bool = True
) -> bool:
    """Record a file change in memory.
    
    Args:
        session_id: Current session ID
        path: Path to the modified file
        change_type: Type of change (replace_text, batch_edit, delete_snippet, etc.)
        diff: The diff content
        success: Whether the change succeeded
        
    Returns:
        True if recorded successfully, False otherwise
    """
    import json
    from pathlib import Path

    try:
        filename = Path(path).name

        # Read current content for hash if file exists
        previous_hash = "*"
        new_hash = "*"
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            new_hash = hash_content(content)
        else:
            # File was deleted, use placeholder
            new_hash = "DELETED"
        
        memory_type = f"file_change:{filename}"
        content_str = f"changed: {filename} ({change_type})"
        properties = {
            "path": path,
            "change_type": change_type,
            "previous_hash": previous_hash,
            "new_hash": new_hash,
            "success": "true" if success else "false"
        }
        
        _get_set_memory()(session_id, memory_type, content_str, properties)
        return True
    except Exception:
        # Non-blocking - don't fail the operation if memory tracking fails
        return False


def get_open_files(session_id: str) -> list[dict]:
    """Get all currently open files for a session.
    
    Args:
        session_id: Current session ID
        
    Returns:
        List of memory entries for open files
    
    Search query: k:open_file: (prefix match for all open files)
    The _search_memories builds: k:{session_id} AND k:open_file:
    """
    query = build_search_query()  # This now returns k:open_file:
    return _get_search_memories()(session_id, query, limit=100)


def get_file_history(session_id: str, path: str | None = None) -> list[dict]:
    """Get file change history for a session.
    
    Args:
        session_id: Current session ID
        path: Optional path to filter by
        
    Returns:
        List of memory entries for file changes
    """
    # Note: wildcard in AND queries doesn't work reliably, so search by session
    # and filter by file_change:* pattern
    memories = _get_search_memories()(session_id, "", limit=50)
    
    if path:
        filename = path.split("/")[-1] if "/" in path else path
        # Filter for file_change:filename patterns
        memories = [m for m in memories if any(kw.startswith(f"file_change:{filename}") for kw in m.get('keywords', []))]
    else:
        # Filter for all file_change:* patterns
        memories = [m for m in memories if any(kw.startswith("file_change:") for kw in m.get('keywords', []))]
    
    return memories


def _get_screen_binding_memories(session_id: str, path: str) -> list[dict]:
    """Find all open_file memory entries for a path and extract their screen UIDs.

    Args:
        session_id: Current session ID
        path: Absolute file path

    Returns:
        List of memory entries for this path
    """
    query = f"p:{PROP_PATH}={path}"
    return _get_search_memories()(session_id, query, limit=100)


def track_screen_bound(session_id: str, path: str, screen_uid: str) -> bool:
    """Record that a screen is watching a file.

    Adds screen_uid to the screen_uids property on the open_file memory entry.
    Creates the entry if it doesn't exist.

    Args:
        session_id: Current session ID
        path: Absolute file path
        screen_uid: Screen browser tab UID

    Returns:
        True if recorded successfully
    """
    import json
    from pathlib import Path

    try:
        filename = Path(path).name
        keyword = make_open_file_keyword(filename)
        # Search for existing entry for this file
        existing_memories = _get_search_memories()(session_id, keyword, limit=10)

        # Find entry with matching path (there may be multiple for same filename)
        existing = None
        for mem in existing_memories:
            props = mem.get("properties", {})
            if props.get("path") == path:
                existing = mem
                break

        # Build current screen_uids list
        if existing:
            props = existing.get("properties", {})
            raw_uids = props.get(PROP_SCREEN_UIDS, "[]")
            try:
                uids = json.loads(raw_uids) if isinstance(raw_uids, str) else list(raw_uids)
            except Exception:
                uids = []
        else:
            uids = []

        # Add screen_uid if not already present
        if screen_uid not in uids:
            uids.append(screen_uid)

        # Build updated properties
        if existing:
            updated_props = dict(existing.get("properties", {}))
        else:
            updated_props = {
                PROP_FILENAME: filename,
                PROP_PATH: os.path.abspath(path),
            }
        updated_props[PROP_SCREEN_UIDS] = json.dumps(uids)

        content = f"open: {filename}"
        _get_set_memory()(session_id, keyword, content, updated_props)
        return True
    except Exception as e:
        import logging
        logging.getLogger("modules.file.memory").warning(f"track_screen_bound failed: {e}")
        return False


def track_screen_unbound(session_id: str, path: str, screen_uid: str) -> bool:
    """Remove a screen from the bound list for a file.

    Args:
        session_id: Current session ID
        path: Absolute file path
        screen_uid: Screen browser tab UID to remove

    Returns:
        True if updated successfully
    """
    import json
    from pathlib import Path

    try:
        filename = Path(path).name
        keyword = make_open_file_keyword(filename)
        existing_memories = _get_search_memories()(session_id, keyword, limit=10)

        existing = None
        for mem in existing_memories:
            props = mem.get("properties", {})
            if props.get("path") == path:
                existing = mem
                break

        if not existing:
            return False

        props = existing.get("properties", {})
        raw_uids = props.get(PROP_SCREEN_UIDS, "[]")
        try:
            uids = json.loads(raw_uids) if isinstance(raw_uids, str) else list(raw_uids)
        except Exception:
            uids = []

        if screen_uid not in uids:
            return False  # Not bound

        uids.remove(screen_uid)
        updated_props = dict(props)
        updated_props[PROP_SCREEN_UIDS] = json.dumps(uids)

        content = f"open: {filename}"
        _get_set_memory()(session_id, keyword, content, updated_props)
        return True
    except Exception as e:
        import logging
        logging.getLogger("modules.file.memory").warning(f"track_screen_unbound failed: {e}")
        return False


def get_screen_uids_for_path(session_id: str, path: str) -> list[str]:
    """Get all screen UIDs bound to a file path.

    Args:
        session_id: Current session ID
        path: Absolute file path

    Returns:
        List of screen UIDs (may be empty)
    """
    try:
        memories = _get_screen_binding_memories(session_id, path)
        uids = []
        for mem in memories:
            props = mem.get("properties", {})
            raw = props.get(PROP_SCREEN_UIDS, "[]")
            try:
                uids.extend(json.loads(raw) if isinstance(raw, str) else list(raw))
            except Exception:
                pass
        return uids
    except Exception:
        return []


def format_file_history(memories: list[dict]) -> str:
    """Format file history memories into human-readable string.
    
    Args:
        memories: List of memory entries
        
    Returns:
        Formatted string with change history
    """
    if not memories:
        return "No file changes recorded in this session."
    
    lines = ["📝 File Change History:", ""]
    
    for mem in memories:
        props = mem.get("properties", {})
        path = props.get("path", "unknown")
        change_type = props.get("change_type", "unknown")
        success = props.get("success", "true") == "true"
        prev_hash = props.get("previous_hash", "*")
        new_hash = props.get("new_hash", "*")
        
        # Get filename from path
        filename = path.split("/")[-1] if "/" in path else path
        
        status = "✅" if success else "❌"
        lines.append(f"  {status} {filename} ({change_type})")
        lines.append(f"      {prev_hash} → {new_hash}")
    
    lines.append("")
    lines.append(f"Total: {len(memories)} change(s)")
    
    return "\n".join(lines)
