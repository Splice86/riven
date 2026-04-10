"""Memory module for riven - interact with the memory database."""

import sqlite3
from dataclasses import dataclass
from typing import Optional, Any

from modules import Module


@dataclass
class MemoryResult:
    """Result from a memory operation."""
    success: bool
    data: Any
    message: str


class MemoryModule:
    """Module for interacting with the memory database."""
    
    def __init__(self, db_path: str = "memory/memory.db", db_name: str = "default"):
        self.db_path = db_path
        self.db_name = db_name
        
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)
    
    def search(
        self,
        query: str = "",
        limit: int = 50
    ) -> list[dict]:
        """Search memories by keyword, property, or content.
        
        Args:
            query: Search query. Supports:
                - k:keyword - search by keyword
                - p:key=value - search by property
                - id:123 - search by memory ID
                - Plain text searches content
            limit: Maximum results to return
            
        Returns:
            List of memory dicts with id, content, keywords, properties, created_at
        """
        from memory.search import MemorySearcher
        from memory.embedding import EmbeddingModel
        
        try:
            searcher = MemorySearcher(self.db_path, EmbeddingModel())
            results = searcher.search(query, limit)
            return results
        except Exception as e:
            return [{"error": str(e)}]
    
    def add(
        self,
        content: str,
        keywords: Optional[list[str]] = None,
        properties: Optional[dict[str, str]] = None,
        created_at: Optional[str] = None
    ) -> dict:
        """Add a new memory to the database.
        
        Args:
            content: The memory content/text
            keywords: Optional list of keyword tags
            properties: Optional dict of properties
            created_at: Optional ISO timestamp
            
        Returns:
            Dict with id and content of created memory
        """
        from memory.database import MemoryDB
        from memory.embedding import EmbeddingModel
        
        try:
            db = MemoryDB(self.db_path, EmbeddingModel())
            memory_id = db.add_memory(
                content=content,
                keywords=keywords,
                properties=properties,
                created_at=created_at
            )
            return {"id": memory_id, "content": content[:100]}
        except Exception as e:
            return {"error": str(e)}
    
    def get(self, memory_id: int) -> Optional[dict]:
        """Get a memory by ID.
        
        Args:
            memory_id: The memory ID to retrieve
            
        Returns:
            Memory dict or None if not found
        """
        from memory.database import MemoryDB
        from memory.embedding import EmbeddingModel
        
        try:
            db = MemoryDB(self.db_path, EmbeddingModel())
            return db.get_memory(memory_id)
        except Exception as e:
            return {"error": str(e)}
    
    def update(
        self,
        memory_id: int,
        properties: Optional[dict[str, str]] = None,
        keywords: Optional[list[str]] = None
    ) -> Optional[dict]:
        """Update a memory's properties and/or keywords.
        
        Args:
            memory_id: The memory ID to update
            properties: Dict of properties to set
            keywords: List of keywords to set
            
        Returns:
            Updated memory dict or None if not found
        """
        from memory.database import MemoryDB
        from memory.embedding import EmbeddingModel
        
        try:
            db = MemoryDB(self.db_path, EmbeddingModel())
            return db.update_memory(memory_id, properties, keywords)
        except Exception as e:
            return {"error": str(e)}
    
    def delete(self, memory_id: int) -> bool:
        """Delete a memory by ID.
        
        Args:
            memory_id: The memory ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        from memory.database import MemoryDB
        from memory.embedding import EmbeddingModel
        
        try:
            db = MemoryDB(self.db_path, EmbeddingModel())
            return db.delete_memory(memory_id)
        except Exception as e:
            return False
    
    def add_link(
        self,
        source_id: int,
        target_id: int,
        link_type: str = "related_to"
    ) -> dict:
        """Add a link between two memories.
        
        Args:
            source_id: ID of the source memory
            target_id: ID of the target memory
            link_type: Type of link (e.g., "related_to", "summary_of", "blocks")
            
        Returns:
            Dict with success status
        """
        from memory.database import MemoryDB
        from memory.embedding import EmbeddingModel
        
        try:
            db = MemoryDB(self.db_path, EmbeddingModel())
            db.add_link(source_id, target_id, link_type)
            return {"success": True, "source_id": source_id, "target_id": target_id, "link_type": link_type}
        except Exception as e:
            return {"error": str(e)}
    
    def list_all(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """List all memories with pagination.
        
        Args:
            limit: Maximum memories to return
            offset: Number of memories to skip
            
        Returns:
            List of memory dicts
        """
        return self.search("", limit=limit + offset)[offset:offset + limit]
    
    def count(self) -> int:
        """Get total memory count.
        
        Returns:
            Number of memories in the database
        """
        results = self.search("", limit=10000)
        return len(results)
    
    def get_by_keyword(self, keyword: str, limit: int = 50) -> list[dict]:
        """Get all memories with a specific keyword.
        
        Args:
            keyword: The keyword to search for
            limit: Maximum results
            
        Returns:
            List of memory dicts
        """
        return self.search(f"k:{keyword}", limit=limit)
    
    def get_by_property(self, key: str, value: str, limit: int = 50) -> list[dict]:
        """Get all memories with a specific property value.
        
        Args:
            key: Property key
            value: Property value
            limit: Maximum results
            
        Returns:
            List of memory dicts
        """
        return self.search(f"p:{key}={value}", limit=limit)
    
    def get_recent(self, hours: int = 24, limit: int = 50) -> list[dict]:
        """Get recent memories from the last N hours.
        
        Args:
            hours: Number of hours to look back
            limit: Maximum results
            
        Returns:
            List of memory dicts
        """
        return self.search(f"d:last {hours} hours", limit=limit)
    
    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a raw SQL query.
        
        WARNING: This allows raw database access. Use with caution.
        
        Args:
            sql: SQL query to execute (SELECT only for safety)
            params: Optional query parameters
            
        Returns:
            List of result rows as dicts
        """
        # Only allow SELECT queries for safety
        if not sql.strip().upper().startswith("SELECT"):
            return [{"error": "Only SELECT queries allowed for safety"}]
        
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            return [{"error": str(e)}]
    
    def execute(self, sql: str, params: tuple = ()) -> dict:
        """Execute a raw SQL statement (INSERT, UPDATE, DELETE).
        
        WARNING: This allows raw database modification. Use with caution.
        
        Args:
            sql: SQL statement to execute
            params: Optional query parameters
            
        Returns:
            Dict with success status and affected rows
        """
        # Block SELECT - use query() instead
        if sql.strip().upper().startswith("SELECT"):
            return {"error": "Use query() for SELECT statements"}
        
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(sql, params)
                conn.commit()
                return {"success": True, "affected_rows": cursor.rowcount}
        except Exception as e:
            return {"error": str(e)}
    
    def get_schema(self) -> dict:
        """Get the database schema.
        
        Returns:
            Dict with table names and their schemas
        """
        schema = {}
        try:
            with self._get_connection() as conn:
                # Get all tables
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [row[0] for row in cursor.fetchall()]
                
                for table in tables:
                    # Get schema for each table
                    cursor = conn.execute(f"PRAGMA table_info({table})")
                    columns = []
                    for row in cursor.fetchall():
                        columns.append({
                            "name": row[1],
                            "type": row[2],
                            "nullable": not row[3],
                            "default": row[4],
                            "primary_key": bool(row[5])
                        })
                    schema[table] = columns
                    
        except Exception as e:
            return {"error": str(e)}
        
        return schema
    
    def get_context(self, query: str = "", limit: int = 5) -> str:
        """Get relevant memories formatted for system prompt context.
        
        Args:
            query: Search query to find relevant memories
            limit: Maximum memories to return
            
        Returns:
            Formatted string of relevant memories
        """
        if not query:
            # Default to recent memories
            results = self.get_recent(hours=24, limit=limit)
        else:
            results = self.search(query, limit=limit)
        
        if not results:
            return "No relevant memories found."
        
        lines = ["## Relevant Memories"]
        for m in results:
            content = m.get("content", "")[:200]
            keywords = m.get("keywords", [])
            created = m.get("created_at", "")[:19]
            kw_str = f" [{', '.join(keywords)}]" if keywords else ""
            lines.append(f"- [{m.get('id')}]{kw_str} {created}: {content}")
        
        return "\n".join(lines)


