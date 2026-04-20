"""Shared memory API utilities for modules.

Provides common helper functions for interacting with the memory API:
- _search_memories: Search memory DB with session + query
- _delete_memory: Delete a memory by ID

All modules that need to store/retrieve from memory should import from here
instead of duplicating these helpers.
"""

import requests
from config import get


MEMORY_API_URL = get('memory_api.url')


def _search_memories(session_id: str, query: str, limit: int = 50) -> list[dict]:
    """Search memory DB and return results.

    Args:
        session_id: Current session ID (auto-scoped with k:<session_id>)
        query: Search query (will be combined with session scope)
        limit: Maximum number of results to return

    Returns:
        List of memory dicts from the API
    """
    search_query = f"k:{session_id} AND {query}"

    try:
        url = f"{MEMORY_API_URL}/memories/search"
        resp = requests.post(
            url,
            json={"query": search_query, "limit": limit},
            timeout=5
        )

        if resp.status_code == 200:
            data = resp.json()
            return data.get("memories", [])
    except Exception:
        pass
    return []


def _delete_memory(memory_id: str) -> None:
    """Delete a memory by ID.

    Args:
        memory_id: ID of the memory to delete
    """
    try:
        requests.delete(
            f"{MEMORY_API_URL}/memories/{memory_id}",
            timeout=5
        )
    except Exception:
        pass
