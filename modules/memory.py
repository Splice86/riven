"""Memory module for temp_riven - queries remote memory API.

Provides long-term memory storage and retrieval:
- search_memories: Query with DSL (keywords, semantic, date filters)
- add_memory: Store with optional metadata
- get_memory: Fetch by ID
- list_memories: List recent memories
- add_link: Link two memories
- delete_memory: Delete by ID
- update_memory: Update metadata
- execute_sql: Raw SQL (dangerous debug tool)
"""

import requests
from typing import Optional

from modules import CalledFn, ContextFn, Module
from config import get


MEMORY_API_URL = get('memory_api.url', 'http://127.0.0.1:8030')


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
    """
    try:
        resp = requests.post(
            f"{MEMORY_API_URL}/memories/search",
            json={"query": query, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
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
        
        if len(results) > 10:
            lines.append(f"... and {len(results) - 10} more (increase limit to see more)")
        
        return "\n".join(lines)
    
    except requests.RequestException as e:
        return f"[ERROR] Memory search failed: {e}"


async def add_memory(
    content: str,
    keywords: Optional[list[str]] = None,
    properties: Optional[dict[str, str]] = None
) -> str:
    """Add a new memory to the database with optional metadata.
    
    Args:
        content: The main text content of the memory
        keywords: Optional list of keywords for keyword searches
        properties: Optional dict of key-value properties (e.g., {"role": "user"})
    """
    try:
        resp = requests.post(
            f"{MEMORY_API_URL}/memories",
            json={"content": content, "keywords": keywords or [], "properties": properties or {}},
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        
        mem_id = result.get('id', '?')
        content_preview = result.get('content', content)[:50]
        return f"Added memory #{mem_id}: {content_preview}..."
    
    except requests.RequestException as e:
        return f"[ERROR] Failed to add memory: {e}"


async def get_memory(memory_id: int) -> str:
    """Get a specific memory by its ID.
    
    Args:
        memory_id: The numeric ID of the memory to retrieve
    """
    try:
        resp = requests.get(
            f"{MEMORY_API_URL}/memories/{memory_id}",
            timeout=10,
        )
        
        if resp.status_code == 404:
            return f"Memory #{memory_id} not found"
        
        resp.raise_for_status()
        m = resp.json()
        
        lines = [f"## Memory #{m['id']}"]
        lines.append(f"Created: {m.get('created_at')}")
        
        if m.get("keywords"):
            lines.append(f"Keywords: {', '.join(m['keywords'])}")
        
        if m.get("properties"):
            lines.append(f"Properties: {m['properties']}")
        
        lines.append(f"\n{m['content']}")
        return "\n".join(lines)
    
    except requests.RequestException as e:
        return f"[ERROR] Failed to get memory: {e}"


async def list_memories(limit: int = 20) -> str:
    """List all memories, most recent first."""
    try:
        resp = requests.get(
            f"{MEMORY_API_URL}/memories",
            params={"limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
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
    
    except requests.RequestException as e:
        return f"[ERROR] Failed to list memories: {e}"


async def get_memory_stats() -> str:
    """Get memory database statistics."""
    try:
        resp = requests.get(
            f"{MEMORY_API_URL}/stats",
            timeout=10,
        )
        resp.raise_for_status()
        count = resp.json().get("count", 0)
        return f"Total memories: {count}"
    
    except requests.RequestException as e:
        return f"[ERROR] Failed to get stats: {e}"


async def add_link(source_id: int, target_id: int, link_type: str = "related_to") -> str:
    """Create a link between two memories.
    
    Args:
        source_id: ID of the source memory (doing the linking)
        target_id: ID of the target memory (being linked to)
        link_type: Type of link (e.g., "related_to", "summary_of", "follows")
    """
    try:
        resp = requests.post(
            f"{MEMORY_API_URL}/memories/link",
            json={"source_id": source_id, "target_id": target_id, "link_type": link_type},
            timeout=10,
        )
        resp.raise_for_status()
        return f"Linked memory #{source_id} -> #{target_id} ({link_type})"
    
    except requests.RequestException as e:
        return f"[ERROR] Failed to link memories: {e}"


async def delete_memory(memory_id: int) -> str:
    """Delete a memory by its ID.
    
    Args:
        memory_id: The numeric ID of the memory to delete
    """
    try:
        resp = requests.delete(
            f"{MEMORY_API_URL}/memories/{memory_id}",
            timeout=10,
        )
        
        if resp.status_code == 404:
            return f"Memory #{memory_id} not found"
        
        resp.raise_for_status()
        return f"Deleted memory #{memory_id}"
    
    except requests.RequestException as e:
        return f"[ERROR] Failed to delete memory: {e}"


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
    """
    try:
        resp = requests.put(
            f"{MEMORY_API_URL}/memories/{memory_id}",
            json={"properties": properties, "keywords": keywords},
            timeout=10,
        )
        
        if resp.status_code == 404:
            return f"Memory #{memory_id} not found"
        
        resp.raise_for_status()
        return f"Updated memory #{memory_id}"
    
    except requests.RequestException as e:
        return f"[ERROR] Failed to update memory: {e}"


