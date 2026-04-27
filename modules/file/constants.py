"""Memory keyword constants for the file module.

These constants define how files are tracked in the memory database.
Centralizing them here makes it easy to modify the naming scheme if needed.

================================================================================
DESIGN PHILOSOPHY
================================================================================

We use a UNIQUE keyword per file (e.g., "open_file:main.py") to prevent
multiple files from overwriting each other, while storing all metadata
in PROPERTIES for flexible querying.

Keyword:     "open_file:{filename}"          # Unique per file (prevents overwrites)
Properties:  {path, line_start, line_end}    # All data in properties

This allows searches like:
  - k:open_file*                           # All open files (wildcard prefix)
  - k:open_file:main.py                    # Specific file
  - k:open_file:main.py AND p:line_start>=50  # Specific file at specific line

Note: We use keyword prefix "open_file:" to identify all open files, but
append filename to ensure uniqueness in _set_memory.

================================================================================
PROPERTY KEYS
================================================================================

All open_file memories store these properties:
  - filename:   basename of the file (e.g., "example.py")
  - path:       absolute path to the file (e.g., "/home/user/project/example.py")
  - line_start: starting line (0-indexed, string "0", "10", etc.)
  - line_end:   ending line ("*" for full file, or number as string)

================================================================================
SEARCH QUERY DSL (from riven_memory database/search.py)
================================================================================

PREFIXES:
  k:<keyword>   - Keyword exact match (e.g., "k:open_file:main.py")
  s:<keyword>   - Keyword similarity search (semantic)
  q:<text>      - Text content search (semantic)
  d:<date>      - Date filter
  p:<key=value> - Property filter
  l:<link_type> - Link traversal

WILDCARDS:
  k:open_file:*                         - All open files (any filename)
  k:open_file:main.*                    - All versions of main file

OPERATORS:
  AND - Both conditions must match
  OR  - Either condition must match
  NOT - Negate condition

PROPERTY VALUE PATTERNS:
  p:key=value         # Exact match
  p:key=prefix*       # Starts with
  p:key=*contains*    # Contains
  p:key=?single       # Single character wildcard
  p:key>=5            # Numeric comparison (>=, <=, <, >, !=)

COMMON SEARCH PATTERNS FOR OPEN FILES:

  # Get all open files for current session:
  query = "k:open_file:"              # Note: colon at end for prefix match

  # Get files with specific filename:
  query = "k:open_file:main.py"

  # Get files in a directory:
  query = "k:open_file: AND p:path=*src/project*"

  # Get files opened at specific line:
  query = "k:open_file: AND p:line_start>=50"

  # Get full files only (not partial ranges):
  query = "k:open_file: AND p:line_end=*"

================================================================================
"""

# Memory keyword prefix - used as prefix for all open file keywords
# Each file gets: "open_file:{filename}" (e.g., "open_file:main.py")
MEMORY_KEYWORD_PREFIX = "open_file:"

# Convenience - full keyword for single-file searches
MEMORY_KEYWORD = MEMORY_KEYWORD_PREFIX

# Default search limit when querying for open files
DEFAULT_SEARCH_LIMIT = 100

# Maximum results to return from a search
MAX_SEARCH_LIMIT = 1000


# =============================================================================
# Property Keys - use these when building search queries
# =============================================================================

PROP_FILENAME = "filename"
PROP_PATH = "path"
PROP_LINE_START = "line_start"
PROP_LINE_END = "line_end"
PROP_SCREEN_UIDS = "screen_uids"


# =============================================================================
# Keyword Builders
# =============================================================================

def make_open_file_keyword(filename: str) -> str:
    """Build a unique memory keyword for an open file.
    
    Each open file needs a unique keyword so _set_memory doesn't overwrite
    other open files. We use just the filename (not line range) in the keyword.
    
    Args:
        filename: Basename of the file (e.g., "example.py")
    
    Returns:
        Keyword like "open_file:example.py"
    """
    return f"{MEMORY_KEYWORD_PREFIX}{filename}"


def match_open_file_keyword(keyword: str) -> bool:
    """Check if a keyword is for an open file.
    
    Args:
        keyword: The keyword to check (e.g., "open_file:example.py")
    
    Returns:
        True if keyword starts with the open file prefix
    """
    return keyword.startswith(MEMORY_KEYWORD_PREFIX)


def extract_filename_from_keyword(keyword: str) -> str | None:
    """Extract the filename from an open file keyword.
    
    Args:
        keyword: Keyword like "open_file:example.py"
    
    Returns:
        The filename (e.g., "example.py") or None if not a valid keyword
    """
    if not keyword.startswith(MEMORY_KEYWORD_PREFIX):
        return None
    
    return keyword[len(MEMORY_KEYWORD_PREFIX):]


# =============================================================================
# Search Query Builders
# =============================================================================

def build_open_file_search_query(filename: str = None, path_pattern: str = None) -> str:
    """Build a search query for open file memories using properties.
    
    We use property patterns (not keyword prefix) because keyword matching
    is exact and doesn't support wildcards. Property patterns like "p:filename=*"
    can match all files.
    
    Args:
        filename: Optional specific filename (e.g., "main.py")
                  If None, matches all open files
        path_pattern: Optional path pattern to match (e.g., "*src/project*")
    
    Returns:
        Search query string using property filters
    
    Examples:
        build_open_file_search_query()                          # All: p:filename=*
        build_open_file_search_query(filename="main.py")        # Specific: p:filename=main.py
        build_open_file_search_query(path_pattern="*src*")      # In dir: p:path=*src*
    """
    parts = []
    
    if filename:
        parts.append(f"p:{PROP_FILENAME}={filename}")
    else:
        parts.append(f"p:{PROP_FILENAME}=*")  # Match all files
    
    if path_pattern:
        parts.append(f"p:{PROP_PATH}={path_pattern}")
    
    return " AND ".join(parts)


def build_search_query(filename: str = None, additional_filters: list = None) -> str:
    """Build a search query for open files using properties.
    
    We use property patterns (not keyword) because keyword matching is exact
    and doesn't support wildcards.
    
    Args:
        filename: Optional specific filename to match
        additional_filters: Optional list of filter conditions
                           (e.g., ["p:line_start>=50", "d:last 7 days"])
    
    Returns:
        Search query string using property filters
    """
    parts = []
    
    if filename:
        parts.append(f"p:{PROP_FILENAME}={filename}")
    else:
        parts.append(f"p:{PROP_FILENAME}=*")  # Match all files
    
    if additional_filters:
        parts.extend(additional_filters)
    
    return " AND ".join(parts)
