#!/usr/bin/env python3
"""Tests for MemoryDB vector similarity search.

Run on server with:
    cd memory && python3 test_vector_search.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

TEST_DB = "test_vector.db"


def setup():
    """Create fresh test database with vector support."""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    
    from database import init_db
    init_db(TEST_DB)
    print("✓ Database setup complete with vector support")


def add_test_data():
    """Add test memories with embeddings."""
    from database import MemoryDB
    from embedding import EmbeddingModel
    
    # Initialize vector model
    vector = EmbeddingModel()
    db = MemoryDB(TEST_DB, embedding_model=vector)
    now = datetime.now(timezone.utc)
    
    # Create memories with similar content
    mem1 = db.add_memory(
        "Python asyncio tutorial for async concurrent programming",
        keywords=["python", "asyncio", "async", "concurrency"],
        created_at=(now - timedelta(days=5)).isoformat()
    )
    print(f"  Added memory 1: {mem1} - Python asyncio")
    
    mem2 = db.add_memory(
        "JavaScript async await tutorial for promises and callbacks",
        keywords=["javascript", "async", "promises", "es6"],
        created_at=(now - timedelta(days=3)).isoformat()
    )
    print(f"  Added memory 2: {mem2} - JavaScript async")
    
    mem3 = db.add_memory(
        "Docker container orchestration with Kubernetes and microservices",
        keywords=["docker", "kubernetes", "containers", "devops"],
        created_at=(now - timedelta(days=1)).isoformat()
    )
    print(f"  Added memory 3: {mem3} - Docker/Kubernetes")
    
    mem4 = db.add_memory(
        "FastAPI Python web framework for building APIs with async endpoints",
        keywords=["python", "fastapi", "api", "web"],
        created_at=(now - timedelta(days=2)).isoformat()
    )
    print(f"  Added memory 4: {mem4} - FastAPI")
    
    return {"mem1": mem1, "mem2": mem2, "mem3": mem3, "mem4": mem4}


def test_vector_similarity():
    """Test vector-based similarity search."""
    from database import MemoryDB
    from embedding import EmbeddingModel
    
    vector = EmbeddingModel()
    db = MemoryDB(TEST_DB, embedding_model=vector)
    ids = add_test_data()
    
    print("\n" + "=" * 60)
    print("TESTING VECTOR SIMILARITY SEARCH")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    # Test 1: Similar to "async python programming"
    # Should find mem1 (Python asyncio) and mem4 (FastAPI)
    print("\n--- Similar to 'async python programming' ---")
    results = db.search("q:async python programming")
    print(f"  q:async python programming → {len(results)} results")
    if len(results) >= 2:
        print("  ✓ Found similar memories")
        for r in results:
            print(f"    id={r['id']}: {r['content'][:50]}...")
        passed += 1
    else:
        print(f"  ✗ Expected at least 2, got {len(results)}")
        failed += 1
    
    # Test 2: Similar to "container orchestration"
    # Should find mem3 (Docker/Kubernetes)
    print("\n--- Similar to 'container orchestration' ---")
    results = db.search("q:container orchestration")
    print(f"  q:container orchestration → {len(results)} results")
    if len(results) >= 1:
        print("  ✓ Found similar memories")
        for r in results:
            print(f"    id={r['id']}: {r['content'][:50]}...")
        passed += 1
    else:
        print(f"  ✗ Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 3: Keyword similarity with threshold
    # Should find memories similar to "python" at high threshold
    print("\n--- Similar keywords 'python' at 0.7 threshold ---")
    results = db.search("s:python@0.7")
    print(f"  s:python@0.7 → {len(results)} results")
    if len(results) >= 1:
        print("  ✓ Found similar keywords")
        passed += 1
    else:
        print(f"  ✗ Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 4: Combined keyword and similarity
    print("\n--- Combined keyword and similarity ---")
    results = db.search("k:python AND q:async")
    print(f"  k:python AND q:async → {len(results)} results")
    if len(results) >= 1:
        print("  ✓ Found matching memories")
        passed += 1
    else:
        print(f"  ✗ Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 5: Empty similarity (no matches)
    print("\n--- Non-matching query 'quantum computing' ---")
    results = db.search("q:quantum computing")
    print(f"  q:quantum computing → {len(results)} results")
    if len(results) == 0:
        print("  ✓ Correctly returns 0 for no matches")
        passed += 1
    else:
        print("  ✗ Expected 0 for non-matching query")
        failed += 1
    
    return passed, failed


def test_semantic_search():
    """Test semantic search with natural language queries."""
    from database import MemoryDB
    from embedding import EmbeddingModel
    
    vector = EmbeddingModel()
    db = MemoryDB(TEST_DB, embedding_model=vector)
    
    print("\n" + "=" * 60)
    print("TESTING SEMANTIC SEARCH")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    # Test semantic search
    print("\n--- Semantic: 'how to do async programming' ---")
    results = db.search("how to do async programming")
    print(f"  'how to do async programming' → {len(results)} results")
    if len(results) >= 1:
        print("  ✓ Found semantically similar memories")
        passed += 1
    else:
        print(f"  ✗ Expected at least 1, got {len(results)}")
        failed += 1
    
    return passed, failed


def test_mixed_search():
    """Test combining vector search with other filters."""
    from database import MemoryDB
    from embedding import EmbeddingModel
    
    vector = EmbeddingModel()
    db = MemoryDB(TEST_DB, embedding_model=vector)
    
    print("\n" + "=" * 60)
    print("TESTING MIXED SEARCH (vector + filters)")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    # Test: recent AND similar to "async"
    print("\n--- Recent + similar to 'async' ---")
    results = db.search("d:last 7 days AND q:async")
    print(f"  d:last 7 days AND q:async → {len(results)} results")
    if len(results) >= 1:
        print("  ✓ Found matching memories")
        passed += 1
    else:
        print(f"  ✗ Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test: keyword OR similar
    print("\n--- 'python' OR similar to 'containers' ---")
    results = db.search("k:python OR q:containers")
    print(f"  k:python OR q:containers → {len(results)} results")
    if len(results) >= 1:
        print("  ✓ Found matching memories")
        passed += 1
    else:
        print(f"  ✗ Expected at least 1, got {len(results)}")
        failed += 1
    
    return passed, failed


def cleanup():
    """Remove test database."""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    print("\n✓ Cleanup complete")


def main():
    print("=" * 60)
    print("MEMORYDB VECTOR SEARCH TESTS")
    print("=" * 60)
    print()
    
    setup()
    
    vec_passed, vec_failed = test_vector_search()
    sem_passed, sem_failed = test_semantic_search()
    mixed_passed, mixed_failed = test_mixed_search()
    
    total_passed = vec_passed + sem_passed + mixed_passed
    total_failed = vec_failed + sem_failed + mixed_failed
    
    print("\n" + "=" * 60)
    print(f"SUMMARY: {total_passed} passed, {total_failed} failed")
    print("=" * 60)
    print(f"  Vector similarity tests: {vec_passed} passed, {vec_failed} failed")
    print(f"  Semantic search tests: {sem_passed} passed, {sem_failed} failed")
    print(f"  Mixed search tests: {mixed_passed} passed, {mixed_failed} failed")
    
    cleanup()
    
    if total_failed == 0:
        print("\n✓ ALL TESTS PASSED!")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
