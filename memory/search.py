"""Search parser for memory database query DSL."""

import re
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass
from enum import Enum


# =============================================================================
# SEARCH QUERY DSL
# =============================================================================
#
# Prefixes:
#   k:<keyword>   - keyword (exact match)
#   s:<keyword>  - keyword similarity (semantic, finds similar keywords)
#   q:<text>   - query (semantic text search against memory content)
#   d:<date>    - date filter
#   p:<key=value> - property filter
#
# Operators:
#   AND - both conditions must match
#   OR  - either condition must match
#   NOT - negate condition
#
# Grouping:
#   ( ) - parentheses for grouping
#
# Date formats:
#   YYYY-MM-DD           - exact date
#   YYYY-MM-DD to YYYY-MM-DD  - range
#   YYYY-MM-DDTHH:MM to YYYY-MM-DDTHH:MM - range with times
#   today                 - today's date
#   yesterday            - yesterday
#   last N days          - relative (e.g., "last 7 days")
#   last N hours          - relative (e.g., "last 24 hours")
#
# Similarity threshold (optional):
#   Append @threshold to s: or q: queries (e.g., "s:python@0.8")
#   Default threshold is 0.5. Higher = stricter, Lower = looser.
#
# Examples:
#   "k:python"                           - keyword = python
#   "k:python AND k:coding"            - both keywords
#   "k:python OR k:javascript"          - either keyword
#   "NOT k:old"                       - exclude keyword
#   "s:python"                        - similar to python (threshold 0.5)
#   "s:python@0.8"                     - similar to python with 0.8 threshold
#   "q:machine learning"             - semantic text search (threshold 0.5)
#   "q:machine learning@0.3"           - semantic text with looser threshold
#   "p:role=user"                      - property = user
#   "p:role=user AND importance=high" - multiple properties
#   "d:last 30 days"                  - last 30 days
#   "d:2025-01-01 to 2025-01-31"      - date range
#   "(k:python OR s:javascript) AND NOT k:deprecated"
#
# =============================================================================


class SearchType(Enum):
    """Search type prefixes."""
    KEYWORD = "k"       # Exact keyword match
    KEYWORD_SIM = "s"   # Keyword similarity (semantic)
    QUERY = "q"        # Text query (semantic)
    DATE = "d"           # Date filter
    PROPERTY = "p"       # Property filter


class Operator(Enum):
    """Boolean operators."""
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


@dataclass
class SearchCondition:
    """Represents a single search condition."""
    search_type: SearchType
    value: str
    negated: bool = False
    threshold: float = None  # Similarity threshold (e.g., 0.8 for "s:python@0.8")


@dataclass
class SearchNode:
    """AST node for parsed search query."""
    # Node types:
    # - "condition": A single condition (search_type + value)
    # - "binary": AND/OR operation with left and right children
    # - "unary": NOT operation with child
    
    node_type: str  # "condition", "binary", "unary"
    operator: Optional[Operator] = None  # For binary/unary nodes
    search_type: Optional[SearchType] = None  # For condition nodes
    value: Optional[str] = None  # For condition nodes
    negated: bool = False  # For condition nodes
    threshold: Optional[float] = None  # For similarity threshold (e.g., 0.8)
    left: Optional["SearchNode"] = None  # For binary nodes
    right: Optional["SearchNode"] = None  # For binary nodes
    child: Optional["SearchNode"] = None  # For unary nodes


