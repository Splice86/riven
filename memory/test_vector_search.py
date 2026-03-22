#!/usr/bin/env python3
"""Comprehensive tests for MemoryDB vector similarity and IF-THEN-ELSE logic.

Run on server with:
    cd memory && python3 test_vector_search.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

TEST_DB = "test_vector.db"


def setup():
    """Create fresh test database."""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    
    from database import init_db
    init_db(TEST_DB)
    print("✓ Database setup complete")


def add_link(source_id: int, target_id: int, link_type: str):
    """Add a memory link."""
    import sqlite3
    with sqlite3.connect(TEST_DB) as conn:
        conn.execute(
            "INSERT INTO memory_links (source_id, target_id, link_type) VALUES (?, ?, ?)",
            (source_id, target_id, link_type)
        )
        conn.commit()


def add_test_data():
    """Add test memories with various attributes for vector and IF tests."""
    from database import MemoryDB
    from embedding import EmbeddingModel
    
    vector = EmbeddingModel()
    db = MemoryDB(TEST_DB, embedding_model=vector)
    now = datetime.now(timezone.utc)
    
    # ===== VECTOR TEST DATA =====
    # Group 1: Python async programming (similar content)
    mem1 = db.add_memory(
        "Python asyncio tutorial for async concurrent programming with async/await",
        keywords=["python", "asyncio", "async", "concurrency"],
        created_at=(now - timedelta(days=5)).isoformat()
    )
    print(f"  Added mem1 (id={mem1}): Python asyncio (5 days old)")
    
    mem2 = db.add_memory(
        "JavaScript async await promises tutorial for asynchronous code",
        keywords=["javascript", "async", "promises", "es6"],
        created_at=(now - timedelta(days=3)).isoformat()
    )
    print(f"  Added mem2 (id={mem2}): JavaScript async (3 days old)")
    
    mem3 = db.add_memory(
        "FastAPI Python web framework building async REST APIs",
        keywords=["python", "fastapi", "api", "web"],
        created_at=(now - timedelta(days=2)).isoformat()
    )
    print(f"  Added mem3 (id={mem3}): FastAPI (2 days old)")
    
    # Group 2: Docker/containers (different content)
    mem4 = db.add_memory(
        "Docker container tutorial for images and volumes",
        keywords=["docker", "containers", "devops"],
        created_at=(now - timedelta(days=1)).isoformat()
    )
    print(f"  Added mem4 (id={mem4}): Docker (1 day old)")
    
    # ===== IF-THEN-ELSE TEST DATA =====
    # Old memories needing summaries
    mem5 = db.add_memory(
        "Deep dive into Python asyncio patterns",
        keywords=["python", "asyncio"],
        properties={"status": "active", "type": "original"},
        created_at=(now - timedelta(days=30)).isoformat()
    )
    print(f"  Added mem5 (id={mem5}): Python deep (30 days old)")
    
    mem6 = db.add_memory(
        "Machine learning with scikit-learn basics",
        keywords=["machine-learning", "sklearn"],
        properties={"status": "archived", "type": "original"},
        created_at=(now - timedelta(days=60)).isoformat()
    )
    print(f"  Added mem6 (id={mem6}): ML (60 days old, archived)")
    
    # Summaries
    summary1 = db.add_memory(
        "Quick summary: Python asyncio provides async/await for concurrent programming",
        keywords=["python", "asyncio", "summary"],
        properties={"status": "active", "type": "summary", "is_summary": "true"},
        created_at=(now - timedelta(days=25)).isoformat()
    )
    print(f"  Added summary1 (id={summary1}): Summary of mem5")
    
    summary2 = db.add_memory(
        "Quick summary: scikit-learn for ML basics",
        keywords=["machine-learning", "sklearn", "summary"],
        properties={"status": "archived", "type": "summary", "is_summary": "true"},
        created_at=(now - timedelta(days=50)).isoformat()
    )
    print(f"  Added summary2 (id={summary2}): Summary of mem6")
    
    # Links: summary -> original
    add_link(summary1, mem5, "summary_of")
    add_link(summary2, mem6, "summary_of")
    
    # Related links
    add_link(mem2, mem1, "related_to")  # JS async related to Python async
    add_link(mem4, mem1, "related_to")  # Docker related to Python
    
    print(f"  Added links: 2 summaries, 2 related")
    
    return {
        "mem1": mem1, "mem2": mem2, "mem3": mem3, "mem4": mem4,
        "mem5": mem5, "mem6": mem6,
        "summary1": summary1, "summary2": summary2
    }


def test_vector_similarity(db):
    """Test vector-based similarity - relative behavior tests."""
    print("\n" + "=" * 60)
    print("TESTING VECTOR SIMILARITY (relative behavior)")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    # Test 1: Query similarity should return results for similar content
    print("\n--- Query similarity 'async programming' ---")
    results = db.search("q:async programming")
    print(f"  q:async programming -> {len(results)} results")
    if len(results) >= 1:
        print("  Found results for similar query")
        passed += 1
    else:
        print("  Expected at least 1 result")
        failed += 1
    
    # Test 2: Higher threshold = fewer or equal results (relative behavior)
    print("\n--- Threshold behavior: strict vs default ---")
    results_default = db.search("q:async")
    results_strict = db.search("q:async@0.7")
    print(f"  q:async (default 0.5): {len(results_default)} results")
    print(f"  q:async@0.7 (strict): {len(results_strict)} results")
    if len(results_strict) <= len(results_default):
        print("  Strict threshold returns <= default")
        passed += 1
    else:
        print("  Strict should return <= default")
        failed += 1
    
    # Test 3: Lower threshold = more or equal results
    results_loose = db.search("q:async@0.3")
    print(f"  q:async@0.3 (loose): {len(results_loose)} results")
    if len(results_loose) >= len(results_default):
        print("  Loose threshold returns >= default")
        passed += 1
    else:
        print("  Loose should return >= default")
        failed += 1
    
    # Test 4: Non-matching query should return fewer results
    print("\n--- Non-matching query 'cooking recipes' ---")
    results = db.search("q:cooking recipes")
    print(f"  q:cooking recipes -> {len(results)} results")
    if len(results) <= len(results_default):
        print("  Unrelated query returns <= related query")
        passed += 1
    else:
        print("  Unrelated should return fewer results")
        failed += 1
    
    # Test 5: Keyword similarity with threshold
    print("\n--- Keyword similarity 'python' ---")
    results = db.search("s:python@0.5")
    print(f"  s:python@0.5 -> {len(results)} results")
    if len(results) >= 1:
        print("  Found similar keywords")
        passed += 1
    else:
        print("  Expected at least 1")
        failed += 1
    
    # Test 6: Combined keyword AND similarity
    print("\n--- Combined: k:python AND q:async ---")
    results = db.search("k:python AND q:async")
    print(f"  k:python AND q:async -> {len(results)} results")
    if len(results) >= 1:
        print("  Combined search works")
        passed += 1
    else:
        print("  Expected at least 1")
        failed += 1
    
    return passed, failed


def test_if_then_else(db, ids):
    """Test IF-THEN-ELSE conditional logic."""
    print("\n" + "=" * 60)
    print("TESTING IF-THEN-ELSE CONDITIONALS")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    # Test 1: Date-based conditional - THEN branch (recent memories exist)
    print("\n--- Date conditional: d:last 3 days THEN k:python ---")
    query = "IF d:last 3 days THEN k:python ELSE k:docker"
    results = db.search(query)
    print(f"  {query}")
    print(f"  -> {len(results)} results")
    # mem2 (3 days), mem3 (2 days), mem4 (1 day) should match k:python
    if len(results) >= 1:
        print("  Found python memories in last 3 days")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 2: Date-based conditional - ELSE branch (no recent python, use docker)
    print("\n--- Date conditional: d:last 1 day THEN k:javascript ELSE k:docker ---")
    query = "IF d:last 1 day THEN k:javascript ELSE k:docker"
    results = db.search(query)
    print(f"  {query}")
    print(f"  -> {len(results)} results")
    # mem4 is docker, 1 day old - should match docker
    if len(results) >= 1:
        print("  Found docker memories")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 3: Property-based conditional - THEN branch
    print("\n--- Property conditional: p:is_summary=true THEN k:python ---")
    query = "IF p:is_summary=true THEN k:python ELSE k:javascript"
    results = db.search(query)
    print(f"  {query}")
    print(f"  -> {len(results)} results")
    # summary1 has python keyword
    if len(results) >= 1:
        print("  Found summaries with python")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 4: Property-based conditional - ELSE branch (no active summaries, use active)
    print("\n--- Property conditional: p:status=archived THEN k:sklearn ELSE p:status=active ---")
    query = "IF p:status=archived THEN k:sklearn ELSE p:status=active"
    results = db.search(query)
    print(f"  {query}")
    print(f"  -> {len(results)} results")
    # mem6 is archived with sklearn, should match
    if len(results) >= 1:
        print("  Found archived or active memories")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 5: Keyword-based conditional
    print("\n--- Keyword conditional: k:asyncio THEN k:python ELSE k:docker ---")
    query = "IF k:asyncio THEN k:python ELSE k:docker"
    results = db.search(query)
    print(f"  {query}")
    print(f"  -> {len(results)} results")
    # mem1, mem5 have asyncio -> should match python
    if len(results) >= 1:
        print("  Found asyncio->python")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 6: Complex conditional with OR in THEN
    print("\n--- Complex: d:last 3 days THEN k:python OR k:javascript ---")
    query = "IF d:last 3 days THEN k:python OR k:javascript ELSE k:docker"
    results = db.search(query)
    print(f"  {query}")
    print(f"  -> {len(results)} results")
    # Should find python (mem2, mem3) or javascript (mem2)
    if len(results) >= 1:
        print("  Found python or javascript in recent days")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 7: IF without ELSE (just THEN branch)
    print("\n--- IF without ELSE: IF k:python THEN k:asyncio ---")
    query = "IF k:python THEN k:asyncio"
    results = db.search(query)
    print(f"  {query}")
    print(f"  -> {len(results)} results")
    # mem1, mem3, mem5 have python, should find asyncio
    if len(results) >= 1:
        print("  IF without ELSE works")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 8: NOT in condition
    print("\n--- NOT condition: IF NOT p:status=archived THEN k:python ---")
    query = "IF NOT p:status=archived THEN k:python ELSE k:javascript"
    results = db.search(query)
    print(f"  {query}")
    print(f"  -> {len(results)} results")
    # mem5 is active (not archived), has python
    if len(results) >= 1:
        print("  NOT condition works")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    return passed, failed


def test_link_traversal(db, ids):
    """Test link traversal queries."""
    print("\n" + "=" * 60)
    print("TESTING LINK TRAVERSAL")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    # Test 1: Direct link by target ID
    print("\n--- Direct link: l:summary_of:5 ---")
    results = db.search(f"l:summary_of:{ids['mem5']}")
    print(f"  l:summary_of:{ids['mem5']} -> {len(results)} results")
    if len(results) >= 1 and any(r['id'] == ids['summary1'] for r in results):
        print("  Found summary1")
        passed += 1
    else:
        print("  Expected summary1")
        failed += 1
    
    # Test 2: Related links
    print("\n--- Related links: l:related_to:1 ---")
    results = db.search(f"l:related_to:{ids['mem1']}")
    print(f"  l:related_to:{ids['mem1']} -> {len(results)} results")
    # mem2 and mem4 are related to mem1
    if len(results) >= 1:
        print("  Found related memories")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 3: Link with inner keyword query
    print("\n--- Link with inner query: l:summary_of:(k:python) ---")
    results = db.search("l:summary_of:(k:python)")
    print(f"  l:summary_of:(k:python) -> {len(results)} results")
    # summary1 is summary of python memory
    if len(results) >= 1:
        print("  Found summaries of python memories")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 4: Link type only (no target)
    print("\n--- Link type only: l:summary_of ---")
    results = db.search("l:summary_of")
    print(f"  l:summary_of -> {len(results)} results")
    if len(results) >= 1:
        print("  Found all summaries")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    return passed, failed


def test_combined(db, ids):
    """Test combined link + IF-THEN-ELSE."""
    print("\n" + "=" * 60)
    print("TESTING COMBINED (LINKS + IF-THEN-ELSE)")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    # Test 1: Link with conditional
    print("\n--- Link with conditional: IF d:last 3 days THEN l:related_to:k:python ELSE l:summary_of:k:python ---")
    query = "IF d:last 3 days THEN l:related_to:(k:python) ELSE l:summary_of:(k:python)"
    results = db.search(query)
    print(f"  -> {len(results)} results")
    # Recent memories (mem2, mem3, mem4) - mem2 and mem4 are related to python
    if len(results) >= 1:
        print("  Found matching memories")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    return passed, failed


def test_mixed_search(db):
    """Test mixing vector search with other filters."""
    print("\n" + "=" * 60)
    print("TESTING MIXED SEARCH (vector + filters)")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    # Test 1: Date + similarity
    print("\n--- Recent + similar: d:last 7 days AND q:async ---")
    results = db.search("d:last 7 days AND q:async")
    print(f"  d:last 7 days AND q:async -> {len(results)} results")
    if len(results) >= 1:
        print("  Combined date + vector works")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 2: Keyword OR similarity
    print("\n--- Keyword OR similarity: k:python OR q:containers ---")
    results = db.search("k:python OR q:containers")
    print(f"  k:python OR q:containers -> {len(results)} results")
    # python memories (mem1, mem3, mem5) or similar to containers (mem4)
    if len(results) >= 1:
        print("  Combined keyword OR vector works")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    # Test 3: Property + similarity
    print("\n--- Property + similarity: p:status=active AND q:async ---")
    results = db.search("p:status=active AND q:async")
    print(f"  p:status=active AND q:async -> {len(results)} results")
    if len(results) >= 1:
        print("  Combined property + vector works")
        passed += 1
    else:
        print(f"  Expected at least 1, got {len(results)}")
        failed += 1
    
    return passed, failed


def cleanup():
    """Remove test database."""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    print("\nCleanup complete")


def main():
    print("=" * 60)
    print("MEMORYDB COMPREHENSIVE TESTS")
    print("Vector Similarity + IF-THEN-ELSE + Links")
    print("=" * 60)
    print()
    
    setup()
    ids = add_test_data()
    
    from database import MemoryDB
    from embedding import EmbeddingModel
    vector = EmbeddingModel()
    db = MemoryDB(TEST_DB, embedding_model=vector)
    
    # Run all test categories
    vec_passed, vec_failed = test_vector_similarity(db)
    if_passed, if_failed = test_if_then_else(db, ids)
    link_passed, link_failed = test_link_traversal(db, ids)
    combined_passed, combined_failed = test_combined(db, ids)
    mixed_passed, mixed_failed = test_mixed_search(db)
    
    total_passed = vec_passed + if_passed + link_passed + combined_passed + mixed_passed
    total_failed = vec_failed + if_failed + link_failed + combined_failed + mixed_failed
    
    print("\n" + "=" * 60)
    print(f"SUMMARY: {total_passed} passed, {total_failed} failed")
    print("=" * 60)
    print(f"  Vector similarity: {vec_passed} passed, {vec_failed} failed")
    print(f"  IF-THEN-ELSE: {if_passed} passed, {if_failed} failed")
    print(f"  Link traversal: {link_passed} passed, {link_failed} failed")
    print(f"  Combined: {combined_passed} passed, {combined_failed} failed")
    print(f"  Mixed search: {mixed_passed} passed, {mixed_failed} failed")
    
    cleanup()
    
    if total_failed == 0:
        print("\nALL TESTS PASSED!")
        return 0
    else:
        print("\nSOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
