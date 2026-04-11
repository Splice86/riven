#!/usr/bin/env python3
"""Test script for temporal clustering functionality."""

import requests
import json
import time
from datetime import datetime, timedelta, timezone

BASE_URL = "http://100.90.58.38:8030"

def create_session():
    """Create a new session."""
    resp = requests.post(f"{BASE_URL}/session/new", params={"name": "riven"})
    return resp.json()["session"]

def add_memory(role: str, content: str, session: str, created_at: str = None):
    """Add a memory with optional custom timestamp."""
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    
    resp = requests.post(
        f"{BASE_URL}/context",
        params={"name": "riven"},
        json={"role": role, "content": content, "session": session, "created_at": created_at}
    )
    return resp.json()

def get_context(session: str):
    """Get context for a session."""
    resp = requests.get(f"{BASE_URL}/context", params={"name": "riven", "session": session})
    return resp.json()

def search_memories(session: str, query: str = None):
    """Search memories."""
    if query is None:
        query = f"p:session={session}"
    resp = requests.post(f"{BASE_URL}/memories/search", params={"name": "riven"}, json={"query": query})
    return resp.json()["memories"]

def cluster(target_tokens: int, min_live: int, max_gap: int, level: int, session: str):
    """Run clustering."""
    resp = requests.post(
        f"{BASE_URL}/context/cluster",
        params={"name": "riven", "target_tokens": target_tokens, "min_live_tokens": min_live, "max_gap": max_gap, "level": level, "session": session}
    )
    return resp.json()

def print_separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def test_basic_clustering():
    """Test basic clustering with time gaps."""
    print_separator("Test 1: Basic Clustering with Time Gaps")
    
    session = create_session()
    print(f"Session: {session}")
    
    base_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    
    # Add 8 memories with two distinct time groups (4 each)
    # This ensures we can create 2 groups and test properly
    memories = [
        ("user", "Message 1 about Python", base_time),
        ("assistant", "Message 2: Python is great for AI", base_time + timedelta(seconds=5)),
        ("user", "Message 3 learning ML basics", base_time + timedelta(seconds=10)),
        ("assistant", "Message 4 neural networks intro", base_time + timedelta(seconds=15)),
        # Gap here - 60 seconds
        ("user", "Message 5 deep learning concepts", base_time + timedelta(seconds=75)),
        ("assistant", "Message 6 about transformers", base_time + timedelta(seconds=80)),
        ("user", "Message 7 attention mechanisms", base_time + timedelta(seconds=85)),
        ("assistant", "Message 8 BERT and GPT models", base_time + timedelta(seconds=90)),
    ]
    
    for role, content, ts in memories:
        add_memory(role, content, session, ts.isoformat())
    
    print(f"\nAdded {len(memories)} messages in 2 time groups")
    print("  Group 1 (0-15s): msg1-msg4")
    print("  Gap: 60s")
    print("  Group 2 (75-90s): msg5-msg8")
    
    # Check before clustering
    ctx = get_context(session)
    print(f"\nBefore cluster: {ctx['count']} messages")
    
    # Cluster with max_gap=30 (should separate into 2 groups)
    print("\n--- Clustering (target=30, min=15, max_gap=30, level=1) ---")
    result = cluster(30, 15, 30, 1, session)
    print(f"Result: {result}")
    
    # Check after
    ctx = get_context(session)
    print(f"\nAfter cluster: {ctx['count']} items")
    
    # Check all memories
    all_mems = search_memories(session)
    summaries = [m for m in all_mems if m.get('properties', {}).get('summary_level') == '1']
    print(f"\nTotal summaries created: {len(summaries)} (should be 2)")
    for m in all_mems:
        props = m.get('properties', {})
        level = props.get('summary_level', 'live')
        was = props.get('was_summarized', '')
        print(f"  id={m['id']} level={level} was_sum={was} content={m['content'][:30]}")

