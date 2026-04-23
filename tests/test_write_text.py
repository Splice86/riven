"""Tests for write_text in file module."""

import pytest
from unittest.mock import patch, AsyncMock
from modules.file import write_text


class TestWriteText:
    @pytest.mark.asyncio
    async def test_write_text_creates_file(self, tmp_path):
        """write_text creates the file with given content."""
        path = tmp_path / "new_file.txt"
        result = await write_text(str(path), "hello world")

        assert path.read_text() == "hello world"
        assert "new_file.txt" in result
        assert "1 lines" in result

    @pytest.mark.asyncio
    async def test_write_text_overwrites_existing(self, tmp_path):
        """write_text overwrites an existing file."""
        path = tmp_path / "existing.txt"
        path.write_text("old content")

        result = await write_text(str(path), "new content")

        assert path.read_text() == "new content"
        assert "existing.txt" in result

    @pytest.mark.asyncio
    async def test_write_text_creates_intermediate_dirs(self, tmp_path):
        """write_text creates parent directories if they don't exist."""
        path = tmp_path / "subdir" / "nested" / "file.txt"

        result = await write_text(str(path), "deep content", create_parent_dirs=True)

        assert path.read_text() == "deep content"
        assert "file.txt" in result

    @pytest.mark.asyncio
    async def test_write_text_multiline_content(self, tmp_path):
        """write_text handles multiline content correctly."""
        path = tmp_path / "multi.txt"
        content = "line one\nline two\nline three"

        result = await write_text(str(path), content)

        assert path.read_text() == content
        assert "3 lines" in result
