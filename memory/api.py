"""Memory API server - FastAPI endpoints for memory storage."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from db import MemoryDB

app = FastAPI(title="Riven Memory API")

# Global database instance
db: MemoryDB | None = None


class MemoryRequest(BaseModel):
    """Request to add a memory."""
    content: str
    role: str = "user"
    keywords: list[str] | None = None


class SearchRequest(BaseModel):
    """Request to search memories."""
    query: str
    limit: int = 5
    start_date: str | None = None
    end_date: str | None = None


@app.on_event("startup")
async def startup():
    """Initialize the database on startup."""
    global db
    db = MemoryDB()


@app.post("/memories")
async def add_memory(request: MemoryRequest) -> dict:
    """Add a new memory.
    
    Args:
        request: Memory content, role, and optional keywords
        
    Returns:
        The ID of the created memory
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    memory_id = db.add(
        content=request.content,
        role=request.role,
        keywords=request.keywords
    )
    
    return {"id": memory_id, "content": request.content[:100]}


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
    
    memory = db.get(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    return memory


@app.get("/memories")
async def get_memories(
    limit: int = 50,
    start_date: str | None = None,
    end_date: str | None = None
) -> dict:
    """Get recent memories with optional date filtering.
    
    Args:
        limit: Maximum number of memories to return
        start_date: Filter memories created on or after this date (ISO format)
        end_date: Filter memories created on or before this date (ISO format)
        
    Returns:
        List of recent memories
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    return {"memories": db.search_dated(limit=limit, start_date=start_date, end_date=end_date)}


@app.get("/memories/search/keyword/{keyword}")
async def search_by_keyword(
    keyword: str,
    limit: int = 10,
    start_date: str | None = None,
    end_date: str | None = None
) -> dict:
    """Search memories by keyword with optional date filtering.
    
    Args:
        keyword: Keyword to search for
        limit: Maximum number of results
        start_date: Filter memories created on or after this date (ISO format)
        end_date: Filter memories created on or before this date (ISO format)
        
    Returns:
        List of matching memories
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    return {"memories": db.search_dated(keywords=keyword, limit=limit, start_date=start_date, end_date=end_date)}


@app.get("/memories/search/similar-keywords/{keyword}")
async def search_similar_keywords(
    keyword: str,
    limit: int = 10,
    start_date: str | None = None,
    end_date: str | None = None
) -> dict:
    """Search memories by similar keywords with optional date filtering.
    
    Finds keywords similar to the given keyword and returns memories
    containing those keywords.
    
    Args:
        keyword: Keyword to search for similar matches
        limit: Maximum number of results
        start_date: Filter memories created on or after this date (ISO format)
        end_date: Filter memories created on or before this date (ISO format)
        
    Returns:
        List of matching memories with similarity scores
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # First get similar keyword results
    memories = db.search_similar_keywords(keyword, limit)
    
    # Filter by date if needed
    if start_date or end_date:
        filtered = []
        for mem in memories:
            created = mem["created_at"]
            if start_date and created < start_date:
                continue
            if end_date and created > end_date:
                continue
            filtered.append(mem)
        memories = filtered
    
    return {"memories": memories}


@app.post("/memories/search/similar")
async def search_similar(request: SearchRequest) -> dict:
    """Search memories by semantic similarity with optional date filtering.
    
    Args:
        request: Query, limit, and optional date range
        
    Returns:
        List of similar memories with scores
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    memories = db.search_similar(request.query, request.limit)
    
    # Filter by date if needed
    if request.start_date or request.end_date:
        filtered = []
        for mem in memories:
            created = mem["created_at"]
            if request.start_date and created < request.start_date:
                continue
            if request.end_date and created > request.end_date:
                continue
            filtered.append(mem)
        memories = filtered
    
    return {"memories": memories}


@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int) -> dict:
    """Delete a memory.
    
    Args:
        memory_id: ID of the memory to delete
        
    Returns:
        Success message
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    deleted = db.delete(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    return {"deleted": memory_id}


@app.get("/stats")
async def get_stats() -> dict:
    """Get memory statistics.
    
    Returns:
        Count of memories
    """
    if not db:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    return {"count": db.count()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8030)
