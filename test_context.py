"""Test script for context memory clustering."""

import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/home/david/Projects/riven')

# Try to use config
try:
    from config import MEMORY_API_URL
except ImportError:
    MEMORY_API_URL = "http://127.0.0.1:8030"

from context import ActivityLog
from memory_manager import MemoryManager


def test_context_clustering():
    """Test that context messages get clustered and summarized."""
    
    db_name = f"test_{int(time.time())}"
    print(f"Using test DB: {db_name}")
    print(f"API: {MEMORY_API_URL}")
    print("=" * 60)
    
    log = ActivityLog(
        max_messages=10,
        keep_recent=3,
        db_name=db_name
    )
    
    # Session 1: 2 hours ago (should form a cluster)
    base_time = datetime.now(timezone.utc) - timedelta(hours=2)
    print("\n[1] Session 1 (2 hours ago)...")
    for i in range(3):
        ts = (base_time + timedelta(minutes=i*5)).isoformat()
        log.add_user(f"User msg {i+1}", created_at=ts)
        log.add_assistant(f"Assistant msg {i+1}", created_at=ts)
    
    # Session 2: now
    print("[2] Session 2 (now)...")
    for i in range(8):
        log.add_user(f"User msg {i+1}")
        log.add_assistant(f"Assistant msg {i+1}")
        time.sleep(0.1)
    
    # Check
    count = log.manager.search("p:node_type=context", limit=100).count
    print(f"\n[3] Context messages: {count}")
    
    # Check clusters
    clusters = log.manager.get_temporal_clusters(
        gap_minutes=30,
        exclude_recent_minutes=30,
        query_filter="p:node_type=context"
    )
    print(f"  Clusters: {len(clusters)}")
    
    # Test LLM
    print("\n[4] Testing LLM...")
    try:
        summary = log.manager.summarizer.summarize("Test. Summarize this.")
        print(f"  LLM OK: {summary[:50]}...")
    except Exception as e:
        print(f"  LLM failed: {e}")
    
    # Manual clustering check
    result = log.manager.check_summarization_needed(
        max_messages=10,
        min_cluster_size=2,
        max_gap_minutes=30,
        exclude_recent_minutes=30,
        query_filter="p:node_type=context"
    )
    print(f"\n[5] Summarization needed: {result['needs_summarization']} ({result['reason']})")
    
    if result['clusters']:
        print("[6] Creating summary...")
        for c in result['clusters']:
            try:
                s = log.manager.summarize_memories(c.memory_ids, keywords=["context_summary"])
                print(f"  Created summary #{s.id}")
            except Exception as e:
                print(f"  Skipped (LLM unavailable): {e}")
    
    final_count = log.manager.search("p:node_type=context", limit=100).count
    summary_count = log.manager.search("k:context_summary", limit=100).count
    print(f"\n[7] Final: {final_count} context, {summary_count} summaries")
    print("=" * 60)


if __name__ == "__main__":
    print("Context Clustering Test")
    print("=" * 60)
    
    try:
        test_db = MemoryManager(db_name="healthcheck", base_url=MEMORY_API_URL)
        test_db.count()
        print(f"API OK: {MEMORY_API_URL}\n")
    except Exception as e:
        print(f"ERROR: API not at {MEMORY_API_URL}")
        sys.exit(1)
    
    test_context_clustering()
