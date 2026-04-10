"""Context system for agent conversations - memory-backed."""

import os
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from memory_manager import MemoryManager

# Try to import tiktoken for token counting
try:
    import tiktoken
    tiktoken_available = True
except ImportError:
    tiktoken_available = False


def _load_config() -> dict:
    """Load config from YAML file.
    
    Priority: config_local.yaml > config.yaml > defaults
    """
    defaults = {
        "memory_api": {"url": "http://127.0.0.1:8030", "db_name": "riven"},
        "llm": {"url": "http://127.0.0.1:8010", "api_key": "sk-dummy", "model": "llama3", "context_window": 128000},
        "context": {
            "max_tokens": 32000,
            "max_messages": 50,
            "cluster_gap_minutes": 30,
            "cluster_exclude_minutes": 30
        },
        "embedding": {"model_size": "27b", "force_cpu": True, "cache_db": "memory/embeddings_cache.db"}
    }
    
    config = defaults.copy()
    
    # Try config.yaml first
    for config_file in ["config_local.yaml", "config.yaml"]:
        if os.path.exists(config_file):
            with open(config_file) as f:
                file_config = yaml.safe_load(f)
                if file_config:
                    # Merge file config into config (file takes priority)
                    for section, values in file_config.items():
                        if section in config:
                            if isinstance(config[section], dict) and isinstance(values, dict):
                                config[section].update(values)
                            else:
                                config[section] = values
                        else:
                            config[section] = values
    
    return config


# Load config once at module import
CONFIG = _load_config()

# Aliases for backwards compatibility / convenience
DEFAULT_DB = CONFIG["memory_api"]["db_name"]
CONTEXT_MAX_TOKENS = CONFIG["context"]["max_tokens"]
CONTEXT_MAX_MESSAGES = CONFIG["context"]["max_messages"]
CONTEXT_CLUSTER_GAP_MINUTES = CONFIG["context"]["cluster_gap_minutes"]
CONTEXT_CLUSTER_EXCLUDE_MINUTES = CONFIG["context"]["cluster_exclude_minutes"]



