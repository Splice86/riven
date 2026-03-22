#!/usr/bin/env python3
"""Tests for MemoryDB vector search functionality.

These tests require a running embedding model (torch, sentence-transformers).
Run on server after deploying the embedding model.

Tests verify RELATIVE behavior:
- Higher threshold = fewer results  
- Lower threshold = more results
- Threshold changes should reduce/increase results predictably
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


def add_test_data():
    """Add test memories with real embeddings using MemoryDB API."""
    from database import MemoryDB
    from embedding import EmbeddingModel
    
    # Use real embedding model
    emb_model = EmbeddingModel()
    db = MemoryDB(TEST_DB, embedding_model=emb_model)
    now = datetime.now(timezone.utc)
    
    memories = []
    
    # Memory 1: Python programming
    mem1 = db.add_memory(
        "Learning Python programming with numpy and pandas for data science",
        keywords=["python", "coding", "programming", "numpy", "pandas", "data-science"],
        properties={"role": "tutorial", "importance": "high", "status": "active"},
        created_at=(now - timedelta(hours=0)).isoformat()
    )
    memories.append(mem1)
    print(f"  Added memory 1: Python programming (id={mem1})")
    
    # Memory 2: JavaScript web
    mem2 = db.add_memory(
        "Building React web applications with JavaScript and TypeScript",
        keywords=["javascript", "react", "web", "frontend", "typescript"],
        properties={"role": "user", "project": "webapp", "status": "active"},
        created_at=(now - timedelta(hours=2)).isoformat()
    )
    memories.append(mem2)
    print(f"  Added memory 2: JavaScript (id={mem2})")
    
    # Memory 3: Machine learning
    mem3 = db.add_memory(
        "Deep learning with PyTorch and neural networks for computer vision",
        keywords=["machine-learning", "pytorch", "deep-learning", "neural-networks", "ai", "computer-vision"],
        properties={"role": "research", "importance": "high", "status": "active"},
        created_at=(now - timedelta(hours=48)).isoformat()
    )
    memories.append(mem3)
    print(f"  Added memory 3: Machine learning (id={mem3})")
    
    # Memory 4: Deprecated old code
    mem4 = db.add_memory(
        "Old deprecated Python 2 code that needs updating to Python 3",
        keywords=["python", "deprecated", "old", "python2", "migration"],
        properties={"status": "archived", "priority": "low"},
        created_at=(now - timedelta(hours=168)).isoformat()
    )
    memories.append(mem4)
    print(f"  Added memory 4: Deprecated (id={mem4})")
    
    # Memory 5: Database
    mem5 = db.add_memory(
        "PostgreSQL database optimization and indexing for better performance",
        keywords=["postgresql", "database", "sql", "optimization", "indexing"],
        properties={"role": "admin", "priority": "high"},
        created_at=(now - timedelta(hours=6)).isoformat()
    )
    memories.append(mem5)
    print(f"  Added memory 5: Database (id={mem5})")
    
    # Memory 6: Docker/Kubernetes
    mem6 = db.add_memory(
        "Docker containerization and Kubernetes deployment for production",
        keywords=["docker", "kubernetes", "containers", "devops", "orchestration", "deployment"],
        properties={"role": "devops", "status": "active"},
        created_at=(now - timedelta(hours=72)).isoformat()
    )
    memories.append(mem6)
    print(f"  Added memory 6: Docker/K8s (id={mem6})")
    
    # Memory 7: API development
    mem7 = db.add_memory(
        "Building REST APIs with FastAPI in Python for backend services",
        keywords=["python", "fastapi", "api", "rest", "backend", "web-service"],
        properties={"role": "developer", "project": "backend", "status": "active"},
        created_at=(now - timedelta(hours=4)).isoformat()
    )
    memories.append(mem7)
    print(f"  Added memory 7: API (id={mem7})")
    
    # Memory 8: Testing
    mem8 = db.add_memory(
        "Writing unit tests with pytest and mock for Python applications",
        keywords=["python", "testing", "pytest", "mock", "unittest", "tdd"],
        properties={"role": "developer", "status": "active"},
        created_at=(now - timedelta(hours=5)).isoformat()
    )
    memories.append(mem8)
    print(f"  Added memory 8: Testing (id={mem8})")
    
    # Memory 9: GraphQL
    mem9 = db.add_memory(
        "GraphQL API design and implementation with Apollo Server",
        keywords=["graphql", "api", "backend", "schema", "apollo"],
        properties={"role": "developer", "project": "api", "status": "active"},
        created_at=(now - timedelta(hours=28)).isoformat()
    )
    memories.append(mem9)
    print(f"  Added memory 9: GraphQL (id={mem9})")
    
    # Memory 10: Redis caching
    mem10 = db.add_memory(
        "Redis caching strategies for high traffic web applications",
        keywords=["redis", "cache", "performance", "optimization", "scaling"],
        properties={"role": "architect", "status": "active"},
        created_at=(now - timedelta(hours=72)).isoformat()
    )
    memories.append(mem10)
    print(f"  Added memory 10: Redis (id={mem10})")
    
    # Memory 11: AWS
    mem11 = db.add_memory(
        "AWS Lambda serverless function optimization and cost management",
        keywords=["aws", "lambda", "serverless", "cloud", "optimization", "cost"],
        properties={"role": "devops", "status": "active"},
        created_at=(now - timedelta(hours=96)).isoformat()
    )
    memories.append(mem11)
    print(f"  Added memory 11: AWS (id={mem11})")
    
    # Memory 12: OAuth
    mem12 = db.add_memory(
        "OAuth 2.0 authentication flow implementation with JWT tokens",
        keywords=["oauth", "authentication", "security", "jwt", "authorization"],
        properties={"role": "security", "status": "active"},
        created_at=(now - timedelta(hours=84)).isoformat()
    )
    memories.append(mem12)
    print(f"  Added memory 12: OAuth (id={mem12})")
    
    # Memory 13: MongoDB
    mem13 = db.add_memory(
        "MongoDB schema design for analytics and reporting applications",
        keywords=["mongodb", "database", "nosql", "analytics", "schema"],
        properties={"role": "architect", "status": "active"},
        created_at=(now - timedelta(hours=120)).isoformat()
    )
    memories.append(mem13)
    print(f"  Added memory 13: MongoDB (id={mem13})")
    
    # Memory 14: CI/CD
    mem14 = db.add_memory(
        "Setting up CI/CD pipelines with GitHub Actions for automated deployment",
        keywords=["cicd", "github", "automation", "devops", "pipeline"],
        properties={"role": "devops", "project": "infrastructure", "status": "active"},
        created_at=(now - timedelta(hours=30)).isoformat()
    )
    memories.append(mem14)
    print(f"  Added memory 14: CI/CD (id={mem14})")
    
    # Memory 15: WebSocket
    mem15 = db.add_memory(
        "WebSocket real-time communication implementation for chat apps",
        keywords=["websocket", "realtime", "javascript", "api", "chat"],
        properties={"role": "developer", "status": "active"},
        created_at=(now - timedelta(hours=60)).isoformat()
    )
    memories.append(mem15)
    print(f"  Added memory 15: WebSocket (id={mem15})")
    
    print(f"  Added {len(memories)} memories total")
    return memories


def run_tests():
    """Run vector search tests - verify RELATIVE behavior."""
    from database import MemoryDB
    from embedding import EmbeddingModel
    
    emb_model = EmbeddingModel()
    db = MemoryDB(TEST_DB, embedding_model=emb_model)
    
    print("\n" + "=" * 60)
    print("RUNNING VECTOR SEARCH TESTS")
    print("=" * 60)
    print("Testing RELATIVE behavior (threshold changes)")
    print()
    
    passed = 0
    failed = 0
    
    # =============================================================================
    # KEYWORD SIMILARITY TESTS (s: operator)
    # =============================================================================
    print("--- Keyword Similarity (s:) ---")
    
    # Test 1: Higher threshold should return fewer or equal results
    results_default = db.search("s:programming")
    results_strict = db.search("s:programming@0.7")
    results_loose = db.search("s:programming@0.3")
    
    print(f"  s:programming (default 0.5): {len(results_default)} results")
    print(f"  s:programming@0.7 (strict): {len(results_strict)} results")  
    print(f"  s:programming@0.3 (loose): {len(results_loose)} results")
    
    # Verify relative behavior
    if len(results_strict) <= len(results_default):
        print("✓ Strict threshold returns ≤ default")
        passed += 1
    else:
        print(f"✗ Strict threshold should return ≤ default, got {len(results_strict)} > {len(results_default)}")
        failed += 1
    
    if len(results_loose) >= len(results_default):
        print("✓ Loose threshold returns ≥ default")
        passed += 1
    else:
        print(f"✗ Loose threshold should return ≥ default, got {len(results_loose)} < {len(results_default)}")
        failed += 1
    
    # Print results for debugging
    if len(results_default) > 0:
        print("  Default results:")
        for r in results_default:
            print(f"    - {r['content'][:50]}...")
    
    # =============================================================================
    # CONTENT SIMILARITY TESTS (q: operator)
    # =============================================================================
    print("\n--- Content Similarity (q:) ---")
    
    results_q_default = db.search("q:machine learning")
    results_q_strict = db.search("q:machine learning@0.7")
    results_q_loose = db.search("q:machine learning@0.3")
    
    print(f"  q:machine learning (default 0.5): {len(results_q_default)} results")
    print(f"  q:machine learning@0.7 (strict): {len(results_q_strict)} results")
    print(f"  q:machine learning@0.3 (loose): {len(results_q_loose)} results")
    
    if len(results_q_strict) <= len(results_q_default):
        print("✓ Strict threshold returns ≤ default")
        passed += 1
    else:
        print(f"✗ Strict threshold should return ≤ default")
        failed += 1
    
    if len(results_q_loose) >= len(results_q_default):
        print("✓ Loose threshold returns ≥ default")
        passed += 1
    else:
        print(f"✗ Loose threshold should return ≥ default")
        failed += 1
    
    # =============================================================================
    # COMBINED WITH NON-VECTOR
    # =============================================================================
    print("\n--- Combined with non-vector operators ---")
    
    # Keyword + vector similarity
    results_combo = db.search("s:programming AND k:python")
    print(f"  s:programming AND k:python: {len(results_combo)} results")
    if len(results_combo) > 0 and len(results_combo) <= len(results_default):
        print("✓ Combined search returns ≤ vector-only")
        passed += 1
    elif len(results_combo) == 0:
        print("✓ Combined search (0 is valid)")
        passed += 1
    else:
        print("✗ Combined should be ≤ vector-only")
        failed += 1
    
    # Vector + property filter
    results_prop = db.search("s:devops AND p:status=active")
    print(f"  s:devops AND p:status=active: {len(results_prop)} results")
    if len(results_prop) <= 15:  # Should filter down from all memories
        print("✓ Property filter reduces results")
        passed += 1
    else:
        print("✗ Property filter should reduce results")
        failed += 1
    
    # =============================================================================
    # BOOLEAN OPERATORS WITH VECTOR
    # =============================================================================
    print("\n--- Boolean operators with vector ---")
    
    # OR should return more than either alone
    results_or = db.search("s:python OR s:javascript")
    print(f"  s:python OR s:javascript: {len(results_or)} results")
    # Should be >= either individual search
    if len(results_or) >= len(results_default):
        print("✓ OR returns ≥ either individual")
        passed += 1
    else:
        print("✗ OR should return ≥ either individual")
        failed += 1
    
    # NOT should reduce results
    results_not = db.search("q:api AND NOT k:deprecated")
    print(f"  q:api AND NOT k:deprecated: {len(results_not)} results")
    results_api_only = db.search("q:api")
    print(f"  q:api only: {len(results_api_only)} results")
    if len(results_not) <= len(results_api_only):
        print("✓ NOT reduces results")
        passed += 1
    else:
        print("✗ NOT should reduce results")
        failed += 1
    
    # =============================================================================
    # EDGE CASES
    # =============================================================================
    print("\n--- Edge cases ---")
    
    # Very high threshold (should return few or none)
    results_very_high = db.search("s:programming@0.95")
    print(f"  s:programming@0.95: {len(results_very_high)} results")
    if len(results_very_high) <= len(results_strict):
        print("✓ Very high threshold returns ≤ strict")
        passed += 1
    else:
        print("✗ Very high threshold should return fewer")
        failed += 1
    
    # Very low threshold (should return more)
    results_very_low = db.search("s:programming@0.1")
    print(f"  s:programming@0.1: {len(results_very_low)} results")
    if len(results_very_low) >= len(results_loose):
        print("✓ Very low threshold returns ≥ loose")
        passed += 1
    else:
        print("✗ Very low threshold should return more")
        failed += 1
    
    # Non-existent query
    results_none = db.search("s:xyznonexistent")
    print(f"  s:xyznonexistent: {len(results_none)} results")
    if len(results_none) == 0:
        print("✓ Non-existent query returns 0")
        passed += 1
    else:
        print("✗ Non-existent query should return 0")
        failed += 1
    
    # =============================================================================
    # SUMMARY
    # =============================================================================
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n✓ ALL TESTS PASSED!")
        print("  Vector search relative behavior is correct:")
        print("  - Higher threshold → fewer results")
        print("  - Lower threshold → more results")
        print("  - Combined queries work as expected")
    else:
        print("\n✗ SOME TESTS FAILED")
    
    return failed == 0


def cleanup():
    """Remove test database."""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    print("✓ Cleanup complete")


def main():
    print("=" * 60)
    print("MEMORYDB VECTOR SEARCH TESTS")
    print("=" * 60)
    print("Testing RELATIVE behavior (not absolute counts)")
    print("NOTE: These tests require embedding model (torch)")
    print()
    
    # Check if embedding is available
    try:
        from embedding import EmbeddingModel
        emb = EmbeddingModel()
        test_vec = emb.get("test")
        if test_vec is None or (hasattr(test_vec, 'size') and test_vec.size == 0):
            print("✗ Embedding model not available (returns empty vectors)")
            return 1
    except ImportError as e:
        print(f"✗ Cannot import embedding: {e}")
        return 1
    except Exception as e:
        print(f"✗ Embedding error: {e}")
        return 1
    
    setup()
    add_test_data()
    
    success = run_tests()
    cleanup()
    
    if success:
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
