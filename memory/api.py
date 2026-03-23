"""Memory API server - FastAPI endpoints for memory storage and search."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from database import MemoryDB, init_db

app = FastAPI(title="Riven Memory API")

# Global database instance
db: MemoryDB | None = None


class AddMemoryRequest(BaseModel):
    """Request to add a memory with tags/properties."""
    content: str
    keywords: list[str] | None = None
    properties: dict[str, str] | None = None
    created_at: str | None = None  # Optional timestamp (ISO format)


class AddSummaryRequest(BaseModel):
    """Request to add a summary memory with links to target memories."""
    content: str
    keywords: list[str] | None = None
    properties: dict[str, str] | None = None
    created_at: str  # Required timestamp (ISO format) - set by agent
    target_ids: list[int]  # List of memory IDs to link to
    link_type: str = "summary_of"


class AddLinkRequest(BaseModel):
    """Request to add a link between two memories."""
    source_id: int
    target_id: int
    link_type: str = "related_to"


class SearchRequest(BaseModel):
    """Request to search memories."""
    query: str
    limit: int = 50


@app.on_event("startup")
async def startup():
    """Initialize the database on startup."""
    global db
    init_db()
    db = MemoryDB()


@app.post("/memories")
async def add_memory(request: AddMemoryRequest) -> dict:
    """Add a new memory with optional keywords and properties.
    
    Args:
        request: Memory content, optional keywords, properties, and created_at timestamp
        
    Returns:
        The ID of the created memory
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    memory_id = db.add_memory(
        content=request.content,
        keywords=request.keywords,
        properties=request.properties,
        created_at=request.created_at
    )
    
    return {"id": memory_id, "content": request.content[:100]}


@app.post("/memories/summary")
async def add_summary(request: AddSummaryRequest) -> dict:
    """Add a summary memory and link it to target memories.
    
    The created_at timestamp is required and should be set by the agent
    making the API call to time-bound the summary.
    
    Args:
        request: Summary content, keywords, properties, created_at, target_ids, link_type
        
    Returns:
        The ID of the created summary memory
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # Add the summary memory
    summary_id = db.add_memory(
        content=request.content,
        keywords=request.keywords,
        properties=request.properties,
        created_at=request.created_at
    )
    
    # Link to each target memory
    for target_id in request.target_ids:
        db.add_link(
            source_id=summary_id,
            target_id=target_id,
            link_type=request.link_type
        )
    
    return {"id": summary_id, "content": request.content[:100], "linked_to": request.target_ids}


@app.post("/memories/link")
async def add_link(request: AddLinkRequest) -> dict:
    """Add a link between two existing memories.
    
    Args:
        request: source_id, target_id, link_type
        
    Returns:
        Success message with link details
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    db.add_link(
        source_id=request.source_id,
        target_id=request.target_id,
        link_type=request.link_type
    )
    
    return {
        "source_id": request.source_id,
        "target_id": request.target_id,
        "link_type": request.link_type,
        "message": "Link created successfully"
    }


@app.post("/memories/search")
async def search_memories(request: SearchRequest) -> dict:
    """Search memories using the query DSL.
    
    Args:
        request: Query string and limit
        
    Returns:
        List of matching memories
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    results = db.search(request.query, limit=request.limit)
    
    return {"memories": results, "count": len(results)}


@app.get("/memories")
async def list_memories(limit: int = 50, offset: int = 0) -> dict:
    """List all memories with pagination.
    
    Args:
        limit: Maximum number of memories to return
        offset: Number of memories to skip
        
    Returns:
        List of memories
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    results = db.search("", limit=limit + offset)
    return {
        "memories": results[offset:offset + limit],
        "count": len(results),
        "limit": limit,
        "offset": offset
    }


@app.get("/memories/{memory_id}")
async def get_memory(memory_id: int) -> dict:
    """Get a memory by ID.
    
    Args:
        memory_id: The ID of the memory
        
    Returns:
        The memory data
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    results = db.search(f"id:{memory_id}", limit=1)
    if not results:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    return results[0]


@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int) -> dict:
    """Delete a memory by ID.
    
    Args:
        memory_id: The ID of the memory to delete
        
    Returns:
        Success message
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # Note: The database module doesn't have a delete method currently
    # This would need to be added if deletion is required
    raise HTTPException(status_code=501, detail="Delete not implemented")


@app.get("/stats")
async def get_stats() -> dict:
    """Get memory statistics.
    
    Returns:
        Count of memories
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    results = db.search("", limit=10000)
    
    return {"count": len(results)}


@app.get("/docs/search-syntax")
async def get_search_syntax() -> dict:
    """Get documentation for the search query syntax.
    
    Returns:
        Search syntax documentation
    """
    return {
        "title": "Memory Search Query Syntax",
        "version": "1.0",
        "operators": {
            "AND": "Both conditions must match. Default between terms.",
            "OR": "Either condition can match.",
            "NOT": "Negate a condition."
        },
        "filters": {
            "keyword": {
                "syntax": "k:<keyword> or keyword:<keyword>",
                "example": "k:python or python",
                "description": "Search by keyword tag"
            },
            "property": {
                "syntax": "p:<key>=<value> or p:<key><op><value>",
                "example": "p:status=active, p:rating>=4, p:opinion<0",
                "description": "Filter by property. Supports string equality and numeric comparisons: <, >, <=, >=, !="
            },
            "date": {
                "syntax": "d:last <n> days or d:<date>",
                "example": "d:last 7 days, d:2025-01-01",
                "description": "Filter by creation date. 'd:last N days' finds memories created in the last N days."
            },
            "similarity": {
                "syntax": "q:<query> or q:<query>@<threshold> or s:<keyword>@<threshold>",
                "example": "q:async programming, q:async@0.7, s:python@0.5",
                "description": "Semantic similarity search. Lower threshold = more permissive. Requires vector embedding."
            },
            "link": {
                "syntax": "l:<link_type> or l:direction:<link_type> or l:<link_type>:(filter)",
                "example": "l:related_to, l:summary_of, l:source:related_to, l:target:related_to, l:summary_of:(k:python)",
                "description": "Find memories by link relationships. Direction: source=links TO others, target=IS LINKED TO."
            },
            "id": {
                "syntax": "id:<memory_id>",
                "example": "id:123",
                "description": "Find a specific memory by ID"
            }
        },
        "conditionals": {
            "syntax": "IF <condition> THEN <query> ELSE <query>",
            "example": "IF k:python THEN k:asyncio ELSE k:docker",
            "description": "Conditional queries based on whether the first condition returns results"
        },
        "grouping": {
            "syntax": "(<query>) AND/OR (<query>)",
            "example": "(k:python OR k:javascript) AND d:last 7 days",
            "description": "Use parentheses to group conditions and control precedence"
        },
        "examples": [
            "k:python AND k:asyncio - memories with both python and asyncio keywords",
            "p:status=active AND k:python - active memories about python",
            "p:opinion<0 - memories with negative opinion (numeric comparison)",
            "p:rating>=4 AND k:positive - highly rated positive memories",
            "d:last 7 days AND (k:python OR k:javascript) - recent Python or JS",
            "l:summary_of:(k:python) - summaries linked to python memories",
            "l:source:related_to - memories that link TO other memories",
            "l:target:related_to - memories that ARE LINKED TO by others",
            "IF k:python THEN k:asyncio ELSE k:docker - conditional based on keyword",
            "(k:python OR k:javascript) AND (d:last 7 days OR p:status=active) - complex nested"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8030)
