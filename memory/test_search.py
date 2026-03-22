#!/usr/bin/env python3
"""Comprehensive test suite for memory search functionality."""

import sqlite3
import os
from datetime import datetime, timedelta, timezone

# Use test database
TEST_DB = "test_search.db"


def setup_database():
    """Create fresh test database with all required tables."""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    
    conn = sqlite3.connect(TEST_DB)
    
    # Main memories table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            embedding BLOB,
            created_at TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            last_accessed TEXT
        )
    """)
    
    # Keywords table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            embedding BLOB
        )
    """)
    
    # Memory keywords junction
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_keywords (
            memory_id INTEGER NOT NULL,
            keyword_id INTEGER NOT NULL,
            PRIMARY KEY (memory_id, keyword_id)
        )
    """)
    
    # Memory properties table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            UNIQUE(memory_id, key)
        )
    """)
    
    # Memory links table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            link_type TEXT NOT NULL,
            UNIQUE(source_id, target_id, link_type)
        )
    """)
    
    conn.commit()
    conn.close()
    print("✓ Database setup complete")


def add_test_data():
    """Add test memories with various keywords and properties."""
    conn = sqlite3.connect(TEST_DB)
    now = datetime.now(timezone.utc).isoformat()
    
    # Helper to insert keyword and return ID
    def insert_keyword(name):
        conn.execute("INSERT OR IGNORE INTO keywords (name) VALUES (?)", (name,))
        row = conn.execute("SELECT id FROM keywords WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None
    
    # Helper to insert memory
    def insert_memory(content, created_offset_hours=0):
        created = (datetime.now(timezone.utc) - timedelta(hours=created_offset_hours)).isoformat()
        conn.execute(
            "INSERT INTO memories (content, created_at, last_updated) VALUES (?, ?, ?)",
            (content, created, created)
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # Helper to link keyword to memory
    def link_keyword(mem_id, kw_name):
        kw_id = insert_keyword(kw_name)
        conn.execute(
            "INSERT OR IGNORE INTO memory_keywords (memory_id, keyword_id) VALUES (?, ?)",
            (mem_id, kw_id)
        )
    
    # Helper to add property
    def add_property(mem_id, key, value):
        conn.execute(
            "INSERT OR REPLACE INTO memory_properties (memory_id, key, value) VALUES (?, ?, ?)",
            (mem_id, key, value)
        )
    
    # =========================================================================
    # Add test memories
    # =========================================================================
    
    # Memory 1: Python programming (recent)
    mem1 = insert_memory("Learning Python programming with numpy and pandas", 0)
    link_keyword(mem1, "python")
    link_keyword(mem1, "coding")
    link_keyword(mem1, "programming")
    link_keyword(mem1, "numpy")
    link_keyword(mem1, "pandas")
    add_property(mem1, "role", "tutorial")
    add_property(mem1, "importance", "high")
    print(f"  Added memory 1: Python programming (id={mem1})")
    
    # Memory 2: JavaScript (recent)
    mem2 = insert_memory("Building React web applications with JavaScript", 2)
    link_keyword(mem2, "javascript")
    link_keyword(mem2, "react")
    link_keyword(mem2, "web")
    link_keyword(mem2, "frontend")
    add_property(mem2, "role", "user")
    add_property(mem2, "project", "webapp")
    print(f"  Added memory 2: JavaScript (id={mem2})")
    
    # Memory 3: Machine learning (older)
    mem3 = insert_memory("Deep learning with PyTorch and neural networks", 48)
    link_keyword(mem3, "machine-learning")
    link_keyword(mem3, "pytorch")
    link_keyword(mem3, "deep-learning")
    link_keyword(mem3, "neural-networks")
    add_property(mem3, "role", "research")
    add_property(mem3, "importance", "high")
    print(f"  Added memory 3: Machine learning (id={mem3})")
    
    # Memory 4: Deprecated old code (old)
    mem4 = insert_memory("Old deprecated Python 2 code that needs updating", 168)  # 1 week ago
    link_keyword(mem4, "python")
    link_keyword(mem4, "deprecated")
    link_keyword(mem4, "old")
    link_keyword(mem4, "python2")
    add_property(mem4, "status", "archived")
    print(f"  Added memory 4: Deprecated code (id={mem4})")
    
    # Memory 5: Database (recent)
    mem5 = insert_memory("PostgreSQL database optimization and indexing", 6)
    link_keyword(mem5, "postgresql")
    link_keyword(mem5, "database")
    link_keyword(mem5, "sql")
    link_keyword(mem5, "optimization")
    add_property(mem5, "role", "admin")
    print(f"  Added memory 5: Database (id={mem5})")
    
    # Memory 6: Docker (older)
    mem6 = insert_memory("Docker containerization and Kubernetes deployment", 72)
    link_keyword(mem6, "docker")
    link_keyword(mem6, "kubernetes")
    link_keyword(mem6, "containers")
    link_keyword(mem6, "devops")
    add_property(mem6, "role", "devops")
    print(f"  Added memory 6: Docker (id={mem6})")
    
    # Memory 7: API development (recent)
    mem7 = insert_memory("Building REST APIs with FastAPI in Python", 4)
    link_keyword(mem7, "python")
    link_keyword(mem7, "fastapi")
    link_keyword(mem7, "api")
    link_keyword(mem7, "rest")
    add_property(mem7, "role", "developer")
    add_property(mem7, "project", "backend")
    print(f"  Added memory 7: API development (id={mem7})")
    
    conn.commit()
    conn.close()
    
    # Return memory IDs for cleanup
    return [mem1, mem2, mem3, mem4, mem5, mem6, mem7]


def run_search_tests(memory_ids):
    """Run all search tests and verify results."""
    from search import MemorySearcher
    searcher = MemorySearcher(TEST_DB)
    
    print("\n" + "=" * 60)
    print("RUNNING SEARCH TESTS")
    print("=" * 60)
    
    tests = [
        # =========================================================================
        # KEYWORD TESTS
        # =========================================================================
        {
            "name": "Keyword exact match - python",
            "query": "k:python",
            "expected_count": 3,  # mem1, mem4, mem7
            "expected_contains": ["Python programming", "deprecated", "REST APIs"],
        },
        {
            "name": "Keyword exact match - javascript",
            "query": "k:javascript",
            "expected_count": 1,
            "expected_contains": ["React web"],
        },
        {
            "name": "Keyword similarity - pyth",
            "query": "s:pyth",  # LIKE match
            "expected_count": 3,
            "expected_contains": ["Python programming", "deprecated", "REST APIs"],
        },
        
        # =========================================================================
        # BOOLEAN OPERATOR TESTS
        # =========================================================================
        {
            "name": "AND operator - python AND coding",
            "query": "k:python AND k:coding",
            "expected_count": 1,
            "expected_contains": ["Learning Python"],
        },
        {
            "name": "OR operator - python OR javascript",
            "query": "k:python OR k:javascript",
            "expected_count": 4,
            "expected_not_contains": ["Machine learning"],  # Should NOT contain ML memory
        },
        {
            "name": "NOT operator - NOT deprecated",
            "query": "NOT k:deprecated",
            "expected_count": 6,  # All except mem4
        },
        
        # =========================================================================
        # PROPERTY TESTS
        # =========================================================================
        {
            "name": "Property filter - role=user",
            "query": "p:role=user",
            "expected_count": 1,
            "expected_contains": ["React web"],
        },
        {
            "name": "Property filter - importance=high",
            "query": "p:importance=high",
            "expected_count": 2,  # mem1, mem3
            "expected_contains": ["Learning Python", "Deep learning"],
        },
        {
            "name": "Multiple properties - role=developer AND project=backend",
            "query": "p:role=developer AND p:project=backend",
            "expected_count": 1,
            "expected_contains": ["REST APIs"],
        },
        
        # =========================================================================
        # CONTENT SEARCH TESTS
        # =========================================================================
        {
            "name": "Content search - Docker",
            "query": "q:Docker",
            "expected_count": 1,
            "expected_contains": ["Docker containerization"],
        },
        {
            "name": "Content search - neural",
            "query": "q:neural",
            "expected_count": 1,
            "expected_contains": ["Deep learning"],
        },
        
        # =========================================================================
        # DATE FILTER TESTS
        # =========================================================================
        {
            "name": "Date filter - last 24 hours",
            "query": "d:last 24 hours",
            "expected_count": 4,  # mem1, mem2, mem5, mem7 (within 24 hours)
        },
        {
            "name": "Date filter - last 7 days",
            "query": "d:last 7 days",
            "expected_count": 6,  # All except mem4 (1 week old)
        },
        
        # =========================================================================
        # COMPLEX QUERY TESTS
        # =========================================================================
        {
            "name": "Complex - python AND NOT deprecated",
            "query": "k:python AND NOT k:deprecated",
            "expected_count": 2,  # mem1, mem7
        },
        {
            "name": "Complex - (python OR javascript) AND role=user",
            "query": "k:python OR k:javascript AND p:role=user",
            "expected_count": 1,  # mem2 (javascript + role=user)
        },
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        query = test["query"]
        expected_count = test["expected_count"]
        
        results = searcher.search(query)
        actual_count = len(results)
        
        # Check content if specified
        if "expected_contains" in test:
            contents = [r["content"] for r in results]
            contains_ok = all(
                any(word.lower() in content.lower() for word in test["expected_contains"])
                for content in contents
            )
        else:
            contains_ok = True
        
        if "expected_not_contains" in test:
            contents = [r["content"] for r in results]
            not_contains_ok = not any(
                any(word.lower() in content.lower() for word in test["expected_not_contains"])
                for content in contents
            )
        else:
            not_contains_ok = True
        
        success = actual_count == expected_count and contains_ok and not_contains_ok
        
        if success:
            print(f"✓ {test['name']}")
            print(f"    Query: {query!r}")
            print(f"    Results: {actual_count} (expected {expected_count})")
            passed += 1
        else:
            print(f"✗ {test['name']}")
            print(f"    Query: {query!r}")
            print(f"    Results: {actual_count} (expected {expected_count})")
            if not contains_ok:
                print(f"    ERROR: Content check failed")
            if not not_contains_ok:
                print(f"    ERROR: Not-contains check failed")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


def cleanup(memory_ids):
    """Remove test data from database."""
    conn = sqlite3.connect(TEST_DB)
    
    # Delete in reverse dependency order
    conn.execute("DELETE FROM memory_properties WHERE memory_id IN ({})".format(
        ",".join("?" * len(memory_ids))), memory_ids)
    conn.execute("DELETE FROM memory_keywords WHERE memory_id IN ({})".format(
        ",".join("?" * len(memory_ids))), memory_ids)
    conn.execute("DELETE FROM memories WHERE id IN ({})".format(
        ",".join("?" * len(memory_ids))), memory_ids)
    
    # Clean up orphaned keywords
    conn.execute("""
        DELETE FROM keywords WHERE id NOT IN (
            SELECT DISTINCT keyword_id FROM memory_keywords
        )
    """)
    
    conn.commit()
    conn.close()
    
    # Remove database file
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    
    print("✓ Cleanup complete")


def main():
    """Run all tests."""
    print("=" * 60)
    print("MEMORY SEARCH COMPREHENSIVE TEST SUITE")
    print("=" * 60)
    
    # Setup
    print("\nSetting up test database...")
    setup_database()
    
    # Add test data
    print("\nAdding test memories...")
    memory_ids = add_test_data()
    print(f"  Added {len(memory_ids)} memories with keywords and properties")
    
    # Run tests
    success = run_search_tests(memory_ids)
    
    # Cleanup
    print("\nCleaning up test data...")
    cleanup(memory_ids)
    
    # Final result
    print("\n" + "=" * 60)
    if success:
        print("ALL TESTS PASSED! ✓")
    else:
        print("SOME TESTS FAILED ✗")
    print("=" * 60)
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
