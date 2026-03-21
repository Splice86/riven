"""Embedding model with automatic caching."""

import sqlite3
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "/home/david/Data/Models/Qwen3-Embedding-4B"
DEFAULT_CACHE_DB = "embeddings_cache.db"


class EmbeddingModel:
    """Embedding model with SQLite caching."""
    
    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        cache_db: str = DEFAULT_CACHE_DB,
        device: str | None = None
    ):
        self.model_path = model_path
        self.cache_db = cache_db
        
        # Determine device: explicit > auto-cuda > auto-cpu
        if device is not None:
            self.device = device
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"
        
        # Try to load model, fall back to CPU if CUDA fails (OOM)
        try:
            self.model = SentenceTransformer(model_path, device=self.device)
        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "cuda" in str(e).lower():
                print(f"Warning: CUDA failed ({e}), falling back to CPU")
                self.device = "cpu"
                self.model = SentenceTransformer(model_path, device="cpu")
            else:
                raise
        
        self._init_cache()
    
    def _init_cache(self):
        """Initialize the cache database."""
        with sqlite3.connect(self.cache_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    text TEXT PRIMARY KEY,
                    embedding BLOB
                )
            """)
    
    def get(self, text: str) -> np.ndarray:
        """Get embedding for text, using cache if available.
        
        Args:
            text: Text to encode
            
        Returns:
            Embedding as numpy array (float32)
        """
        text_lower = text.lower().strip()
        if not text_lower:
            return np.array([], dtype=np.float32)
        
        # Check cache first
        with sqlite3.connect(self.cache_db) as conn:
            cursor = conn.execute(
                "SELECT embedding FROM embeddings WHERE text = ?",
                (text_lower,)
            )
            row = cursor.fetchone()
            
            if row:
                return np.frombuffer(row[0], dtype=np.float32)
        
        # Generate new embedding
        embedding = self.model.encode(text_lower, normalize_embeddings=True)
        embedding = np.array(embedding, dtype=np.float32)
        
        # Cache it
        with sqlite3.connect(self.cache_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO embeddings (text, embedding) VALUES (?, ?)",
                (text_lower, embedding.tobytes())
            )
        
        return embedding
    
    def clear_cache(self) -> int:
        """Clear the embedding cache.
        
        Returns:
            Number of entries deleted
        """
        with sqlite3.connect(self.cache_db) as conn:
            cursor = conn.execute("DELETE FROM embeddings")
            conn.commit()
            return cursor.rowcount