def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken.
    
    Args:
        text: Text to count tokens for
        model: Tiktoken model to use (cl100k_base is GPT-4/3.5 tokenizer, good enough for estimation)
        
    Returns:
        Token count
    """
    if not tiktoken_available:
        # Fallback: rough estimate (~4 chars per token)
        return len(text) // 4
    
    try:
        encoding = tiktoken.get_encoding(model)
        return len(encoding.encode(text))
    except Exception:
        return len(text) // 4


def count_message_tokens(role: str, content: str) -> int:
    """Count tokens for a message (approximates OpenAI format).
    
    Args:
        role: Message role (user, assistant, system)
        content: Message content
        
    Returns:
        Token count including message formatting overhead
    """
    # ~4 tokens overhead per message (role labels, formatting)
    return count_tokens(content) + 4


@dataclass
class Message:
    """A single message in the conversation."""
    id: int  # Memory ID
    role: str  # "user", "assistant", "system", "tool"
    content: str
    tool_name: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class ActivityLog:
    """Conversation history backed by MemoryManager.
    
    Messages are stored in the memory API with node_type=context.
    When token count exceeds max_tokens, older messages are clustered by
    temporal proximity and summarized using the LLM.
    """
    
    def __init__(
        self,
        max_tokens: int = CONTEXT_MAX_TOKENS,
        max_messages: int = CONTEXT_MAX_MESSAGES,
        memory_manager: Optional[MemoryManager] = None,
        db_name: str = DEFAULT_DB,
        cluster_gap: int = CONTEXT_CLUSTER_GAP_MINUTES,
        cluster_exclude: int = CONTEXT_CLUSTER_EXCLUDE_MINUTES
    ):
        self._max_tokens = max_tokens
        self._max_messages = max_messages
        self._db_name = db_name
        self._manager = memory_manager or MemoryManager(db_name=db_name)
        self._recent_ids: list[int] = []  # Track recent message IDs
        self._cluster_gap = cluster_gap
        self._cluster_exclude = cluster_exclude
    
    @property
    def manager(self) -> MemoryManager:
        """Access the memory manager."""
        return self._manager
    
    def add(self, role: str, content: str, tool_name: str | None = None, created_at: str | None = None) -> int:
        """Add a message to memory.
        
        Args:
            role: Message role (user, assistant, tool, system)
            content: Message content
            tool_name: Optional tool name for tool messages
            created_at: Optional ISO timestamp (for simulating historical messages)
            
        Returns:
            Memory ID of the stored message
        """
        props = {
            "role": role,
            "node_type": "context"
        }
        if tool_name:
            props["tool_name"] = tool_name
        
        result = self._manager.add(
            content=content,
            keywords=["context", role],
            properties=props,
            created_at=created_at
        )
        
        self._recent_ids.append(result.id)
        
        # Check if we need to prune/cluster
        self._maybe_cluster()
        
        return result.id
    
    def add_user(self, content: str, created_at: str | None = None) -> int:
        return self.add("user", content, created_at=created_at)
    
    def add_assistant(self, content: str, created_at: str | None = None) -> int:
        return self.add("assistant", content, created_at=created_at)
    
    def add_tool(self, tool_name: str, content: str, created_at: str | None = None) -> int:
        return self.add("tool", content, tool_name=tool_name, created_at=created_at)
    
    def add_tool_result(self, tool_name: str, content: str, created_at: str | None = None) -> int:
        """Alias for add_tool."""
        return self.add_tool(tool_name, content, created_at=created_at)

    def add_system(self, content: str, created_at: str | None = None) -> int:
        return self.add("system", content, created_at=created_at)
    
    def _get_token_count(self, memories: list) -> int:
        """Get total token count for a list of memories.
        
        Args:
            memories: List of Memory objects
            
        Returns:
            Total token count
        """
        total = 0
        for m in memories:
            total += count_message_tokens(m.properties.get("role", "user"), m.content)
        return total
    
    def _maybe_cluster(self) -> None:
        """Check if we need to summarize old messages.
        
        Logic:
        1. Get all UNSUMMARIZED context messages
        2. Calculate total token count
        3. If over threshold, try temporal clustering
        4. If cluster found, summarize it
        5. Else, reduce time gap until we get a cluster
        6. Mark summarized, repeat until under token threshold
        """
        # Keep summarizing until we're under the threshold
        while True:
            # Get unsummarized context messages
            result = self._manager.search(
                "p:node_type=context AND NOT p:summarized=true",
                limit=10000
            )
            
            # Sort by time
            sorted_memories = sorted(result.memories, key=lambda m: m.created_at)
            total_tokens = self._get_token_count(sorted_memories)
            total_messages = len(sorted_memories)
            
            # If under both thresholds, done
            if total_tokens <= self._max_tokens and total_messages <= self._max_messages:
                return
            
            # If we have too many tokens but very few messages, still summarize
            if total_messages < 3:
                return
            
            print(f"Context at {total_tokens} tokens ({total_messages} msgs), checking for clusters...")
            
            # Try temporal clustering with decreasing time gaps
            memory_ids = None
            
            # Start with the configured gap, shrink until we get a cluster
            gap = self._cluster_gap
            while gap >= 5:
                clusters = self._manager.get_temporal_clusters(
                    gap_minutes=gap,
                    exclude_recent_minutes=self._cluster_exclude,
                    query_filter="p:node_type=context AND NOT p:summarized=true"
                )
                
                # Find a cluster to summarize
                for cluster in clusters:
                    cluster_ids = set(cluster.memory_ids)
                    
                    # Take this cluster
                    memory_ids = list(cluster_ids)
                    break
                
                if memory_ids:
                    break
                gap = gap // 2
            
            # If no temporal cluster found, just take oldest ones
            if not memory_ids:
                memory_ids = [m.id for m in sorted_memories[:min(10, len(sorted_memories))]]
            
            if len(memory_ids) < 3:
                return
            
            # Summarize them
            try:
                summary = self._manager.summarize_memories(
                    memory_ids,
                    keywords=["context_summary"]
                )
                print(f"  Summarized {len(memory_ids)} messages -> summary #{summary.id}")
                
                # Mark original messages as summarized
                for mid in memory_ids:
                    self._manager.update(mid, {"summarized": "true"})
                    
            except Exception as e:
                print(f"  Summarization failed: {e}")
                return  # Don't retry if LLM failed
            
            # Loop will check again and clean up if needed
    
    def get_messages(self, limit: int = 20) -> list[dict]:
        """Get recent UNSUMMARIZED messages for LLM API.
        
        This excludes messages that have been summarized to keep
        the context window focused on recent conversation.
        """
        # Only get unsummarized messages
        result = self._manager.search(
            "p:node_type=context AND NOT p:summarized=true",
            limit=limit
        )
        
        # Sort by created_at ascending for LLM
        memories = sorted(result.memories, key=lambda m: m.created_at)
        
        return [
            {
                "role": m.properties.get("role", "user"),
                "content": m.content
            }
            for m in memories
        ]
    
    def get_summaries(self, limit: int = 10) -> list[dict]:
        """Get conversation summaries.
        
        Returns the summarized versions of older conversation segments.
        """
        result = self._manager.search(
            "k:context_summary",
            limit=limit
        )
        
        # Sort by created_at descending (newest first)
        memories = sorted(result.memories, key=lambda m: m.created_at, reverse=True)
        
        return [
            {
                "content": m.content,
                "created_at": m.created_at
            }
            for m in memories
        ]
    
    def get_history(self, limit: int = 20) -> str:
        """Get recent messages as text for display."""
        messages = self.get_messages(limit)
        return "\n".join([f"{m['role']}: {m['content']}" for m in messages])
    
    def get_context_for_prompt(self) -> str:
        """Get formatted context for system prompt.
        
        Returns recent messages + any relevant long-term memories.
        """
        # Get recent context messages
        recent = self.get_messages(limit=10)
        
        if not recent:
            return "(No conversation history)"
        
        # Format as conversation
        lines = []
        for msg in recent:
            role = msg["role"]
            content = msg["content"][:200]  # Truncate long messages
            lines.append(f"{role}: {content}")
        
        return "\n".join(lines)
    
    def clear(self) -> None:
        """Clear all context messages (use with caution!)."""
        result = self._manager.search("p:node_type=context", limit=10000)
        for memory in result.memories:
            try:
                self._manager.delete(memory.id)
            except Exception:
                pass
        self._recent_ids.clear()


class SystemContext:
    """Dynamic system prompt - the {{tags}} template."""
    
    def __init__(self,prompt: str):
        self._template = prompt

    def apply_tags(self, replacements: list[tuple[str, str]]) -> str:
        """Replace {{tag}} placeholders."""
        prompt = self._template
        for tag, data in replacements:
            prompt = prompt.replace(f"{{{{{tag}}}}}", str(data))
        return prompt