class SearchParser:
    """Parser for the search query DSL."""
    
    def __init__(self, query_string: str, searcher=None):
        self.query_string = query_string.strip()
        self.tokens = []
        self.pos = 0
        self.searcher = searcher  # MemorySearcher instance for similarity search
    
    # -------------------------------------------------------------------------
    # TOKENIZER
    # -------------------------------------------------------------------------
    
    def tokenize(self) -> list[tuple]:
        """Convert query string into tokens.
        
        Token types:
            - PREFIX: k, s, q, d, p
            - COLON: :
            - VALUE: the search value
            - OPERATOR: AND, OR, NOT
            - LPAREN: (
            - RPAREN: )
            - TO: "to" for date ranges
        
        Returns:
            List of (token_type, value) tuples
        """
        tokens = []
        query = self.query_string
        i = 0
        
        while i < len(query):
            # Skip whitespace
            if query[i].isspace():
                i += 1
                continue
            
            # Left parenthesis
            if query[i] == '(':
                tokens.append(('LPAREN', '('))
                i += 1
                continue
            
            # Right parenthesis
            if query[i] == ')':
                tokens.append(('RPAREN', ')'))
                i += 1
                continue
            
            # Check for operators (AND, OR, NOT) - must have whitespace before
            # (or be at start) and either whitespace after or end of query
            if query[i:i+3].upper() == 'AND':
                if (i == 0 or query[i-1].isspace()) and (i + 3 >= len(query) or query[i+3].isspace()):
                    tokens.append(('OPERATOR', 'AND'))
                    i += 3
                    continue
            
            if query[i:i+2].upper() == 'OR':
                if (i == 0 or query[i-1].isspace()) and (i + 2 >= len(query) or query[i+2].isspace()):
                    tokens.append(('OPERATOR', 'OR'))
                    i += 2
                    continue
            
            if query[i:i+3].upper() == 'NOT':
                if (i == 0 or query[i-1].isspace()) and (i + 3 >= len(query) or query[i+3].isspace()):
                    tokens.append(('OPERATOR', 'NOT'))
                    i += 3
                    continue
            
            # Check for prefix (k, s, q, d, p)
            if query[i] in 'ksqdpKSQDP':
                prefix = query[i].lower()
                tokens.append(('PREFIX', prefix))
                i += 1
                
                # Expect colon after prefix
                if i < len(query) and query[i] == ':':
                    tokens.append(('COLON', ':'))
                    i += 1
                
                # Get the value (everything until next operator, paren, or end)
                value_start = i
                while i < len(query):
                    # Stop at closing paren
                    if query[i] == ')':
                        break
                    # Stop at space followed by operator or paren
                    if query[i].isspace():
                        # Check if next non-space is operator or paren
                        j = i + 1
                        while j < len(query) and query[j].isspace():
                            j += 1
                        if j < len(query) and (query[j] in '()' or query[j:j+3].upper() in ('AND', 'NOT') or query[j:j+2].upper() == 'OR'):
                            break
                    # Check for operators - only if preceded by whitespace
                    if i > 0 and query[i-1].isspace():
                        if i + 2 <= len(query) and query[i:i+2].upper() == 'OR':
                            break
                        if i + 3 <= len(query) and query[i:i+3].upper() in ('AND', 'NOT'):
                            break
                    i += 1
                
                value = query[value_start:i].strip()
                if value:
                    tokens.append(('VALUE', value))
                continue
            
            # Check for "to" (for date ranges like "2025-01-01 to 2025-01-31")
            if query[i:i+2].lower() == 'to':
                tokens.append(('TO', 'to'))
                i += 2
                continue
            
            # If we get here, skip unknown character
            i += 1
        
        self.tokens = tokens
        return tokens
    
    # -------------------------------------------------------------------------
    # PARSER
    # -------------------------------------------------------------------------
    
    def parse(self) -> SearchNode:
        """Parse tokens into AST.
        
        Grammar:
            expression  -> term (AND term | OR term)*
            term         -> NOT term | PRIMARY
            PRIMARY      -> condition | LPAREN expression RPAREN
            condition    -> (NOT)? (k|s|q|d|p):value
        
        Returns:
            Root AST node
        """
        self.pos = 0
        self.tokens = self.tokenize()
        return self.parse_expression()
    
    def parse_expression(self) -> SearchNode:
        """Parse expression -> term (AND term | OR term)*"""
        left = self.parse_term()
        
        while self.pos < len(self.tokens):
            token_type, token_val = self.tokens[self.pos]
            
            if token_type == 'OPERATOR' and token_val in ('AND', 'OR'):
                self.pos += 1  # consume operator
                right = self.parse_term()
                left = SearchNode(
                    node_type='binary',
                    operator=Operator.AND if token_val == 'AND' else Operator.OR,
                    left=left,
                    right=right
                )
            else:
                break
        
        return left
    
    def parse_term(self) -> SearchNode:
        """Parse term -> NOT term | PRIMARY"""
        if self.pos >= len(self.tokens):
            return None
        
        token_type, token_val = self.tokens[self.pos]
        
        if token_type == 'OPERATOR' and token_val == 'NOT':
            self.pos += 1  # consume NOT
            child = self.parse_term()
            return SearchNode(
                node_type='unary',
                operator=Operator.NOT,
                child=child
            )
        
        return self.parse_primary()
    
    def parse_primary(self) -> SearchNode:
        """Parse PRIMARY -> condition | LPAREN expression RPAREN"""
        if self.pos >= len(self.tokens):
            return None
        
        token_type, token_val = self.tokens[self.pos]
        
        if token_type == 'LPAREN':
            self.pos += 1  # consume (
            expr = self.parse_expression()
            # consume )
            if self.pos < len(self.tokens) and self.tokens[self.pos][0] == 'RPAREN':
                self.pos += 1
            return expr
        
        return self.parse_condition()
    
    def parse_condition(self) -> SearchNode:
        """Parse condition -> (NOT)? (k|s|q|d|p):value"""
        # Check for leading NOT
        negated = False
        if self.pos < len(self.tokens):
            token_type, token_val = self.tokens[self.pos]
            if token_type == 'OPERATOR' and token_val == 'NOT':
                negated = True
                self.pos += 1
        
        # Expect PREFIX
        if self.pos >= len(self.tokens):
            return None
        
        token_type, token_val = self.tokens[self.pos]
        
        if token_type != 'PREFIX':
            # Skip unknown token
            self.pos += 1
            return self.parse_condition()
        
        prefix = token_val
        self.pos += 1  # consume prefix
        
        # Skip COLON if present
        if self.pos < len(self.tokens) and self.tokens[self.pos][0] == 'COLON':
            self.pos += 1
        
        # Get VALUE - check for threshold syntax like "programming@0.8"
        threshold = None
        if self.pos < len(self.tokens) and self.tokens[self.pos][0] == 'VALUE':
            raw_value = self.tokens[self.pos][1]
            self.pos += 1
            
            # Parse threshold from value (e.g., "programming@0.8")
            if '@' in raw_value:
                value, threshold_str = raw_value.split('@', 1)
                try:
                    threshold = float(threshold_str)
                except ValueError:
                    threshold = None
            else:
                value = raw_value
        else:
            value = ""
        
        # Map prefix to SearchType
        type_map = {
            'k': SearchType.KEYWORD,
            's': SearchType.KEYWORD_SIM,
            'q': SearchType.QUERY,
            'd': SearchType.DATE,
            'p': SearchType.PROPERTY,
        }
        
        search_type = type_map.get(prefix, SearchType.QUERY)
        
        # Store threshold in a hidden way - we'll pass it through via the searcher
        # For now, embed it in the value as a special marker
        # Actually, let's just use the value and we'll handle it in build_query
        
        return SearchNode(
            node_type='condition',
            search_type=search_type,
            value=value,
            negated=negated,
            # We'll pass threshold via a custom attribute
            threshold=threshold,
            left=None,
            right=None,
            child=None,
            operator=None
        )
    
    # -------------------------------------------------------------------------
    # DATE PARSING
    # -------------------------------------------------------------------------
    
    def parse_date(self, date_str: str) -> tuple[Optional[str], Optional[str]]:
        """Parse date string into (start_date, end_date) tuple.
        
        Formats:
            - "today" -> (start_of_today, end_of_today)
            - "yesterday" -> (start_of_yesterday, end_of_yesterday)
            - "last N days" -> (N days ago, now)
            - "last N hours" -> (N hours ago, now)
            - "YYYY-MM-DD" -> (start_of_day, end_of_day)
            - "YYYY-MM-DDTHH:MM" -> (exact datetime, same datetime)
            - "YYYY-MM-DD to YYYY-MM-DD" -> (start, end)
            - "YYYY-MM-DDTHH:MM to YYYY-MM-DDTHH:MM" -> (start, end)
        
        Returns:
            (start_date, end_date) as ISO format strings, or (None, None) if invalid
        """
        date_str = date_str.strip().lower()
        now = datetime.now(timezone.utc)
        
        # Handle date ranges (contains "to")
        if ' to ' in date_str:
            return self._parse_date_range(date_str, now)
        
        # Handle relative dates
        if date_str == 'today':
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            return (start.isoformat(), end.isoformat())
        
        if date_str == 'yesterday':
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return (start.isoformat(), end.isoformat())
        
        # "last N days" or "last N hours"
        if date_str.startswith('last '):
            # Extract number
            parts = date_str.split()
            if len(parts) >= 3:
                try:
                    num = int(parts[1])
                    unit = parts[2]  # "days" or "hours"
                    
                    if 'day' in unit:
                        start = now - timedelta(days=num)
                    elif 'hour' in unit:
                        start = now - timedelta(hours=num)
                    else:
                        return (None, None)
                    
                    return (start.isoformat(), now.isoformat())
                except (ValueError, IndexError):
                    pass
            return (None, None)
        
        # Try to parse as absolute date
        result = self._parse_single_date(date_str, now)
        return result  # Returns (start, end) tuple
    
    def _parse_single_date(self, date_str: str, now: datetime) -> tuple[Optional[str], Optional[str]]:
        """Parse a single date string into (start, end) tuple."""
        date_str = date_str.strip()
        
        # Check if has time component (contains 'T' or 't' after lowercasing)
        has_time = 't' in date_str.lower()
        
        if has_time:
            # Try parsing with time (YYYY-MM-DDTHH:MM)
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return (dt.isoformat(), dt.isoformat())
            except ValueError:
                pass
        else:
            # Try parsing as date only (YYYY-MM-DD) - return full day range
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                dt = dt.replace(tzinfo=timezone.utc)
                start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                end = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                return (start.isoformat(), end.isoformat())
            except ValueError:
                pass
        
        return (None, None)

    def _parse_date_range(self, date_str: str, now: datetime) -> tuple[Optional[str], Optional[str]]:
        """Parse a date range string into (start, end) tuple."""
        parts = date_str.split(' to ')
        if len(parts) != 2:
            return (None, None)
        
        start = self._parse_single_date(parts[0].strip(), now)
        end = self._parse_single_date(parts[1].strip(), now)
        
        if start[0] is None or end[0] is None:
            return (None, None)
        
        return (start[0], end[1])
    
    # -------------------------------------------------------------------------
    # SQL QUERY BUILDER
    # -------------------------------------------------------------------------
    
    def build_query(self, node: SearchNode) -> tuple[str, list]:
        """Build SQL query from AST node.
        
        Returns:
            (sql_query, params_list)
        """
        if node is None:
            return ("1=1", [])  # No condition
        
        if node.node_type == 'condition':
            return self._build_condition_query(node)
        
        if node.node_type == 'binary':
            return self._build_binary_query(node)
        
        if node.node_type == 'unary':
            return self._build_unary_query(node)
        
        return ("1=1", [])
    
    def _build_condition_query(self, node: SearchNode) -> tuple[str, list]:
        """Build SQL for a single condition."""
        search_type = node.search_type
        value = node.value
        negated = node.negated
        
        if search_type == SearchType.KEYWORD:
            # Keyword exact match - search via memory_keywords junction table
            sql = " EXISTS (SELECT 1 FROM memory_keywords mk JOIN keywords k ON mk.keyword_id = k.id WHERE mk.memory_id = m.id AND k.name = ?)"
            params = [value.lower()]
        
        elif search_type == SearchType.KEYWORD_SIM:
            # Keyword similarity - use embedding vectors
            # Get matching keyword IDs using vector similarity
            # Only use vector search if we have a real embedding model
            use_vector = False
            if self.searcher and self.searcher.embedding:
                test_emb = self.searcher.embedding.get("test")
                use_vector = test_emb is not None and np.linalg.norm(test_emb) > 0
            
            if use_vector:
                # Use threshold from query (e.g., "s:python@0.8") or default
                threshold = node.threshold
                matching_kw_ids = self.searcher._get_similar_keywords(value, threshold=threshold)
                if matching_kw_ids:
                    placeholders = ",".join("?" * len(matching_kw_ids))
                    sql = f" EXISTS (SELECT 1 FROM memory_keywords mk WHERE mk.memory_id = m.id AND mk.keyword_id IN ({placeholders}))"
                    params = matching_kw_ids
                else:
                    sql = " 1=0"
                    params = []
            else:
                # Fallback to LIKE if no embedding model
                sql = " EXISTS (SELECT 1 FROM memory_keywords mk JOIN keywords k ON mk.keyword_id = k.id WHERE mk.memory_id = m.id AND k.name LIKE ?)"
                params = [f"%{value.lower()}%"]
        
        elif search_type == SearchType.QUERY:
            # Text query - vector similarity search on memory content
            # Only use vector search if we have a real embedding model
            use_vector = False
            if self.searcher and self.searcher.embedding:
                test_emb = self.searcher.embedding.get("test")
                use_vector = test_emb is not None and np.linalg.norm(test_emb) > 0
            
            if use_vector:
                # Use threshold from query (e.g., "q:machine learning@0.3") or default
                threshold = node.threshold
                matching_memory_ids = self.searcher._get_similar_memories(value, threshold=threshold)
                if matching_memory_ids:
                    placeholders = ",".join("?" * len(matching_memory_ids))
                    sql = f" m.id IN ({placeholders})"
                    params = matching_memory_ids
                else:
                    sql = " 1=0"
                    params = []
            else:
                # Fallback to LIKE
                sql = " m.content LIKE ?"
                params = [f"%{value}%"]
        
        elif search_type == SearchType.DATE:
            # Date filter - uses created_at or last_accessed
            start, end = self.parse_date(value)
            if start and end:
                sql = " (m.created_at BETWEEN ? AND ? OR m.last_accessed BETWEEN ? AND ?)"
                params = [start, end, start, end]
            else:
                sql = " 1=1"
                params = []
        
        elif search_type == SearchType.PROPERTY:
            # Property filter - key=value format
            if '=' in value:
                prop_key, prop_val = value.split('=', 1)
                sql = " EXISTS (SELECT 1 FROM memory_properties mp WHERE mp.memory_id = m.id AND mp.key = ? AND mp.value = ?)"
                params = [prop_key.lower(), prop_val]
            else:
                sql = " 1=1"
                params = []
        else:
            sql = " 1=1"
            params = []
        
        # Handle negation
        if negated:
            sql = f"NOT ({sql.strip()})"
        
        return (sql, params)
    
    def _build_binary_query(self, node: SearchNode) -> tuple[str, list]:
        """Build SQL for binary AND/OR node."""
        left_sql, left_params = self.build_query(node.left)
        right_sql, right_params = self.build_query(node.right)
        
        operator = "AND" if node.operator == Operator.AND else "OR"
        
        sql = f"({left_sql}) {operator} ({right_sql})"
        params = left_params + right_params
        
        return (sql, params)
    
    def _build_unary_query(self, node: SearchNode) -> tuple[str, list]:
        """Build SQL for unary NOT node."""
        child_sql, child_params = self.build_query(node.child)
        
        sql = f"NOT ({child_sql})"
        
        return (sql, child_params)


