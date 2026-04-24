"""Tests for file module constants."""

import pytest
import sys
sys.path.insert(0, "/home/david/Projects/riven_projects/riven_core")

from modules.file.constants import (
    MEMORY_KEYWORD_PREFIX,
    MEMORY_KEYWORD,
    make_open_file_keyword,
    match_open_file_keyword,
    extract_filename_from_keyword,
    build_open_file_search_query,
    build_search_query,
    PROP_FILENAME,
    PROP_PATH,
    PROP_LINE_START,
    PROP_LINE_END,
)


class TestMemoryKeywordPrefix:
    """Tests for MEMORY_KEYWORD_PREFIX constant."""
    
    def test_prefix_is_correct_format(self):
        """The prefix should be 'open_file:' with colon."""
        assert MEMORY_KEYWORD_PREFIX == "open_file:"
        assert MEMORY_KEYWORD_PREFIX.endswith(":")


class TestMakeOpenFileKeyword:
    """Tests for make_open_file_keyword function."""
    
    def test_basic_filename(self):
        """Test basic keyword generation."""
        result = make_open_file_keyword("example.py")
        assert result == "open_file:example.py"
    
    def test_filename_with_underscore(self):
        """Test filename with underscores."""
        result = make_open_file_keyword("test_file.txt")
        assert result == "open_file:test_file.txt"
    
    def test_filename_extraction_roundtrip(self):
        """Test that extract and make are inverse operations."""
        filename = "main.py"
        keyword = make_open_file_keyword(filename)
        extracted = extract_filename_from_keyword(keyword)
        assert extracted == filename


class TestMatchOpenFileKeyword:
    """Tests for match_open_file_keyword function."""
    
    def test_match_open_file(self):
        """Test matching open_file keywords."""
        assert match_open_file_keyword("open_file:main.py") is True
        assert match_open_file_keyword("open_file:app.py:10-50") is True
        assert match_open_file_keyword("open_file:utils/foo.py") is True
    
    def test_no_match_other_prefix(self):
        """Test not matching other prefixes."""
        assert match_open_file_keyword("file_change:path.txt") is False
        assert match_open_file_keyword("cwd") is False
        assert match_open_file_keyword("open_files") is False  # Missing colon


class TestExtractFilenameFromKeyword:
    """Tests for extract_filename_from_keyword function."""
    
    def test_extract_simple_filename(self):
        """Test extracting simple filename."""
        assert extract_filename_from_keyword("open_file:example.py") == "example.py"
    
    def test_extract_filename_with_underscore(self):
        """Test extracting filename with underscores."""
        assert extract_filename_from_keyword("open_file:test_file.txt") == "test_file.txt"
    
    def test_invalid_keyword_returns_none(self):
        """Test that invalid keyword returns None."""
        assert extract_filename_from_keyword("not_open_file:example.py") is None
        assert extract_filename_from_keyword("open_file") is None


class TestBuildSearchQuery:
    """Tests for build_search_query function - uses PROPERTIES not keywords."""
    
    def test_all_files_query(self):
        """Test query for all open files using property pattern."""
        result = build_search_query()
        assert result == "p:filename=*"
    
    def test_specific_filename_query(self):
        """Test query for specific filename using property."""
        result = build_search_query(filename="main.py")
        assert result == "p:filename=main.py"
    
    def test_query_with_line_filter(self):
        """Test query with line range filter."""
        result = build_search_query(additional_filters=["p:line_start>=50"])
        assert result == "p:filename=* AND p:line_start>=50"
    
    def test_query_with_date_filter(self):
        """Test query with date filter."""
        result = build_search_query(additional_filters=["d:last 7 days"])
        assert result == "p:filename=* AND d:last 7 days"
    
    def test_query_with_multiple_filters(self):
        """Test query with multiple additional filters."""
        result = build_search_query(additional_filters=["p:line_start>=50", "d:last 7 days"])
        assert result == "p:filename=* AND p:line_start>=50 AND d:last 7 days"


class TestBuildOpenFileSearchQuery:
    """Tests for build_open_file_search_query function - uses PROPERTIES."""
    
    def test_all_files_query(self):
        """Test query for all open files."""
        result = build_open_file_search_query()
        assert result == "p:filename=*"
    
    def test_specific_filename_query(self):
        """Test query for specific filename."""
        result = build_open_file_search_query(filename="main.py")
        assert result == "p:filename=main.py"
    
    def test_path_pattern_query(self):
        """Test query with path pattern."""
        result = build_open_file_search_query(path_pattern="*src/project*")
        assert result == "p:filename=* AND p:path=*src/project*"
    
    def test_filename_and_path_query(self):
        """Test query with both filename and path."""
        result = build_open_file_search_query(filename="*.py", path_pattern="*src*")
        assert result == "p:filename=*.py AND p:path=*src*"


class TestPropertyKeys:
    """Tests for property key constants."""
    
    def test_all_property_keys_defined(self):
        """All required property keys should be defined."""
        assert PROP_FILENAME == "filename"
        assert PROP_PATH == "path"
        assert PROP_LINE_START == "line_start"
        assert PROP_LINE_END == "line_end"


class TestConstantsIntegration:
    """Integration tests showing constants work together."""
    
    def test_keyword_uniqueness(self):
        """Verify different files get different keywords."""
        kw1 = make_open_file_keyword("file1.py")
        kw2 = make_open_file_keyword("file2.py")
        assert kw1 != kw2
        assert kw1 == "open_file:file1.py"
        assert kw2 == "open_file:file2.py"
    
    def test_query_format_uses_properties(self):
        """Verify queries use property filters (not keyword wildcards)."""
        # All files query uses property pattern
        query = build_search_query()
        assert query.startswith("p:filename=")
        assert "*" in query
        
        # Specific file query uses property
        query = build_search_query(filename="test.py")
        assert query == "p:filename=test.py"
    
    def test_data_in_properties_not_keyword(self):
        """Verify that filename is stored in properties, not encoded in keyword."""
        # The keyword is just for uniqueness in _set_memory
        keyword = make_open_file_keyword("example.py")
        assert keyword == "open_file:example.py"
        
        # But searching uses properties, not keywords
        search_query = build_search_query(filename="example.py")
        assert search_query == "p:filename=example.py"
        
        # This means we can search for all files using property pattern
        all_files_query = build_search_query()
        assert all_files_query == "p:filename=*"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
