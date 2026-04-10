"""
Context management for the Memory API.

Single Context class that handles:
- add(): adds context messages, auto-summarizes if needed
- get(): returns summary + unsummarized turns for LLM
"""

import os
from datetime import datetime, timezone
from typing import Optional

# Try to import tiktoken for token counting
try:
    import tiktoken
    tiktoken_available = True
except ImportError:
    tiktoken_available = False

# Try to import OpenAI for LLM calls
try:
    from openai import OpenAI
    openai_available = True
except ImportError:
    openai_available = False


# ============================================================================
# Config
# ============================================================================

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8000/v1/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-dummy")
LLM_MODEL = os.environ.get("LLM_MODEL", "nvidia/MiniMax-M2.5-NVFP4")

MAX_TOKENS_DEFAULT = 32000
MIN_CLUSTER_SIZE = 3


# ============================================================================
# Token Counting
# ============================================================================

def count_tokens(text: str) -> int:
    """Count tokens using tiktoken, fallback to rough estimate."""
    if not text:
        return 0
    
    if tiktoken_available:
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            pass
    
    return len(text) // 4


def count_message_tokens(role: str, content: str) -> int:
    """Count tokens for a message including overhead."""
    return count_tokens(content) + 4


# ============================================================================
# LLM Client
# ============================================================================

class SummarizerLLM:
    """LLM client for generating summaries."""
    
    def __init__(
        self,
        llm_url: str = LLM_URL,
        llm_api_key: str = LLM_API_KEY,
        model: str = LLM_MODEL
    ):
        self.llm_url = llm_url
        self.llm_api_key = llm_api_key
        self.model = model
        
        if openai_available:
            self.client = OpenAI(base_url=f"{self.llm_url}/v1", api_key=self.llm_api_key)
        else:
            self.client = None
    
    def summarize(self, text: str) -> str:
        """Summarize text using the LLM."""
        if not self.client:
            return f"[Summary of {len(text)} chars]"
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that summarizes text concisely."
                    },
                    {
                        "role": "user",
                        "content": f"Summarize the following in 1-2 paragraphs:\n\n{text}"
                    }
                ],
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"[Summary failed: {e}]"
    
    def health_check(self) -> bool:
        """Check if LLM is available."""
        if not self.client:
            return False
        try:
            self.summarize("test")
            return True
        except Exception:
            return False


# ============================================================================
# Context
# ============================================================================

