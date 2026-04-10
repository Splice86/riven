"""Memory module for riven - calls memory API."""

import os
from typing import Optional

from modules import Module

MEMORY_API_URL = os.environ.get("MEMORY_API_URL", "http://127.0.0.1:8030")

# Database name - set from config, not overrideable via tools
DEFAULT_DB = os.environ.get("MEMORY_DB", "riven")


def get_module():
    """Get the memory module."""
    
    async def search_memories(query: str = "", limit: int = 50) -> str:
        """Search the memory database."""
        import requests
        resp = requests.get(
            f"{MEMORY_API_URL}/memories/search",
            params={"db_name": DEFAULT_DB},
            json={"query": query, "limit": limit}
        )
        data = resp.json()
        results = data.get("memories", [])
        if not results:
            return "No memories found."
        
        lines = [f"Found {len(results)} memories:"]
        for m in results[:10]:
            content = m.get("content", "")[:100]
            keywords = m.get("keywords", [])
            kw_str = f" [{', '.join(keywords)}]" if keywords else ""
            lines.append(f"  [{m.get('id')}]{kw_str}: {content}")
        
        return "\n".join(lines)
    
    async def add_memory(
        content: str,
        keywords: Optional[list[str]] = None,
        properties: Optional[dict[str, str]] = None
    ) -> str:
        """Add a new memory to the database."""
        import requests
        resp = requests.post(
            f"{MEMORY_API_URL}/memories",
            params={"db_name": DEFAULT_DB},
            json={"content": content, "keywords": keywords, "properties": properties}
        )
        result = resp.json()
        return f"Added memory #{result.get('id')}: {result.get('content', '')[:50]}..."
    
    async def get_memory(memory_id: int) -> str:
        """Get a specific memory by ID."""
        import requests
        resp = requests.get(
            f"{MEMORY_API_URL}/memories/{memory_id}",
            params={"db_name": DEFAULT_DB}
        )
        if resp.status_code == 404:
            return f"Memory #{memory_id} not found"
        m = resp.json()
        
        lines = [f"## Memory #{m['id']}"]
        lines.append(f"Created: {m.get('created_at')}")
        if m.get("keywords"):
            lines.append(f"Keywords: {', '.join(m['keywords'])}")
        lines.append(f"\n{m['content']}")
        return "\n".join(lines)
    
    async def list_memories(limit: int = 20) -> str:
        """List all memories."""
        import requests
        resp = requests.get(
            f"{MEMORY_API_URL}/memories",
            params={"db_name": DEFAULT_DB, "limit": limit}
        )
        data = resp.json()
        results = data.get("memories", [])
        if not results:
            return "No memories in database."
        
        lines = [f"Memories:"]
        for m in results:
            content = m.get("content", "")[:60]
            created = m.get("created_at", "")[:19]
            lines.append(f"  [{m.get('id')}] {created}: {content}")
        
        return "\n".join(lines)
    
    async def get_memory_stats() -> str:
        """Get memory database statistics."""
        import requests
        resp = requests.get(
            f"{MEMORY_API_URL}/stats",
            params={"db_name": DEFAULT_DB}
        )
        count = resp.json().get("count", 0)
        return f"Total memories: {count}"
    
    async def get_recent_context(hours: int = 24, limit: int = 5) -> str:
        """Get recent memories for context."""
        import requests
        resp = requests.post(
            f"{MEMORY_API_URL}/memories/search",
            params={"db_name": DEFAULT_DB},
            json={"query": f"d:last {hours} hours", "limit": limit}
        )
        results = resp.json().get("memories", [])
        if not results:
            return "No recent memories."
        
        lines = ["## Recent Memories"]
        for m in results:
            content = m.get("content", "")[:150]
            created = m.get("created_at", "")[:19]
            lines.append(f"- [{created}]: {content}")
        
        return "\n".join(lines)
    
    def get_context() -> str:
        """Get memory stats for system prompt."""
        import requests
        try:
            resp = requests.get(f"{MEMORY_API_URL}/stats", params={"db_name": DEFAULT_DB}, timeout=2)
            count = resp.json().get("count", 0)
            return f"Memory database: {count} memories"
        except Exception:
            return "Memory database: unavailable"
    
    return Module(
        name="memory",
        enrollment=lambda: None,
        functions={
            "search_memories": search_memories,
            "add_memory": add_memory,
            "get_memory": get_memory,
            "list_memories": list_memories,
            "get_memory_stats": get_memory_stats,
            "get_recent_context": get_recent_context,
        },
        get_context=get_context,
        tag="memory"
    )