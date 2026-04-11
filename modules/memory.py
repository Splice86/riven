"""Memory module for riven - calls memory API."""

import os
from typing import Optional

from modules import Module

# Load config - same as core.py
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
try:
    import yaml
    with open(CONFIG_PATH) as f:
        CONFIG = yaml.safe_load(f)
except Exception:
    CONFIG = {}

MEMORY_API_URL = os.environ.get("MEMORY_API_URL", CONFIG.get('memory_api', {}).get('url', "http://127.0.0.1:8030"))

# Database name - set from config, not overrideable via tools
DEFAULT_DB = os.environ.get("MEMORY_DB", CONFIG.get('memory_api', {}).get('db_name', "riven"))


def get_module():
    """Get the memory module."""
    
    async def search_memories(query: str = "", limit: int = 50) -> str:
        """Search the memory database using a query DSL.
        
        Search Syntax:
            k:<keyword>   - Exact keyword match (e.g., "k:python")
            s:<keyword>   - Semantic keyword similarity (e.g., "s:python")
            q:<text>      - Semantic text search (e.g., "q:machine learning")
            d:<date>      - Date filter (e.g., "d:last 7 days", "d:2025-01-01")
            p:<key=value> - Property filter (e.g., "p:role=user")
            
        Operators:
            AND - Both conditions must match
            OR  - Either condition must match
            NOT - Exclude keyword
            
        Examples:
            "k:python AND k:coding"           - Both keywords
            "k:python OR k:javascript"        - Either keyword
            "NOT k:deprecated"                - Exclude keyword
            "s:python@0.8"                    - Similar to python, threshold 0.8
            "q:machine learning"               - Semantic search
            "d:last 30 days AND k:important"   - Date range with keyword
            "(k:bug OR k:fix) AND NOT k:wontfix" - Complex query
            
        Date Formats:
            "today", "yesterday"
            "last N days", "last N hours"
            "YYYY-MM-DD to YYYY-MM-DD"
        """
        import requests
        resp = requests.post(
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
        """Add a new memory to the database with optional metadata.
        
        Args:
            content: The main text content of the memory
            keywords: Optional list of keywords for keyword searches (e.g., ["python", "coding"])
            properties: Optional dict of key-value properties (e.g., {"role": "user", "priority": "high"})
            
        Returns:
            Confirmation message with memory ID and content preview
        """
        import requests
        resp = requests.post(
            f"{MEMORY_API_URL}/memories",
            params={"db_name": DEFAULT_DB},
            json={"content": content, "keywords": keywords, "properties": properties}
        )
        result = resp.json()
        return f"Added memory #{result.get('id')}: {result.get('content', '')[:50]}..."
    
    async def get_memory(memory_id: int) -> str:
        """Get a specific memory by its ID.
        
        Use list_memories to find IDs, or search_memories to find relevant memories first.
        
        Args:
            memory_id: The numeric ID of the memory to retrieve
            
        Returns:
            Full memory details including content, creation time, and keywords
        """
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
        }
    )