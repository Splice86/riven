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

from riven_secrets import get_memory_api
MEMORY_API_URL = os.environ.get("MEMORY_API_URL", get_memory_api())

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
    
    async def add_link(source_id: int, target_id: int, link_type: str = "related_to") -> str:
        """Create a link between two memories.
        
        Args:
            source_id: ID of the source memory (the one doing the linking)
            target_id: ID of the target memory (the one being linked to)
            link_type: Type of link (e.g., "related_to", "summary_of", "follows")
            
        Returns:
            Confirmation message with link details
        """
        import requests
        resp = requests.post(
            f"{MEMORY_API_URL}/memories/link",
            params={"db_name": DEFAULT_DB},
            json={"source_id": source_id, "target_id": target_id, "link_type": link_type}
        )
        result = resp.json()
        return f"Linked memory #{source_id} -> #{target_id} ({link_type})"
    
    async def delete_memory(memory_id: int) -> str:
        """Delete a memory by its ID.
        
        Args:
            memory_id: The numeric ID of the memory to delete
            
        Returns:
            Confirmation message
        """
        import requests
        resp = requests.delete(
            f"{MEMORY_API_URL}/memories/{memory_id}",
            params={"db_name": DEFAULT_DB}
        )
        if resp.status_code == 404:
            return f"Memory #{memory_id} not found"
        return f"Deleted memory #{memory_id}"
    
    async def update_memory(
        memory_id: int,
        properties: Optional[dict[str, str]] = None,
        keywords: Optional[list[str]] = None
    ) -> str:
        """Update a memory's properties and/or keywords.
        
        Args:
            memory_id: The numeric ID of the memory to update
            properties: Optional dict of key-value properties to update
            keywords: Optional list of keywords to replace existing keywords
            
        Returns:
            Confirmation message with updated memory info
        """
        import requests
        resp = requests.put(
            f"{MEMORY_API_URL}/memories/{memory_id}",
            params={"db_name": DEFAULT_DB},
            json={"properties": properties, "keywords": keywords}
        )
        if resp.status_code == 404:
            return f"Memory #{memory_id} not found"
        result = resp.json()
        return f"Updated memory #{memory_id}"
    
    async def execute_sql(sql: str, params: Optional[list] = None) -> str:
        """Execute raw SQL against the memory database.
        
        WARNING: This is powerful and potentially dangerous. Use only for debugging
        or direct database inspection.
        
        Args:
            sql: SQL statement to execute (SELECT, INSERT, UPDATE, DELETE, etc.)
            params: Optional list of parameters for the SQL query
            
        Returns:
            Query results or row count
        """
        import requests
        resp = requests.post(
            f"{MEMORY_API_URL}/db/execute",
            params={"db_name": DEFAULT_DB},
            json={"sql": sql, "params": params}
        )
        if resp.status_code != 200:
            return f"SQL Error: {resp.json().get('detail', resp.text)}"
        
        result = resp.json()
        if result.get("type") == "select":
            rows = result.get("rows", [])
            if not rows:
                return "No results found."
            # Format results
            lines = [f"{result.get('count')} rows:"]
            for row in rows[:10]:
                lines.append(str(row))
            if len(rows) > 10:
                lines.append(f"... and {len(rows) - 10} more rows")
            return "\n".join(lines)
        else:
            return f"Executed. {result.get('rows_affected')} rows affected."
    
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
            "add_link": add_link,
            "delete_memory": delete_memory,
            "update_memory": update_memory,
            "execute_sql": execute_sql,
            "get_recent_context": get_recent_context,
        }
    )