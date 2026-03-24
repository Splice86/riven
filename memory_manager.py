"""
Memory Manager - Client for the Memories API.

Provides a clean Python interface to interact with the memory system.
"""

import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, Protocol
from dataclasses import dataclass, field
from openai import OpenAI


@dataclass
class Memory:
    """Represents a memory entry."""
    id: int
    content: str
    keywords: list[str]
    properties: dict[str, Any]
    created_at: str
    updated_at: str
    
    @property
    def node_type(self) -> str:
        """Get the node type from properties."""
        return self.properties.get("node_type", "memory")
    
    @property
    def temporal_location(self) -> str:
        """Get the temporal location from properties or created_at."""
        return self.properties.get("temporal_location") or self.created_at
    
    @classmethod
    def from_dict(cls, data: dict) -> "Memory":
        return cls(
            id=data["id"],
            content=data["content"],
            keywords=data.get("keywords", []),
            properties=data.get("properties", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", "")
        )


@dataclass
class MemoryRef:
    """Lightweight reference to a memory (returned on create)."""
    id: int
    content: str


@dataclass
class SearchResult:
    """Search results container."""
    memories: list[Memory]
    count: int


@dataclass
class MemoryCluster:
    """A temporal cluster of memories."""
    memory_ids: list[int] = field(default_factory=list)
    memories: list[Memory] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    
    @property
    def size(self) -> int:
        return len(self.memory_ids)


class LLMSummarizer:
    """LLM client for summarization."""
    
    DEFAULT_URL = "http://192.168.1.11:8010"
    DEFAULT_MODEL = "llama3"
    DEFAULT_API_KEY = "sk-dummy"
    
    def __init__(
        self,
        llm_url: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.llm_url = llm_url or os.environ.get("LLM_URL", self.DEFAULT_URL)
        self.llm_api_key = llm_api_key or os.environ.get("LLM_API_KEY", self.DEFAULT_API_KEY)
        self.model = model or os.environ.get("LLM_MODEL", self.DEFAULT_MODEL)
        
        self.client = OpenAI(base_url=f"{self.llm_url}/v1", api_key=self.llm_api_key)
    
    def summarize(self, text: str) -> str:
        """Summarize text using the LLM."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that summarizes text concisely."
                },
                {
                    "role": "user",
                    "content": f"Summarize the following text in 1-2 sentences:\n\n{text}"
                }
            ],
            temperature=0.3
        )
        return response.choices[0].message.content


class MemoryManager:
    """
    Client for interacting with the Memories API.
    
    Usage:
        manager = MemoryManager()
        manager.add("My memory", keywords=["tag1", "tag2"])
        results = manager.search("k:tag1")
    """
    
    DEFAULT_URL = "http://192.168.1.11:8030"
    DEFAULT_TIMEOUT = 10  # seconds
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        llm_url: Optional[str] = None,
        llm_api_key: Optional[str] = None,
        llm_model: Optional[str] = None
    ):
        self.base_url = base_url or os.environ.get("MEMORY_API_URL", self.DEFAULT_URL)
        self._setup_session()
        
        # Optional LLM for summarization
        self.summarizer = LLMSummarizer(llm_url, llm_api_key, llm_model)
    
    def _setup_session(self) -> None:
        """Configure session with retry logic and timeouts."""
        self.session = requests.Session()
        
        # Retry strategy: 3 retries with exponential backoff
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "DELETE"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    # --- Core Operations ---
    
    def add(
        self,
        content: str,
        keywords: Optional[list[str]] = None,
        properties: Optional[dict[str, Any]] = None,
        created_at: Optional[str] = None,
        node_type: str = "memory"
    ) -> MemoryRef:
        """
        Add a new memory.
        
        All memories automatically get:
        - node_type: "memory" (or custom type like "cluster")
        - temporal_location: defaults to created_at
        
        Args:
            content: The memory text content
            keywords: List of keyword tags
            properties: Dict of custom properties
            created_at: Optional ISO timestamp (defaults to now)
            node_type: Type of node ("memory", "cluster", etc.)
            
        Returns:
            MemoryRef with id and content
        """
        # Default timestamp to now
        if not created_at:
            created_at = datetime.now(timezone.utc).isoformat()
        
        # Build properties with defaults
        props = properties or {}
        props["node_type"] = node_type
        props["temporal_location"] = props.get("temporal_location", created_at)
            
        payload = {
            "content": content,
            "created_at": created_at,
            "properties": props
        }
        if keywords:
            payload["keywords"] = keywords
            
        response = self.session.post(f"{self.base_url}/memories", json=payload, timeout=self.DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return MemoryRef(id=data["id"], content=data["content"])
    
    def get(self, memory_id: int) -> Memory:
        """Get a memory by ID."""
        response = self.session.get(f"{self.base_url}/memories/{memory_id}", timeout=self.DEFAULT_TIMEOUT)
        response.raise_for_status()
        return Memory.from_dict(response.json())
    
    def delete(self, memory_id: int) -> bool:
        """Delete a memory by ID."""
        response = self.session.delete(f"{self.base_url}/memories/{memory_id}", timeout=self.DEFAULT_TIMEOUT)
        response.raise_for_status()
        return True
    
    def count(self) -> int:
        """Get total memory count."""
        response = self.session.get(f"{self.base_url}/stats", timeout=self.DEFAULT_TIMEOUT)
        response.raise_for_status()
        return response.json().get("count", 0)
    
    # --- Search ---
    
    def search(self, query: str = "", limit: int = 50) -> SearchResult:
        """Search memories using the query syntax."""
        payload = {"query": query, "limit": limit}
        response = self.session.post(f"{self.base_url}/memories/search", json=payload, timeout=self.DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        return SearchResult(
            memories=[Memory.from_dict(m) for m in data.get("memories", [])],
            count=data.get("count", 0)
        )
    
    # --- Links ---
    
    def add_link(self, source_id: int, target_id: int, link_type: str = "related_to") -> dict:
        """Add a link between two memories."""
        payload = {"source_id": source_id, "target_id": target_id, "link_type": link_type}
        response = self.session.post(f"{self.base_url}/memories/link", json=payload, timeout=self.DEFAULT_TIMEOUT)
        response.raise_for_status()
        return response.json()
    
    # --- Convenience Methods ---
    
    def get_by_keyword(self, keyword: str) -> list[Memory]:
        """Get all memories with a specific keyword."""
        result = self.search(f"k:{keyword}")
        return result.memories
    
    def get_by_property(self, key: str, value: Any) -> list[Memory]:
        """Get all memories with a specific property value."""
        result = self.search(f"p:{key}={value}")
        return result.memories
    
    def get_clusters(self) -> list[Memory]:
        """Get all cluster nodes."""
        return self.get_by_property("node_type", "cluster")
    
    def list_all(self, limit: int = 100) -> list[Memory]:
        """List all memories."""
        result = self.search("", limit=limit)
        return result.memories
    
    # --- Temporal Clustering ---
    
    def get_temporal_clusters(
        self,
        gap_minutes: int = 30,
        exclude_recent_minutes: int = 60,
        exclude_summarized: bool = True
    ) -> list[MemoryCluster]:
        """
        Cluster memories by temporal proximity.
        
        Memories within `gap_minutes` of each other are grouped into the same cluster.
        Clusters within `exclude_recent_minutes` of now are excluded (active session).
        
        Args:
            gap_minutes: Time gap to start a new cluster (default: 30 min)
            exclude_recent_minutes: How recent a cluster can be to be included (default: 60 min)
            exclude_summarized: Skip clusters where all memories already have summaries (default: True)
            
        Returns:
            List of MemoryCluster objects (excluding recent/active clusters)
        """
        all_memories = self.list_all(limit=10000)
        
        if not all_memories:
            return []
        
        # Build set of already-summarized memory IDs
        summarized_ids: set[int] = set()
        if exclude_summarized:
            # For each memory, check if it already has a summary linked to it
            for memory in all_memories:
                result = self.search(f"l:summary_of:{memory.id}", limit=1)
                if result.count > 0:
                    summarized_ids.add(memory.id)
        
        # Sort by created_at
        sorted_memories = sorted(all_memories, key=lambda m: m.created_at)
        
        clusters: list[MemoryCluster] = []
        current_cluster = MemoryCluster()
        
        now = datetime.now(timezone.utc)
        exclude_threshold = now - timedelta(minutes=exclude_recent_minutes)
        
        for memory in sorted_memories:
            memory_time = datetime.fromisoformat(memory.created_at.replace('Z', '+00:00'))
            
            # Check if this memory is too recent (active session)
            if memory_time > exclude_threshold:
                continue  # Skip recent memories
            
            # Skip if already summarized
            if exclude_summarized and memory.id in summarized_ids:
                continue
            
            # Start new cluster if empty
            if not current_cluster.memory_ids:
                current_cluster.start_time = memory.created_at
            
            # Check time gap from last memory in cluster
            if current_cluster.memory_ids:
                last_memory = current_cluster.memories[-1]
                last_time = datetime.fromisoformat(last_memory.created_at.replace('Z', '+00:00'))
                gap = (memory_time - last_time).total_seconds() / 60
                
                if gap > gap_minutes:
                    # Close current cluster and start new one
                    current_cluster.end_time = last_memory.created_at
                    clusters.append(current_cluster)
                    current_cluster = MemoryCluster()
                    current_cluster.start_time = memory.created_at
            
            # Add to current cluster
            current_cluster.memory_ids.append(memory.id)
            current_cluster.memories.append(memory)
        
        # Don't forget the last cluster (but it may be recent, so check)
        if current_cluster.memory_ids:
            last_time_str = current_cluster.memories[-1].created_at
            last_time = datetime.fromisoformat(last_time_str.replace('Z', '+00:00'))
            if last_time <= exclude_threshold:
                current_cluster.end_time = last_time_str
                clusters.append(current_cluster)
        
        return clusters
    
    def summarize_recent_clusters(
        self,
        gap_minutes: int = 30,
        exclude_recent_minutes: int = 60,
        min_cluster_size: int = 2
    ) -> list[MemoryRef]:
        """
        Find and summarize all closed temporal clusters.
        
        Args:
            gap_minutes: Time gap to start a new cluster
            exclude_recent_minutes: How recent a cluster can be
            min_cluster_size: Minimum memories in a cluster to summarize
            
        Returns:
            List of MemoryRef for created summaries
        """
        clusters = self.get_temporal_clusters(gap_minutes, exclude_recent_minutes)
        
        summaries = []
        for cluster in clusters:
            if cluster.size >= min_cluster_size:
                print(f"Summarizing cluster: {cluster.size} memories from {cluster.start_time[:19]} to {cluster.end_time[:19]}")
                summary = self.summarize_memories(
                    cluster.memory_ids,
                    keywords=["temporal_summary", "cluster"]
                )
                summaries.append(summary)
        
        return summaries
    
    # --- Summarization ---
    
    def summarize_memory(self, memory_id: int, keywords: Optional[list[str]] = None) -> MemoryRef:
        """
        Summarize a memory and add as a linked summary.
        
        Args:
            memory_id: ID of the memory to summarize
            keywords: Optional keywords for the summary
            
        Returns:
            MemoryRef for the new summary memory
        """
        memory = self.get(memory_id)
        summary_text = self.summarizer.summarize(memory.content)
        
        # Add summary linked to original
        summary = self.add(
            summary_text,
            keywords=keywords or ["summary"],
            properties={"is_summary": "true", "summarized_from": str(memory_id)}
        )
        
        # Link summary to original
        self.add_link(summary.id, memory_id, "summary_of")
        
        return summary
    
    def summarize_memories(self, memory_ids: list[int], keywords: Optional[list[str]] = None) -> MemoryRef:
        """
        Summarize multiple memories into one summary.
        
        Args:
            memory_ids: List of memory IDs to summarize
            keywords: Optional keywords for the summary
            
        Returns:
            MemoryRef for the new summary memory
        """
        memories = [self.get(mid) for mid in memory_ids]
        combined_content = "\n\n".join(m.content for m in memories)
        
        summary_text = self.summarizer.summarize(combined_content)
        
        summary = self.add(
            summary_text,
            keywords=keywords or ["summary"],
            properties={"is_summary": "true", "summarized_count": str(len(memory_ids))}
        )
        
        # Link to all original memories
        for memory_id in memory_ids:
            self.add_link(summary.id, memory_id, "summary_of")
        
        return summary


def check_api_health(manager: MemoryManager) -> bool:
    """Check if the memory API is running."""
    try:
        manager.count()
        return True
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False


def check_llm_health(manager: MemoryManager) -> bool:
    """Check if the LLM API is running."""
    try:
        manager.summarizer.summarize("test")
        return True
    except Exception:
        return False


def create_test_memories(manager: MemoryManager) -> dict:
    """Create test memories in 3 topic groups with temporal spacing."""
    from datetime import datetime, timezone, timedelta
    
    now = datetime.now(timezone.utc)
    created_ids = {}
    
    # Group 1: Pets (memories from 2 hours ago)
    pets_base = now - timedelta(hours=2)
    pets = [
        ("My dog Max loves to chase squirrels in the backyard every morning.", ["pets", "dog", "max"]),
        ("I adopted a rescue cat named Luna last month. She's very shy but warming up.", ["pets", "cat", "luna"]),
        ("Max and Luna don't get along yet. They mostly ignore each other.", ["pets", "dog", "cat", "max", "luna"]),
    ]
    pets_ids = []
    for i, (content, keywords) in enumerate(pets):
        m = manager.add(content, keywords=keywords, created_at=(pets_base + timedelta(minutes=i*10)).isoformat())
        pets_ids.append(m.id)
    created_ids["pets"] = pets_ids
    
    # Group 2: Gig work (memories from 1.5 hours ago)
    gig_base = now - timedelta(hours=1.5)
    gig_work = [
        ("Did 5 Uber rides today. Made about $85 after expenses.", ["gig", "uber", "rides"]),
        ("Delivered groceries for Instacart. Tips were good this week, $120 total.", ["gig", "instacart", "delivery"]),
        ("Signed up for DoorDash. Need to complete 20 deliveries for the bonus.", ["gig", "doordash", "bonus"]),
        ("My car needs an oil change. Been putting it off while doing gig work.", ["gig", "car", "maintenance"]),
    ]
    gig_ids = []
    for i, (content, keywords) in enumerate(gig_work):
        m = manager.add(content, keywords=keywords, created_at=(gig_base + timedelta(minutes=i*8)).isoformat())
        gig_ids.append(m.id)
    created_ids["gig"] = gig_ids
    
    # Group 3: Technical (memories from 1 hour ago)
    tech_base = now - timedelta(hours=1)
    technical = [
        ("Fixed a memory leak in the Python agent. Was caused by unclosed database connections.", ["technical", "python", "debugging"]),
        ("Refactored the API endpoints to use async/await properly. Performance improved 3x.", ["technical", "api", "performance"]),
        ("Added a new feature to the memory search - temporal clustering by time gaps.", ["technical", "feature", "memory"]),
    ]
    tech_ids = []
    for i, (content, keywords) in enumerate(technical):
        m = manager.add(content, keywords=keywords, created_at=(tech_base + timedelta(minutes=i*12)).isoformat())
        tech_ids.append(m.id)
    created_ids["technical"] = tech_ids
    
    return created_ids


def run_tests():
    """Run temporal clustering test with 3 topic groups."""
    print("=" * 60)
    print("Memory Manager Temporal Clustering Test")
    print("=" * 60)
    
    # Check API availability
    print("\n[1/4] Checking API availability...")
    manager = MemoryManager()
    
    if not check_api_health(manager):
        print("\n❌ ERROR: Memory API is not running!")
        print("   Please start the memory API first:")
        print("   cd memory/ && python api.py")
        return False
    
    if not check_llm_health(manager):
        print("\n❌ ERROR: LLM API is not running!")
        print("   Please start the LLM server first:")
        print("   e.g., llama.cpp server on port 8010")
        return False
    
    print("   ✓ Memory API is running")
    print("   ✓ LLM API is running")
    
    # Get initial count
    initial_count = manager.count()
    print(f"\n   Initial memory count: {initial_count}")
    
    # Create test memories
    print("\n[2/4] Creating test memories in 3 topic groups...")
    created_ids = create_test_memories(manager)
    
    print(f"   ✓ Created memories:")
    for topic, ids in created_ids.items():
        print(f"      {topic}: {len(ids)} memories (IDs: {ids})")
    
    # Get temporal clusters
    print("\n[3/4] Testing temporal clustering...")
    clusters = manager.get_temporal_clusters(
        gap_minutes=30,
        exclude_recent_minutes=30,  # Exclude memories from last 30 min
        exclude_summarized=False
    )
    
    print(f"   ✓ Found {len(clusters)} temporal clusters:")
    for i, c in enumerate(clusters):
        print(f"      Cluster {i+1}: {c.size} memories")
        print(f"         Time range: {c.start_time[:19]} to {c.end_time[:19]}")
        # Show keywords from this cluster
        all_kw = set()
        for m in c.memories:
            all_kw.update(m.keywords)
        print(f"         Keywords: {sorted(all_kw)}")
    
    # Summarize clusters
    print("\n[4/4] Summarizing clusters...")
    summaries = manager.summarize_recent_clusters(
        gap_minutes=30,
        exclude_recent_minutes=30,
        min_cluster_size=2
    )
    
    print(f"   ✓ Created {len(summaries)} summaries")
    for s in summaries:
        sm = manager.get(s.id)
        print(f"      Summary #{s.id}: {sm.content[:80]}...")
    
    # Verify exclude_summarized works
    clusters_after = manager.get_temporal_clusters(
        gap_minutes=30,
        exclude_recent_minutes=30,
        exclude_summarized=True
    )
    print(f"\n   ✓ After summarization: {len(clusters_after)} clusters (should be fewer)")
    
    # Cleanup
    print("\n--- Cleaning up ---")
    all_ids = []
    for ids in created_ids.values():
        all_ids.extend(ids)
    for mid in all_ids:
        manager.delete(mid)
    
    for s in summaries:
        manager.delete(s.id)
    
    final_count = manager.count()
    print(f"   ✓ Deleted {len(all_ids) + len(summaries)} test memories")
    print(f"   ✓ Final count: {final_count} (should be {initial_count})")
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = run_tests()
    if not success:
        exit(1)