async def execute_sql(sql: str, params: Optional[list] = None) -> str:
    """Execute raw SQL against the memory database.
    
    WARNING: Powerful and potentially dangerous. Use only for debugging.
    
    Args:
        sql: SQL statement to execute (SELECT, INSERT, UPDATE, DELETE)
        params: Optional list of parameters for the SQL query
    """
    try:
        resp = requests.post(
            f"{MEMORY_API_URL}/db/execute",
            json={"sql": sql, "params": params or []},
            timeout=30,
        )
        
        if resp.status_code != 200:
            error_detail = resp.json().get('detail', resp.text)
            return f"SQL Error: {error_detail}"
        
        result = resp.json()
        
        if result.get("type") == "select":
            rows = result.get("rows", [])
            if not rows:
                return "No results found."
            
            lines = [f"{result.get('count')} rows:"]
            for row in rows[:10]:
                lines.append(str(row))
            
            if len(rows) > 10:
                lines.append(f"... and {len(rows) - 10} more rows")
            
            return "\n".join(lines)
        else:
            return f"Executed. {result.get('rows_affected')} rows affected."
    
    except requests.RequestException as e:
        return f"[ERROR] SQL execution failed: {e}"


def _memory_context() -> str:
    """Return memory module context info."""
    return """## Memory Tools

Use these tools to store and retrieve persistent memories:
- **add_memory(content, keywords?, properties?)** - Store a new memory
- **search_memories(query, limit?)** - Search with DSL query
- **get_memory(memory_id)** - Get specific memory by ID
- **list_memories(limit?)** - List recent memories
- **delete_memory(memory_id)** - Delete a memory
- **update_memory(memory_id, properties?, keywords?)** - Update metadata
- **add_link(source_id, target_id, link_type?)** - Link two memories
- **get_memory_stats()** - Get database statistics

Query DSL: k:keyword (exact), s:keyword (semantic), q:text (semantic search),
d:date (date filter), p:key=value (property filter). Use AND/OR/NOT operators."""


def get_module() -> Module:
    """Get the memory module."""
    return Module(
        name="memory",
        called_fns=[
            CalledFn(
                name="search_memories",
                description="Search memories with DSL query: k:keyword (exact), s:keyword (semantic), q:text (semantic), d:date filter, AND/OR/NOT operators.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query in DSL format"},
                        "limit": {"type": "integer", "description": "Maximum results to return (default: 50)"},
                    },
                    "required": ["query"],
                },
                fn=search_memories,
            ),
            CalledFn(
                name="add_memory",
                description="Add a new memory with optional keywords and properties.",
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Main text content of the memory"},
                        "keywords": {"type": "array", "items": {"type": "string"}, "description": "Optional keywords for search"},
                        "properties": {"type": "object", "description": "Optional key-value properties"},
                    },
                    "required": ["content"],
                },
                fn=add_memory,
            ),
            CalledFn(
                name="get_memory",
                description="Get a specific memory by its ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "integer", "description": "Numeric ID of the memory"},
                    },
                    "required": ["memory_id"],
                },
                fn=get_memory,
            ),
            CalledFn(
                name="list_memories",
                description="List all memories, most recent first.",
                parameters={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Maximum memories to return (default: 20)"},
                    },
                    "required": [],
                },
                fn=list_memories,
            ),
            CalledFn(
                name="get_memory_stats",
                description="Get memory database statistics (total count).",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                fn=get_memory_stats,
            ),
            CalledFn(
                name="add_link",
                description="Create a link between two memories.",
                parameters={
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "integer", "description": "ID of source memory"},
                        "target_id": {"type": "integer", "description": "ID of target memory"},
                        "link_type": {"type": "string", "description": "Link type: related_to, summary_of, follows (default: related_to)"},
                    },
                    "required": ["source_id", "target_id"],
                },
                fn=add_link,
            ),
            CalledFn(
                name="delete_memory",
                description="Delete a memory by its ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "integer", "description": "Numeric ID of the memory to delete"},
                    },
                    "required": ["memory_id"],
                },
                fn=delete_memory,
            ),
            CalledFn(
                name="update_memory",
                description="Update a memory's properties and/or keywords.",
                parameters={
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "integer", "description": "Numeric ID of the memory"},
                        "properties": {"type": "object", "description": "Key-value properties to update"},
                        "keywords": {"type": "array", "items": {"type": "string"}, "description": "New keywords list"},
                    },
                    "required": ["memory_id"],
                },
                fn=update_memory,
            ),
            CalledFn(
                name="execute_sql",
                description="Execute raw SQL against memory database. WARNING: Dangerous, use for debugging only.",
                parameters={
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL statement to execute"},
                        "params": {"type": "array", "description": "Optional query parameters"},
                    },
                    "required": ["sql"],
                },
                fn=execute_sql,
            ),
        ],
        context_fns=[
            ContextFn(tag="memory", fn=_memory_context),
        ],
    )
