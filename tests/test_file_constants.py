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
)


class TestMemoryKeywordPrefix:
    """Tests for MEMORY_KEYWORD_PREFIX constant."""

    def test_prefix_is_correct_format(self):
        """The prefix should be 'open_file:' with colon."""
        assert MEMORY_KEYWORD_PREFIX == "open_file:"
        assert MEMORY_KEYWORD_PREFIX.endswith(":")

    def test_memory_keyword_alias(self):
        """MEMORY_KEYWORD should be the same as the prefix."""
        assert MEMORY_KEYWORD == MEMORY_KEYWORD_PREFIX


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
        assert match_open_file_keyword("open_file:app.py") is True
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


class TestConstantsIntegration:
    """Integration tests showing constants work together."""

    def test_keyword_uniqueness(self):
        """Verify different files get different keywords."""
        kw1 = make_open_file_keyword("file1.py")
        kw2 = make_open_file_keyword("file2.py")
        assert kw1 != kw2
        assert kw1 == "open_file:file1.py"
        assert kw2 == "open_file:file2.py"

    def test_keyword_uses_prefix(self):
        """Verify keywords use the prefix consistently."""
        keyword = make_open_file_keyword("example.py")
        assert keyword.startswith(MEMORY_KEYWORD_PREFIX)
        assert match_open_file_keyword(keyword) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