class Context:
    """
    Handles adding and retrieving context for the LLM.
    
    - add(): adds a context message, auto-summarizes if needed
    - get(): returns summary + unsummarized turns for LLM context
    """
    
    VALID_ROLES = {"user", "assistant", "system", "tool"}
    
    def __init__(self, db, max_tokens: int = MAX_TOKENS_DEFAULT, min_cluster_size: int = MIN_CLUSTER_SIZE):
        self.db = db
        self.max_tokens = max_tokens
        self.min_cluster_size = min_cluster_size
    
    def add(self, role: str, text: str, created_at: str = None) -> dict:
        """
        Add a context message.
        
        Automatically checks and runs summarization if needed.
        
        Args:
            role: Message role (user, assistant, system, tool)
            text: Message content
            created_at: Optional timestamp (ISO format)
            
        Returns:
            Dict with id, role, token_count, created_at, and summarization result
        """
        if role not in self.VALID_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {self.VALID_ROLES}")
        
        if not created_at:
            created_at = datetime.now(timezone.utc).isoformat()
        
        token_count = count_message_tokens(role, text)
        
        memory_id = self.db.add_memory(
            content=text,
            keywords=["context", role],
            properties={
                "role": role,
                "node_type": "context",
                "token_count": str(token_count)
            },
            created_at=created_at
        )
        
        # Check if summarization is needed
        summary_result = self._maybe_summarize()
        
        return {
            "id": memory_id,
            "role": role,
            "token_count": token_count,
            "created_at": created_at,
            "summarized": summary_result.get("summarized", False),
            "summary_id": summary_result.get("summary_id"),
            "memories_summarized": summary_result.get("memories_summarized", 0)
        }
    
    def get(self, limit: int = 100) -> list[dict]:
        """
        Get context for LLM: summary first, then unsummarized turns.
        
        Returns:
            List of memory dicts with id, role, content, created_at
        """
        # Get last summary
        summary = self._get_last_summary()
        
        # Get unsummarized
        unsummarized = self._get_unsummarized(limit)
        
        # Build context: summary first, then unsummarized
        context = []
        
        if summary:
            context.append({
                "id": summary["id"],
                "role": "summary",
                "content": summary["content"],
                "created_at": summary["created_at"]
            })
        
        for mem in unsummarized:
            context.append({
                "id": mem["id"],
                "role": mem["role"],
                "content": mem["content"],
                "created_at": mem["created_at"]
            })
        
        return context
    
    def get_token_count(self) -> int:
        """Get total tokens in unsummarized context."""
        results = self.db.search("k:context", limit=10000)
        
        total = 0
        for mem in results:
            props = mem.get("properties", {})
            if props.get("was_summarized") == "true":
                continue
            
            token_count = props.get("token_count", "0")
            try:
                total += int(token_count)
            except ValueError:
                total += count_tokens(mem.get("content", ""))
        
        return total
    
    def _maybe_summarize(self) -> dict:
        """Check token count and summarize if needed."""
        results = self.db.search("k:context", limit=10000)
        
        unsummarized = []
        for mem in results:
            props = mem.get("properties", {})
            if props.get("was_summarized") == "true":
                continue
            
            token_count = props.get("token_count", "0")
            try:
                token_count = int(token_count)
            except ValueError:
                token_count = count_tokens(mem.get("content", ""))
            
            unsummarized.append({
                "id": mem["id"],
                "content": mem["content"],
                "created_at": mem["created_at"],
                "token_count": token_count
            })
        
        if len(unsummarized) < self.min_cluster_size:
            return {"summarized": False}
        
        total_tokens = sum(m["token_count"] for m in unsummarized)
        
        if total_tokens <= self.max_tokens:
            return {"summarized": False}
        
        return self._summarize(unsummarized)
    
    def _summarize(self, memories: list[dict]) -> dict:
        """Summarize the given memories."""
        if not memories:
            return {"summarized": False}
        
        combined = "\n\n".join(m["content"] for m in memories)
        llm = SummarizerLLM()
        summary_text = llm.summarize(combined)
        
        total_tokens = sum(m["token_count"] for m in memories)
        created_at = datetime.now(timezone.utc).isoformat()
        
        summary_id = self.db.add_memory(
            content=summary_text,
            keywords=["context", "summary"],
            properties={
                "is_summary": "true",
                "summarized_count": str(len(memories)),
                "summarized_tokens": str(total_tokens)
            },
            created_at=created_at
        )
        
        for memory in memories:
            self.db.update_memory(
                memory["id"],
                properties={"was_summarized": "true"}
            )
            self.db.add_link(summary_id, memory["id"], "summary_of")
        
        return {
            "summarized": True,
            "summary_id": summary_id,
            "memories_summarized": len(memories)
        }
    
    def _get_last_summary(self) -> Optional[dict]:
        """Get the most recent summary memory."""
        results = self.db.search("k:summary", limit=10)
        
        if not results:
            return None
        
        # Sort by created_at desc to get most recent
        results.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        return results[0]
    
    def _get_unsummarized(self, limit: int) -> list[dict]:
        """Get unsummarized context memories."""
        results = self.db.search("k:context", limit=10000)
        
        unsummarized = []
        for mem in results:
            props = mem.get("properties", {})
            if props.get("was_summarized") == "true":
                continue
            
            unsummarized.append({
                "id": mem["id"],
                "role": props.get("role", "unknown"),
                "content": mem["content"],
                "created_at": mem["created_at"]
            })
        
        unsummarized.sort(key=lambda m: m["created_at"])
        return unsummarized[-limit:]


# Example usage:
# from context import Context
#
# ctx = Context(db)
# ctx.add("user", "Hello!")
# ctx.add("assistant", "Hi there!")
#
# # Get context for LLM (summary + unsummarized turns)
# context = ctx.get()