def test_multi_level_clustering():
    """Test hierarchical clustering (summaries of summaries)."""
    print_separator("Test 2: Multi-Level Clustering")
    
    session = create_session()
    print(f"Session: {session}")
    
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Add 12 messages in 4 time groups (3 each)
    # This should create 4 level-1 summaries
    for i in range(12):
        ts = base_time + timedelta(seconds=i*10 + (i//3)*60)  # 4 groups of 3
        add_memory("user", f"Message {i+1} content here for testing", session, ts.isoformat())
    
    print("Added 12 messages in 4 time groups (3 each)")
    
    # First level clustering - should create 4 summaries
    print("\n--- Level 1 Clustering ---")
    result = cluster(40, 20, 30, 1, session)
    print(f"Level 1 result: {result}")
    
    ctx = get_context(session)
    print(f"After level 1: {ctx['count']} items")
    
    # Check levels
    all_mems = search_memories(session)
    level1_summaries = [m for m in all_mems if m.get('properties', {}).get('summary_level') == '1']
    print(f"Level 1 summaries: {len(level1_summaries)} (should be 4)")
    
    # Second level clustering - should cluster the 4 summaries into 1
    print("\n--- Level 2 Clustering (summaries of summaries) ---")
    result = cluster(30, 10, 30, 2, session)
    print(f"Level 2 result: {result}")
    
    ctx = get_context(session)
    print(f"After level 2: {ctx['count']} items")
    
    all_mems = search_memories(session)
    level2_summaries = [m for m in all_mems if m.get('properties', {}).get('summary_level') == '2']
    print(f"Level 2 summaries: {len(level2_summaries)} (should be 1)")
    
    for m in all_mems:
        props = m.get('properties', {})
        level = props.get('summary_level', 'live')
        was = props.get('was_summarized', '')
        print(f"  id={m['id']} level={level} was_sum={was} content={m['content'][:30]}")

def test_no_double_summarize():
    """Verify messages aren't summarized twice."""
    print_separator("Test 3: No Double Summarization")
    
    session = create_session()
    print(f"Session: {session}")
    
    base_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
    
    # Add 6 messages
    for i in range(6):
        ts = base_time + timedelta(seconds=i*5)
        add_memory("user", f"Message {i+1}", session, ts.isoformat())
    
    # Run clustering twice
    print("\n--- First cluster ---")
    result1 = cluster(20, 10, 30, 1, session)
    print(f"Result: {result1}")
    
    print("\n--- Second cluster (should do nothing) ---")
    result2 = cluster(20, 10, 30, 1, session)
    print(f"Result: {result2}")
    
    all_mems = search_memories(session)
    print(f"\nTotal memories: {len(all_mems)}")
    
    # Count was_summarized
    summarized = sum(1 for m in all_mems if m.get('properties', {}).get('was_summarized') == 'true')
    summaries = [m for m in all_mems if m.get('properties', {}).get('summary_level')]
    
    print(f"Original messages marked was_summarized: {summarized}")
    print(f"Summary memories created: {len(summaries)}")
    
    # Try to summarize again - should not create new summaries
    print("\n--- Third cluster (should not summarize already summarized) ---")
    result3 = cluster(10, 5, 30, 1, session)
    print(f"Result: {result3}")
    
    all_mems_after = search_memories(session)
    print(f"Total after: {len(all_mems_after)} (should be same as before)")

def test_max_gap_different():
    """Test different max_gap values."""
    print_separator("Test 4: Different max_gap Values")
    
    base_time = datetime(2024, 1, 1, 16, 0, 0, tzinfo=timezone.utc)
    
    # Test 1: max_gap=30 with 8 messages in 2 groups
    session = create_session()
    print(f"Session: {session}")
    
    # 4 messages in group 1 (0-15s), 4 in group 2 (60-75s)
    gaps = [0, 5, 10, 15, 60, 65, 70, 75]
    for i, gap in enumerate(gaps):
        ts = base_time + timedelta(seconds=gap)
        add_memory("user", f"Message {i+1} with content", session, ts.isoformat())
    
    print(f"Added 8 messages: gaps {gaps}")
    
    # With max_gap=30 (should make 2 groups = 2 summaries)
    print("\n--- Cluster with max_gap=30 ---")
    result = cluster(25, 12, 30, 1, session)
    print(f"Result: {result}")
    
    all_mems = search_memories(session)
    summaries = [m for m in all_mems if m.get('properties', {}).get('summary_level') == '1']
    print(f"Summaries created: {len(summaries)} (should be 2)")
    
    # Test 2: max_gap=100 (should make 1 group = 1 summary)
    print("\n--- Cluster with max_gap=100 (new session) ---")
    session2 = create_session()
    for i, gap in enumerate(gaps):
        ts = base_time + timedelta(seconds=gap)
        add_memory("user", f"Message {i+1} with content", session2, ts.isoformat())
    
    result = cluster(25, 12, 100, 1, session2)
    print(f"Result: {result}")
    
    all_mems2 = search_memories(session2)
    summaries2 = [m for m in all_mems2 if m.get('properties', {}).get('summary_level') == '1']
    print(f"Summaries created: {len(summaries2)} (should be 1)")

def test_large_context():
    """Test with 20+ memories."""
    print_separator("Test 5: Large Context (30 Messages)")
    
    session = create_session()
    print(f"Session: {session}")
    
    base_time = datetime(2024, 1, 1, 18, 0, 0, tzinfo=timezone.utc)
    
    # Add 30 messages in 6 time groups (5 each)
    for i in range(30):
        group_gap = (i // 5) * 60  # 60s between groups
        ts = base_time + timedelta(seconds=(i * 5) + group_gap)
        add_memory("user", f"Message {i+1} with some content to make tokens", session, ts.isoformat())
    
    print("Added 30 messages in 6 groups of 5")
    
    ctx = get_context(session)
    print(f"Before cluster: {ctx['count']} messages")
    
    # Cluster to reduce significantly - should create multiple summaries
    print("\n--- Cluster (target=40, min=15, max_gap=30) ---")
    result = cluster(40, 15, 30, 1, session)
    print(f"Result: {result}")
    
    ctx = get_context(session)
    print(f"After cluster: {ctx['count']} items")
    
    # Check level distribution
    all_mems = search_memories(session)
    by_level = {}
    for m in all_mems:
        level = m.get('properties', {}).get('summary_level', 'live')
        by_level[level] = by_level.get(level, 0) + 1
    
    print(f"Distribution: {by_level}")
    
    level1 = [m for m in all_mems if m.get('properties', {}).get('summary_level') == '1']
    print(f"Level 1 summaries: {len(level1)} (should be ~5)")

def main():
    print("Testing Temporal Clustering Functionality")
    print(f"Base URL: {BASE_URL}")
    
    # Check API is up
    try:
        resp = requests.get(f"{BASE_URL}/db/list")
        print(f"API Status: OK")
    except Exception as e:
        print(f"API Error: {e}")
        return
    
    test_basic_clustering()
    test_multi_level_clustering()
    test_no_double_summarize()
    test_max_gap_different()
    test_large_context()
    
    print_separator("All Tests Complete!")

if __name__ == "__main__":
    main()