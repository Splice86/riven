#!/usr/bin/env python3
"""Tests for MemoryDB vector search functionality.

These tests require a running embedding model (torch, sentence-transformers).
Run on server after deploying the embedding model.
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
    """Run vector search tests."""
    from database import MemoryDB
    from embedding import EmbeddingModel
    
    emb_model = EmbeddingModel()
    db = MemoryDB(TEST_DB, embedding_model=emb_model)
    
    print("\n" + "=" * 60)
    print("RUNNING VECTOR SEARCH TESTS")
    print("=" * 60)
    
    # Test keyword similarity with vector search (s: operator)
    tests = [
        # Keyword vector similarity - s: operator
        ("Vector Similarity - programming", "s:programming", 3),  # python, coding, pytest
        ("Vector Similarity - webdev", "s:webdev", 2),  # react, frontend
        ("Vector Similarity - data", "s:data", 2),  # pandas, analytics
        ("Vector Similarity - testing", "s:testing", 2),  # pytest, unittest
        
        # With explicit threshold
        ("Vector Similarity - programming@0.7", "s:programming@0.7", 2),  # stricter threshold
        ("Vector Similarity - webdev@0.3", "s:webdev@0.3", 3),  # looser threshold
        
        # Content vector similarity - q: operator
        ("Vector Content - machine learning", "q:machine learning", 1),  # ML memory
        ("Vector Content - containers", "q:containers", 1),  # Docker memory
        ("Vector Content - web development", "q:web development", 2),  # React + FastAPI
        ("Vector Content - authentication", "q:authentication security", 1),  # OAuth
        
        # With explicit threshold
        ("Vector Content - machine learning@0.3", "q:machine learning@0.3", 2),  # looser
        ("Vector Content - containers@0.7", "q:containers@0.7", 1),  # stricter
        
        # Combined with non-vector operators
        ("Combined - s:programming AND k:python", "s:programming AND k:python", 2),
        ("Combined - q:api AND p:role=developer", "q:api AND p:role=developer", 2),
        ("Combined - s:devops AND p:status=active", "s:devops AND p:status=active", 2),
        
        # Boolean with vector
        ("Boolean - s:python OR s:javascript", "s:python OR s:javascript", 5),
        ("Boolean - q:api AND NOT k:deprecated", "q:api AND NOT k:deprecated", 2),
        
        # Complex queries
        ("Complex - (s:programming OR q:api) AND p:status=active", "(s:programming OR q:api) AND p:status=active", 4),
    ]
    
    passed = 0
    failed = 0
    
    for name, query, expected in tests:
        results = db.search(query)
        actual = len(results)
        
        if actual == expected:
            print(f"✓ {name}")
            passed += 1
        else:
            print(f"✗ {name}: got {actual}, expected {expected}")
            # Print what we found for debugging
            print(f"  Query: {query}")
            print(f"  Found {actual} memories:")
            for r in results:
                print(f"    - {r['content'][:60]}...")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
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
        print("\n✓ ALL VECTOR TESTS PASSED!")
        return 0
    else:
        print("\n✗ SOME VECTOR TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