class MemorySearcher:
    """Handles searching memories using the query DSL."""
    
    DEFAULT_SIMILARITY_THRESHOLD = 0.5  # Cosine similarity threshold
    
    def __init__(self, db_path: str, embedding_model=None, default_threshold: float = None):
        self.db_path = db_path
        self.embedding = embedding_model
        self.default_threshold = default_threshold or self.DEFAULT_SIMILARITY_THRESHOLD
    
    def _get_similar_keywords(self, query: str, threshold: float = None, limit: int = 100) -> list[int]:
        """Find keywords with similar embeddings to the query.
        
        Args:
            query: Search query text
            threshold: Similarity threshold (default from self.default_threshold)
            limit: Max keywords to consider
            
        Returns:
            List of keyword IDs with similarity above threshold
        """
        import sqlite3
        import numpy as np
        
        if not self.embedding:
            return []
        
        threshold = threshold or self.default_threshold
        
        # Get embedding for query
        query_embedding = self.embedding.get(query)
        if query_embedding.size == 0:
            return []
        
        # Get all keywords with embeddings
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, embedding FROM keywords WHERE embedding IS NOT NULL LIMIT ?",
                (limit,)
            ).fetchall()
        
        # Calculate cosine similarity
        matching_ids = []
        for row in rows:
            kw_id, embedding_blob = row
            if embedding_blob:
                kw_embedding = np.frombuffer(embedding_blob, dtype=np.float32)
                
                # Cosine similarity (already normalized, so just dot product)
                similarity = np.dot(query_embedding, kw_embedding)
                
                if similarity >= threshold:
                    matching_ids.append(kw_id)
        
        return matching_ids
    
    def _get_similar_memories(self, query: str, threshold: float = None, limit: int = 100) -> list[int]:
        """Find memories with similar content embeddings to the query.
        
        Args:
            query: Search query text
            threshold: Similarity threshold (default from self.default_threshold)
            limit: Max memories to consider
            
        Returns:
            List of memory IDs with similarity above threshold
        """
        import sqlite3
        import numpy as np
        
        if not self.embedding:
            return []
        
        threshold = threshold or self.default_threshold
        
        # Get embedding for query
        query_embedding = self.embedding.get(query)
        if query_embedding.size == 0:
            return []
        
        # Get all memories with embeddings
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, embedding FROM memories WHERE embedding IS NOT NULL LIMIT ?",
                (limit,)
            ).fetchall()
        
        # Calculate cosine similarity
        matching_ids = []
        for row in rows:
            mem_id, embedding_blob = row
            if embedding_blob:
                mem_embedding = np.frombuffer(embedding_blob, dtype=np.float32)
                
                # Cosine similarity
                similarity = np.dot(query_embedding, mem_embedding)
                
                if similarity >= threshold:
                    matching_ids.append(mem_id)
        
        return matching_ids
    
    def search(self, query_string: str, limit: int = 50) -> list[dict]:
        """Search memories using the query DSL.
        
        Args:
            query_string: Search query in DSL format
            limit: Maximum number of results
            
        Returns:
            List of matching memories with their data
        """
        import sqlite3
        
        # Parse the query - pass searcher for similarity searches
        parser = SearchParser(query_string, searcher=self)
        parser.tokenize()
        ast = parser.parse()
        
        # Build SQL
        where_clause, params = parser.build_query(ast)
        
        # Build full query - simpler version without json_objectagg
        sql = f"""
            SELECT m.id, m.content, m.created_at, m.last_updated as updated_at
            FROM memories m
            WHERE {where_clause}
            ORDER BY m.created_at DESC
            LIMIT ?
        """
        params.append(limit)
        
        # Execute
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                # Get keywords for this memory
                keywords = conn.execute(
                    """SELECT k.name FROM keywords k 
                       JOIN memory_keywords mk ON k.id = mk.keyword_id 
                       WHERE mk.memory_id = ?""",
                    (row['id'],)
                ).fetchall()
                keywords_list = [k['name'] for k in keywords]
                
                # Get properties for this memory
                props = conn.execute(
                    "SELECT key, value FROM memory_properties WHERE memory_id = ?",
                    (row['id'],)
                ).fetchall()
                properties_dict = {p['key']: p['value'] for p in props}
                
                results.append({
                    'id': row['id'],
                    'content': row['content'],
                    'keywords': keywords_list,
                    'properties': properties_dict,
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at'],
                })
            
            return results


