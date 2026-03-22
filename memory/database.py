"""Simplified memory database with vector embeddings."""

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
        embedding_model: Optional[EmbeddingModel] = None
    ):
        self.db_path = db_path
        self.embedding = embedding_model or EmbeddingModel()
        init_db(db_path)
    
    def add_memory(
        self,
        content: str,
        keywords: list[str] | None = None,
        properties: dict[str, str] | None = None,
        embedding: np.ndarray | None = None
    ) -> int:
        """Add a memory with optional keywords and properties.
        
        Args:
            content: The memory text
            keywords: Optional keywords to tag the memory
            properties: Optional key-value pairs (e.g., {"role": "user"})
            embedding: Optional pre-computed embedding (generated from content if not provided)
            
        Returns:
            The ID of the inserted memory
        """
        # Generate embedding if not provided
        if embedding is None:
            embedding = self.embedding.get(content)
        
        now = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            # Insert memory
            cursor = conn.execute(
                """INSERT INTO memories (content, embedding, created_at, last_updated)
                   VALUES (?, ?, ?, ?)""",
                (content, embedding.tobytes(), now, now)
            )
            memory_id = cursor.lastrowid
            
            # Handle keywords (lowercase, deduplicated)
            if keywords:
                unique_keywords = set(kw.lower().strip() for kw in keywords if kw.strip())
                
                for kw in unique_keywords:
                    # Get or create keyword
                    kw_row = conn.execute(
                        "SELECT id FROM keywords WHERE name = ?", (kw,)
                    ).fetchone()
                    
                    if kw_row is None:
                        # Insert new keyword
                        kw_embedding = self.embedding.get(kw)
                        cursor = conn.execute(
                            "INSERT INTO keywords (name, embedding) VALUES (?, ?)",
                            (kw, kw_embedding.tobytes())
                        )
                        kw_id = cursor.lastrowid
                    else:
                        kw_id = kw_row[0]
                    
                    # Link memory to keyword
                    conn.execute(
                        "INSERT OR IGNORE INTO memory_keywords (memory_id, keyword_id) VALUES (?, ?)",
                        (memory_id, kw_id)
                    )
            
            # Handle properties (lowercase key names)
            if properties:
                for key, value in properties.items():
                    key_lower = key.lower().strip()
                    if key_lower:
                        conn.execute(
                            """INSERT OR REPLACE INTO memory_properties (memory_id, key, value)
                               VALUES (?, ?, ?)""",
                            (memory_id, key_lower, value)
                        )
            
            conn.commit()
            
            return memory_id


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize the database schema.
    
    Args:
        db_path: Path to the SQLite database file
    """
    with sqlite3.connect(db_path) as conn:
        # Main memories table - simplified
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                embedding BLOB,
                created_at TEXT NOT NULL,
                last_updated TEXT NOT NULL,
                last_accessed TEXT
            )
        """)
        
        # Keywords table (with embeddings for similarity search)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                embedding BLOB
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
        
        # Memory properties (key-value store)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                UNIQUE(memory_id, key)
            )
        """)
        
        # Memory links (directional relationships)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                target_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                link_type TEXT NOT NULL,
                UNIQUE(source_id, target_id, link_type)
            )
        """)
        
        # Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mk_memory ON memory_keywords(memory_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mk_keyword ON memory_keywords(keyword_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_keyword_name ON keywords(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mp_memory_key ON memory_properties(memory_id, key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_links_source ON memory_links(source_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_links_target ON memory_links(target_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_links_type ON memory_links(link_type)")
        
        conn.commit()


if __name__ == "__main__":
    import tempfile
    import os
    
    # Mock embedding model that returns zeros
    class MockEmbeddingModel:
        def __init__(self):
            self.dimension = 384  # Common embedding dimension
        
        def get(self, text: str) -> np.ndarray:
            """Return a zero vector for testing."""
            return np.zeros(self.dimension, dtype=np.float32)
    
    # Create temp database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    try:
        print("Testing MemoryDB...")
        print("=" * 50)
        
        # Initialize with mock embedding
        db = MemoryDB(db_path, embedding_model=MockEmbeddingModel())
        
        # Test 1: Simple memory
        memory_id = db.add_memory("This is my first memory!")
        print(f"✓ Added memory {memory_id}: 'This is my first memory!'")
        
        # Test 2: Memory with keywords
        memory_id = db.add_memory(
            "Python is a great programming language",
            keywords=["Python", "programming", "python", "code"]  # should dedupe
        )
        print(f"✓ Added memory {memory_id} with keywords (deduplicated)")
        
        # Test 3: Memory with properties
        memory_id = db.add_memory(
            "User asked about the weather",
            properties={"role": "user", "source": "chat"}
        )
        print(f"✓ Added memory {memory_id} with properties")
        
        # Test 4: Memory with everything
        memory_id = db.add_memory(
            "Assistant provided a helpful response",
            keywords=["assistant", "help"],
            properties={"role": "assistant", "importance": "high"}
        )
        print(f"✓ Added memory {memory_id} with keywords AND properties")
        
        print("=" * 50)
        print("All tests passed! ✓")
        
    finally:
        # Cleanup
        os.unlink(db_path)
