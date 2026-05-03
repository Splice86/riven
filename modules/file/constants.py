"""Memory keyword constants for the file module.

================================================================================
DESIGN
================================================================================

Each open file is stored with a unique keyword and its line range stored
as direct columns (not in a JSON properties blob):

    keyword:  "open_file:{filename}"     # e.g. "open_file:main.py"
    path:     absolute path              # direct column
    line_start: int (0-indexed)          # direct column
    line_end: int or None (None = to end) # direct column

This means we don't need property-key constants or a search query DSL.
Keywords are for uniqueness, line ranges are for tracking.

================================================================================
"""

# Memory keyword prefix — all open file keywords start with this
MEMORY_KEYWORD_PREFIX = "open_file:"

# Convenience alias
MEMORY_KEYWORD = MEMORY_KEYWORD_PREFIX


# =============================================================================
# Keyword Builders
# =============================================================================

def make_open_file_keyword(filename: str) -> str:
    """Build a unique memory keyword for an open file.

    Each open file needs a unique keyword so set_open_file doesn't overwrite
    other open files. We use just the filename (not line range) in the keyword.

    Args:
        filename: Basename of the file (e.g., "example.py")

    Returns:
        Keyword like "open_file:example.py"
    """
    return f"{MEMORY_KEYWORD_PREFIX}{filename}"


def match_open_file_keyword(keyword: str) -> bool:
    """Check if a keyword is for an open file."""
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