if __name__ == "__main__":
    print("Testing SearchParser")
    print("=" * 60)
    
    # Test tokenizer and parser
    test_cases = [
        # Simple cases
        ("k:python", "keyword"),
        ("s:javascript", "keyword similarity"),
        ("q:machine learning", "text query"),
        ("p:role=user", "property"),
        ("d:last 30 days", "date"),
        
        # Boolean operators
        ("k:python AND k:coding", "AND operator"),
        ("k:python OR k:javascript", "OR operator"),
        ("NOT k:old", "NOT operator"),
        
        # Grouping
        ("(k:python OR s:javascript) AND NOT k:deprecated", "parentheses + NOT"),
        
        # Property with AND
        ("p:role=user AND p:importance=high", "multiple properties"),
        
        # Date ranges
        ("d:2025-01-01 to 2025-01-31", "date range"),
        ("d:2025-01-01T10:00 to 2025-01-01T18:00", "date with time range"),
        
        # Complex query
        ("(k:python OR s:javascript) AND q:machine learning AND p:role=user AND NOT k:deprecated", "complex query"),
    ]
    
    all_passed = True
    for query, description in test_cases:
        parser = SearchParser(query)
        tokens = parser.tokenize()
        ast = parser.parse()
        print(f"\n{description}")
        print(f"  Input:  {query!r}")
        print(f"  AST:   {ast}")
    
    print("\n" + "=" * 60)
    print("Testing Date Parser")
    print("=" * 60)
    
    date_tests = [
        "today",
        "yesterday",
        "last 7 days",
        "last 24 hours",
        "2025-01-01",
        "2025-01-01T10:30",
        "2025-01-01 to 2025-01-31",
        "2025-01-01T10:00 to 2025-01-01T18:00",
    ]
    
    for date_str in date_tests:
        parser = SearchParser("")
        result = parser.parse_date(date_str)
        print(f"  {date_str!r} -> {result}")
    
    print("\n" + "=" * 60)
    print("All tests completed!")
