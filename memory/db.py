"""Memory database with vector embeddings."""

import sqlite3
import numpy as np
from datetime import datetime, timezone
from typing import Optional

from embedding import EmbeddingModel

DEFAULT_DB_PATH = "memory.db"


class MemoryDB:
    """SQLite-based memory storage with vector embeddings."""
    
    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        embedding_model: EmbeddingModel | None = None
    ):
        self.db_path = db_path
        self.embedding = embedding_model or EmbeddingModel()
        self._init_db()
    
    def _init_db(self):
        """Initialize the database schema."""
        with sqlite3.connect(self.db_path) as conn:
            # Main memories table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    embedding BLOB,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # Keywords table (with embeddings for similarity search)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    embedding BLOB,
                    created_at TEXT NOT NULL
                )
            """)
            
            # Memory keywords junction
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_keywords (
                    memory_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
                    PRIMARY KEY (memory_id, keyword_id)
                )
            """)
            
            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mk_memory ON memory_keywords(memory_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mk_keyword ON memory_keywords(keyword_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_keyword_name ON keywords(name)")
            conn.commit()
    
    def add(
        self,
        content: str,
        role: str = "user",
        keywords: list[str] | None = None
    ) -> int:
        """Add a memory.
        
        Args:
            content: The content to store
            role: Role (user, assistant, system, tool)
            keywords: Optional keywords for the memory
            
        Returns:
            The ID of the inserted memory
        """
        embedding = self.embedding.get(content)
        now = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO memories (content, role, embedding, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (content, role, embedding.tobytes(), now, now)
            )
            memory_id = cursor.lastrowid
            
            # Add keywords (with embeddings)
            if keywords:
                for kw in keywords:
                    normalized = kw.lower().strip()
                    if not normalized:
                        continue
                    
                    # Check if keyword exists
                    kw_row = conn.execute(
                        "SELECT id, embedding FROM keywords WHERE name = ?", (normalized,)
                    ).fetchone()
                    
                    if kw_row:
                        # If exists but no embedding, generate one
                        if kw_row[1] is None:
                            kw_embedding = self.embedding.get(normalized)
                            conn.execute(
                                "UPDATE keywords SET embedding = ? WHERE id = ?",
                                (kw_embedding.tobytes(), kw_row[0])
                            )
                    else:
                        # Insert new keyword with embedding
                        kw_embedding = self.embedding.get(normalized)
                        conn.execute(
                            "INSERT INTO keywords (name, embedding, created_at) VALUES (?, ?, ?)",
                            (normalized, kw_embedding.tobytes(), now)
                        )
                        kw_row = conn.execute(
                            "SELECT id FROM keywords WHERE name = ?", (normalized,)
                        ).fetchone()
                    
                    if kw_row:
                        conn.execute(
                            "INSERT OR IGNORE INTO memory_keywords (memory_id, keyword_id) VALUES (?, ?)",
                            (memory_id, kw_row[0])
                        )
            
            conn.commit()
            return memory_id
    
    def get(self, memory_id: int) -> dict | None:
        """Get a memory by ID.
        
        Args:
            memory_id: The ID of the memory
            
        Returns:
            Dictionary with memory data, or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if not row:
                return None
            
            keywords = conn.execute(
                """SELECT k.name FROM keywords k
                   JOIN memory_keywords mk ON mk.keyword_id = k.id
                   WHERE mk.memory_id = ?""",
                (memory_id,)
            ).fetchall()
            
            return {
                "id": row["id"],
                "content": row["content"],
                "role": row["role"],
                "keywords": [k["name"] for k in keywords],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
    
    def search_by_keyword(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search memories by keyword.
        
        Args:
            keyword: Keyword to search for
            limit: Maximum number of results
            
        Returns:
            List of matching memories
        """
        normalized = keyword.lower().strip()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT DISTINCT m.* FROM memories m
                   JOIN memory_keywords mk ON mk.memory_id = m.id
                   JOIN keywords k ON k.id = mk.keyword_id
                   WHERE k.name = ?
                   ORDER BY m.created_at DESC
                   LIMIT ?""",
                (normalized, limit)
            ).fetchall()
            
            results = []
            for row in rows:
                keywords = conn.execute(
                    """SELECT k.name FROM keywords k
                       JOIN memory_keywords mk ON mk.keyword_id = k.id
                       WHERE mk.memory_id = ?""",
                    (row["id"],)
                ).fetchall()
                
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "role": row["role"],
                    "keywords": [k["name"] for k in keywords],
                    "created_at": row["created_at"]
                })
            
            return results
    
    def search_similar(self, query: str, limit: int = 5) -> list[dict]:
        """Search memories by semantic similarity.
        
        Args:
            query: Text query to search for
            limit: Maximum number of results
            
        Returns:
            List of similar memories with similarity scores
        """
        query_embedding = self.embedding.get(query)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memories WHERE embedding IS NOT NULL"
            ).fetchall()
            
            results = []
            for row in rows:
                stored = np.frombuffer(row["embedding"], dtype=np.float32)
                similarity = self._cosine_similarity(query_embedding, stored)
                
                keywords = conn.execute(
                    """SELECT k.name FROM keywords k
                       JOIN memory_keywords mk ON mk.keyword_id = k.id
                       WHERE mk.memory_id = ?""",
                    (row["id"],)
                ).fetchall()
                
                
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "role": row["role"],
                    "keywords": [k["name"] for k in keywords],
                    "created_at": row["created_at"],
                    "similarity": float(similarity)
                })
            
            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results[:limit]
    
    def search_similar_keywords(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search memories by similar keywords.
        
        Finds keywords similar to the given keyword using embeddings,
        then returns memories containing those keywords.
        
        Args:
            keyword: Keyword to search for similar matches
            limit: Maximum number of results
            
        Returns:
            List of memories with similarity scores based on keyword match
        """
        normalized = keyword.lower().strip()
        query_embedding = self.embedding.get(normalized)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Get all keywords with embeddings
            kw_rows = conn.execute(
                "SELECT * FROM keywords WHERE embedding IS NOT NULL"
            ).fetchall()
            
            # Find similar keywords
            similar_keywords = []
            for kw_row in kw_rows:
                stored = np.frombuffer(kw_row["embedding"], dtype=np.float32)
                similarity = self._cosine_similarity(query_embedding, stored)
                similar_keywords.append({
                    "id": kw_row["id"],
                    "name": kw_row["name"],
                    "similarity": float(similarity)
                })
            
            similar_keywords.sort(key=lambda x: x["similarity"], reverse=True)
            
            # Get keyword IDs to search for
            keyword_ids = [k["id"] for k in similar_keywords[:limit]]
            
            if not keyword_ids:
                return []
            
            # Get memories with those keywords
            placeholders = ",".join("?" for _ in keyword_ids)
            memory_rows = conn.execute(
                f"""SELECT DISTINCT m.* FROM memories m
                   JOIN memory_keywords mk ON mk.memory_id = m.id
                   WHERE mk.keyword_id IN ({placeholders})
                   ORDER BY m.created_at DESC
                   LIMIT ?""",
                (*keyword_ids, limit)
            ).fetchall()
            
            results = []
            for row in memory_rows:
                # Get keywords for this memory
                keywords = conn.execute(
                    """SELECT k.name FROM keywords k
                       JOIN memory_keywords mk ON mk.keyword_id = k.id
                       WHERE mk.memory_id = ?""",
                    (row["id"],)
                ).fetchall()
                
                # Calculate best keyword similarity for this memory
                mem_kw_ids = conn.execute(
                    "SELECT keyword_id FROM memory_keywords WHERE memory_id = ?",
                    (row["id"],)
                ).fetchall()
                mem_kw_ids = [m[0] for m in mem_kw_ids]
                best_sim = max(
                    (k["similarity"] for k in similar_keywords if k["id"] in mem_kw_ids),
                    default=0.0
                )
                
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "role": row["role"],
                    "keywords": [k["name"] for k in keywords],
                    "created_at": row["created_at"],
                    "similarity": best_sim
                })
            
            return results
    
    def get_recent(self, limit: int = 50) -> list[dict]:
        """Get recent memories.
        
        Args:
            limit: Maximum number of memories
            
        Returns:
            List of recent memories
        """
        return self.search_dated(limit=limit)
    
    def search_dated(
        self,
        keywords: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50
    ) -> list[dict]:
        """Search memories with optional keyword and date filtering.
        
        Args:
            keywords: Single keyword or list of keywords to search for
            start_date: Filter memories created on or after this date (ISO format)
            end_date: Filter memories created on or before this date (ISO format)
            limit: Maximum number of results
            
        Returns:
            List of matching memories
        """
        # Normalize keywords
        keyword_list = []
        if keywords:
            if isinstance(keywords, str):
                keyword_list = [keywords.lower().strip()]
            else:
                keyword_list = [k.lower().strip() for k in keywords if k]
        
        # Validate dates
        if start_date:
            try:
                datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"Invalid start_date: {start_date}")
        
        if end_date:
            try:
                datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"Invalid end_date: {end_date}")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Build query
            select_parts = ["SELECT DISTINCT m.*"]
            from_parts = ["FROM memories m"]
            where_parts = []
            params = []
            
            # Keyword join
            if keyword_list:
                from_parts.append("JOIN memory_keywords mk ON mk.memory_id = m.id")
                from_parts.append("JOIN keywords k ON k.id = mk.keyword_id")
                placeholders = ",".join("?" for _ in keyword_list)
                where_parts.append(f"k.name IN ({placeholders})")
                params.extend(keyword_list)
            
            # Date filters
            if start_date:
                where_parts.append("m.created_at >= ?")
                params.append(start_date)
            
            if end_date:
                where_parts.append("m.created_at <= ?")
                params.append(end_date)
            
            # Build and execute
            query = " ".join(select_parts + from_parts)
            if where_parts:
                query += " WHERE " + " AND ".join(where_parts)
            query += " ORDER BY m.created_at DESC LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            
            results = []
            for row in rows:
                keywords = conn.execute(
                    """SELECT k.name FROM keywords k
                       JOIN memory_keywords mk ON mk.keyword_id = k.id
                       WHERE mk.memory_id = ?""",
                    (row["id"],)
                ).fetchall()
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "role": row["role"],
                    "keywords": [k["name"] for k in keywords],
                    "created_at": row["created_at"]
                })
            
            return results
    
    def delete(self, memory_id: int) -> bool:
        """Delete a memory.
        
        Args:
            memory_id: ID of the memory to delete
            
        Returns:
            True if deleted, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def count(self) -> int:
        """Get total number of memories.
        
        Returns:
            Count of memories
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM memories")
            return cursor.fetchone()[0]
    
    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
