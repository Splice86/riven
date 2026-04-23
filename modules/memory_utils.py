"""Shared memory API utilities for modules.

Provides common helper functions for interacting with the memory API:
- _search_memories: Search memory DB with session + query
- _delete_memory: Delete a memory by ID
- _get_memory_url: Lazy getter for memory API base URL

All modules that need to store/retrieve from memory should import from here
instead of duplicating these helpers.
"""

import logging
import requests
from config import get

logger = logging.getLogger(__name__)


def _get_memory_url() -> str:
    """Lazy getter for memory API URL — defers config.get() to call time."""
    return get('memory_api.url')


def _search_memories(
    session_id: str,
    query: str,
    limit: int = 50,
    keyword_prefix: str = "",
) -> list[dict]:
    """Search memory DB and return results.

    Args:
        session_id: Current session ID (auto-scoped with k:<session_id>)
        query: Search query (combined with session scope and keyword_prefix)
        limit: Maximum number of results to return
        keyword_prefix: Optional extra keywords to insert after session scope,
                        e.g. "k:planning AND " to scope results to the planning namespace

    Returns:
        List of memory dicts from the API
    """
    prefix = f"{keyword_prefix}" if keyword_prefix else ""
    search_query = f"k:{session_id}{prefix} AND {query}"

    try:
        url = f"{_get_memory_url()}/memories/search"
        resp = requests.post(
            url,
            json={"query": search_query, "limit": limit},
            timeout=5
        )

        if resp.status_code == 200:
            data = resp.json()
            return data.get("memories", [])
    except Exception as e:
        logger.warning(f"Memory search failed: {e}")
    return []


def _delete_memory(memory_id: str) -> bool:
    """Delete a memory by ID.

    Args:
        memory_id: ID of the memory to delete
        
    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        response = requests.delete(
            f"{_get_memory_url()}/memories/{memory_id}",
            timeout=5
        )
        return response.status_code in (200, 204)
    except Exception as e:
        logger.warning(f"Memory delete failed for {memory_id}: {e}")
        return False


def _get_memory(session_id: str, memory_type: str) -> dict | None:
    """Get a single memory by type for the current session.

    Args:
        session_id: Current session ID
        memory_type: Type identifier (e.g. "cwd")

    Returns:
        Memory dict or None if not found
    """
    query = f"k:{memory_type}"
    memories = _search_memories(session_id, query, limit=1)
    return memories[0] if memories else None


def _set_memory(
    session_id: str,
    memory_type: str,
    content: str,
    properties: dict,
) -> bool:
    """Store a single memory, overwriting any existing one of the same type.

    Args:
        session_id: Current session ID
        memory_type: Type identifier (e.g. "cwd")
        content: Display content for the memory
        properties: Additional properties to store

    Returns:
        True if successful, False otherwise
    """
    # Delete existing first to avoid duplicates
    existing = _get_memory(session_id, memory_type)
    if existing:
        _delete_memory(existing['id'])

    keywords = [session_id, memory_type]
    payload = {
        "content": content,
        "keywords": keywords,
        "properties": properties,
    }

    try:
        url = f"{_get_memory_url()}/memories"
        resp = requests.post(url, json=payload, timeout=5)
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Memory set failed for {memory_type}: {e}")
        return False