def get_module(db_path: str = "memory/memory.db", db_name: str = "default"):
    """Get the memory module.
    
    Args:
        db_path: Path to the memory database
        db_name: Name of the database (for API compatibility)
        
    Returns:
        Module instance with memory tools
    """
    manager = MemoryModule(db_path=db_path, db_name=db_name)
    
    async def search_memories(query: str = "", limit: int = 50) -> str:
        """Search the memory database.
        
        Args:
            query: Search query (k:keyword, p:key=value, id:123, or plain text)
            limit: Maximum results to return
            
        Returns:
            Formatted search results
        """
        results = manager.search(query, limit)
        if not results:
            return "No memories found."
        
        lines = [f"Found {len(results)} memories:"]
        for m in results[:10]:
            content = m.get("content", "")[:100]
            keywords = m.get("keywords", [])
            kw_str = f" [{', '.join(keywords)}]" if keywords else ""
            lines.append(f"  [{m.get('id')}]{kw_str}: {content}")
        
        if len(results) > 10:
            lines.append(f"  ... and {len(results) - 10} more")
        
        return "\n".join(lines)
    
    async def add_memory(
        content: str,
        keywords: Optional[list[str]] = None,
        properties: Optional[dict[str, str]] = None
    ) -> str:
        """Add a new memory to the database.
        
        Args:
            content: The memory content/text
            keywords: Optional list of keyword tags
            properties: Optional dict of properties (e.g., {"project": "myapp"})
            
        Returns:
            Confirmation with memory ID
        """
        result = manager.add(content, keywords, properties)
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Added memory #{result['id']}: {result['content'][:50]}..."
    
    async def get_memory(memory_id: int) -> str:
        """Get a specific memory by ID.
        
        Args:
            memory_id: The memory ID to retrieve
            
        Returns:
            Formatted memory details
        """
        result = manager.get(memory_id)
        if result is None:
            return f"Memory #{memory_id} not found"
        if "error" in result:
            return f"Error: {result['error']}"
        
        lines = [f"## Memory #{result['id']}"]
        lines.append(f"Created: {result['created_at']}")
        if result.get("keywords"):
            lines.append(f"Keywords: {', '.join(result['keywords'])}")
        if result.get("properties"):
            props = ", ".join(f"{k}={v}" for k, v in result["properties"].items())
            lines.append(f"Properties: {props}")
        lines.append(f"\n{result['content']}")
        
        return "\n".join(lines)
    
    async def update_memory(
        memory_id: int,
        properties: Optional[dict[str, str]] = None,
        keywords: Optional[list[str]] = None
    ) -> str:
        """Update a memory's properties and/or keywords.
        
        Args:
            memory_id: The memory ID to update
            properties: Dict of properties to set
            keywords: List of keywords to set
            
        Returns:
            Confirmation message
        """
        result = manager.update(memory_id, properties, keywords)
        if result is None:
            return f"Memory #{memory_id} not found"
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Updated memory #{memory_id}"
    
    async def delete_memory(memory_id: int) -> str:
        """Delete a memory by ID.
        
        Args:
            memory_id: The memory ID to delete
            
        Returns:
            Confirmation message
        """
        success = manager.delete(memory_id)
        if success:
            return f"Deleted memory #{memory_id}"
        return f"Memory #{memory_id} not found"
    
    async def link_memories(
        source_id: int,
        target_id: int,
        link_type: str = "related_to"
    ) -> str:
        """Link two memories together.
        
        Args:
            source_id: ID of the source memory
            target_id: ID of the target memory
            link_type: Type of link (e.g., "related_to", "blocks", "depends_on")
            
        Returns:
            Confirmation message
        """
        result = manager.add_link(source_id, target_id, link_type)
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Linked memory #{source_id} -> #{target_id} ({link_type})"
    
    async def list_memories(limit: int = 20, offset: int = 0) -> str:
        """List all memories with pagination.
        
        Args:
            limit: Maximum memories to return
            offset: Number of memories to skip
            
        Returns:
            Formatted list of memories
        """
        results = manager.list_all(limit, offset)
        if not results:
            return "No memories in database."
        
        total = manager.count()
        lines = [f"Memories {offset+1}-{min(offset+limit, total)} of {total}:"]
        for m in results:
            content = m.get("content", "")[:60]
            created = m.get("created_at", "")[:19]
            lines.append(f"  [{m.get('id')}] {created}: {content}")
        
        return "\n".join(lines)
    
    async def get_memory_stats() -> str:
        """Get memory database statistics.
        
        Returns:
            Formatted stats
        """
        total = manager.count()
        schema = manager.get_schema()
        
        lines = [f"## Memory Database Stats", f"Total memories: {total}"]
        
        # Count by keyword
        keyword_counts: dict[str, int] = {}
        for m in manager.list_all(limit=1000):
            for kw in m.get("keywords", []):
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
        
        if keyword_counts:
            top_kw = sorted(keyword_counts.items(), key=lambda x: -x[1])[:10]
            lines.append("Top keywords:")
            for kw, count in top_kw:
                lines.append(f"  {kw}: {count}")
        
        return "\n".join(lines)
    
    async def run_query(sql: str) -> str:
        """Execute a raw SQL SELECT query.
        
        WARNING: Use with caution. Only SELECT statements allowed.
        
        Args:
            sql: SQL query to execute
            
        Returns:
            Query results
        """
        results = manager.query(sql)
        if not results:
            return "No results"
        if "error" in results[0]:
            return f"Error: {results[0]['error']}"
        
        lines = [f"Query returned {len(results)} rows:"]
        for row in results[:20]:
            lines.append(f"  {row}")
        
        if len(results) > 20:
            lines.append(f"  ... and {len(results) - 20} more")
        
        return "\n".join(lines)
    
    async def run_sql(sql: str) -> str:
        """Execute a raw SQL statement (INSERT, UPDATE, DELETE).
        
        WARNING: Use with caution - this modifies the database.
        
        Args:
            sql: SQL statement to execute
            
        Returns:
            Execution result
        """
        result = manager.execute(sql)
        if "error" in result:
            return f"Error: {result['error']}"
        return f"Executed. Affected {result['affected_rows']} rows"
    
    async def get_db_schema() -> str:
        """Get the database schema.
        
        Returns:
            Formatted schema
        """
        schema = manager.get_schema()
        if "error" in schema:
            return f"Error: {schema['error']}"
        
        lines = ["## Database Schema"]
        for table, columns in schema.items():
            lines.append(f"\n### {table}")
            for col in columns:
                pk = " PK" if col["primary_key"] else ""
                nullable = "" if col["nullable"] else " NOT NULL"
                lines.append(f"  {col['name']}: {col['type']}{pk}{nullable}")
        
        return "\n".join(lines)
    
    async def get_search_help() -> str:
        """Get search syntax help.
        
        Returns:
            Search syntax documentation
        """
        return """## Memory Search Syntax

### Filters
- `k:keyword` - Search by keyword tag
- `p:key=value` - Search by property (exact match)
- `p:key>value` - Numeric comparison (>, <, >=, <=, !=)
- `d:last N days` - Filter by date
- `q:text` - Semantic similarity search
- `id:123` - Get specific memory by ID
- `l:link_type` - Find memories by link relationship

### Operators
- `AND` - Both conditions must match (default)
- `OR` - Either condition matches
- `NOT` - Negate a condition
- `(...)` - Group conditions

### Examples
- `k:python` - memories tagged with python
- `k:python AND k:asyncio` - both keywords
- `p:project=webapp` - property exact match
- `p:priority>=3` - numeric comparison
- `d:last 7 days` - from last week
- `k:bug AND p:status=open` - complex query
"""
    
    async def get_recent_context(hours: int = 24, limit: int = 5) -> str:
        """Get recent memories for context.
        
        Args:
            hours: How many hours back to look
            limit: Maximum memories to return
            
        Returns:
            Formatted recent memories
        """
        return manager.get_context(limit=limit)
    
    return Module(
        name="memory",
        enrollment=lambda: None,
        functions={
            "search_memories": search_memories,
            "add_memory": add_memory,
            "get_memory": get_memory,
            "update_memory": update_memory,
            "delete_memory": delete_memory,
            "link_memories": link_memories,
            "list_memories": list_memories,
            "get_memory_stats": get_memory_stats,
            "run_query": run_query,
            "run_sql": run_sql,
            "get_db_schema": get_db_schema,
            "get_recent_context": get_recent_context,
            "get_search_help": get_search_help,
        },
        get_context=manager.get_context,
        tag="memory"
    )