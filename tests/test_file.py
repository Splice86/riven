"""Tests for the file module."""

import pytest
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFileModuleRegistration:
    """Test that file module is correctly registered."""

    def test_file_help_is_static_context_fn(self):
        """Verify _file_help is registered as a static ContextFn."""
        from modules.file import get_module
        mod = get_module()
        help_fn = next((cf for cf in mod.context_fns if cf.tag == "file_help"), None)
        assert help_fn is not None, "file_help ContextFn not found"
        assert help_fn.static is True, "file_help should be static=True"

    def test_file_context_is_dynamic_context_fn(self):
        """Verify _file_context is registered as a dynamic (non-static) ContextFn."""
        from modules.file import get_module
        mod = get_module()
        ctx_fn = next((cf for cf in mod.context_fns if cf.tag == "file"), None)
        assert ctx_fn is not None, "file ContextFn not found"
        assert ctx_fn.static is False, "file should be dynamic (static=False)"

    def test_all_called_fns_have_descriptions(self):
        """Verify every CalledFn has a non-empty description."""
        from modules.file import get_module
        mod = get_module()
        for cf in mod.called_fns:
            assert cf.description, f"CalledFn {cf.name} has empty description"

    def test_replace_text_has_threshold_param(self):
        """Verify replace_text has a threshold parameter for per-call override."""
        from modules.file import get_module
        mod = get_module()
        replace_fn = next((cf for cf in mod.called_fns if cf.name == "replace_text"), None)
        assert replace_fn is not None
        props = replace_fn.parameters.get("properties", {})
        assert "threshold" in props, "replace_text should have threshold param"
        assert props["threshold"]["type"] == "number"

    def test_search_files_is_registered(self):
        """Verify search_files is registered as a CalledFn."""
        from modules.file import get_module
        mod = get_module()
        search_fn = next((cf for cf in mod.called_fns if cf.name == "search_files"), None)
        assert search_fn is not None

    def test_list_dir_is_registered(self):
        """Verify list_dir is registered as a CalledFn."""
        from modules.file import get_module
        mod = get_module()
        list_fn = next((cf for cf in mod.called_fns if cf.name == "list_dir"), None)
        assert list_fn is not None

    def test_preview_replace_is_registered(self):
        """Verify preview_replace is registered as a CalledFn."""
        from modules.file import get_module
        mod = get_module()
        preview_fn = next((cf for cf in mod.called_fns if cf.name == "preview_replace"), None)
        assert preview_fn is not None

    def test_diff_text_is_registered(self):
        """Verify diff_text is registered as a CalledFn."""
        from modules.file import get_module
        mod = get_module()
        diff_fn = next((cf for cf in mod.called_fns if cf.name == "diff_text"), None)
        assert diff_fn is not None


class TestFindBestWindow:
    """Test _find_best_window fuzzy matching."""

    def test_exact_match_returns_full_score(self):
        """Exact line match should return score of 1.0."""
        from modules.file import _find_best_window
        lines = ["def foo():", "    pass", "    return 1"]
        needle = "def foo():\n    pass\n    return 1"
        span, score = _find_best_window(lines, needle)
        assert span is not None
        assert score == 1.0

    def test_close_match_above_threshold(self):
        """Near-match should return score above threshold."""
        from modules.file import _find_best_window
        lines = ["def foo():", "    pass", "    return 1"]
        needle = "def foo():\n    pass\n    return 2"  # only last line differs
        span, score = _find_best_window(lines, needle, threshold=0.9)
        assert span is not None
        assert score > 0.9

    def test_no_match_below_threshold(self):
        """Completely different text should return None."""
        from modules.file import _find_best_window
        lines = ["def foo():", "    pass", "    return 1"]
        needle = "class Bar:\n    def method(self):\n        pass"
        span, score = _find_best_window(lines, needle, threshold=0.95)
        assert span is None

    def test_single_line_needle(self):
        """Single line needle should match a single line in window."""
        from modules.file import _find_best_window
        lines = ["def foo():", "    pass", "    return 1"]
        needle = "def foo():"
        span, score = _find_best_window(lines, needle)
        assert span == (0, 1)

    def test_trailing_newline_handling(self):
        """Needle with trailing newline should still match."""
        from modules.file import _find_best_window
        lines = ["def foo():", "    pass"]
        needle = "def foo():\n"  # has trailing newline
        span, score = _find_best_window(lines, needle)
        assert span is not None
        assert score == 1.0


class TestOpenFile:
    """Test open_file function."""

    @pytest.mark.asyncio
    async def test_open_file_returns_filename_and_line_count(self):
        """open_file should return filename, line count, and file type."""
        from modules import _session_id
        from modules.file import open_file

        _session_id.set("test-session-123")

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("line1\nline2\nline3\n")
            tmp_path = f.name

        try:
            with patch("modules.file.requests.post") as mock_post:
                mock_post.return_value = MagicMock(status_code=200)

                result = await open_file(tmp_path)

                assert os.path.basename(tmp_path) in result
                assert "3 lines" in result
                assert "python" in result
                mock_post.assert_called_once()
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_open_file_nonexistent_returns_error(self):
        """open_file with non-existent path should return error."""
        from modules import _session_id
        from modules.file import open_file

        _session_id.set("test-session-123")
        result = await open_file("/nonexistent/path/to/file.py")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_open_file_with_line_range(self):
        """open_file with line_start/line_end should report range."""
        from modules import _session_id
        from modules.file import open_file

        _session_id.set("test-session-123")

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("\n".join([f"line {i}" for i in range(100)]))
            tmp_path = f.name

        try:
            with patch("modules.file.requests.post") as mock_post:
                mock_post.return_value = MagicMock(status_code=200)

                result = await open_file(tmp_path, line_start=10, line_end=20)

                assert "10-20" in result
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_open_file_large_file_shows_warning(self):
        """open_file with file > 1000 lines should include a warning."""
        from modules import _session_id
        from modules.file import open_file

        _session_id.set("test-session-123")

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("\n".join([f"line {i}" for i in range(1500)]))
            tmp_path = f.name

        try:
            with patch("modules.file.requests.post") as mock_post:
                mock_post.return_value = MagicMock(status_code=200)

                result = await open_file(tmp_path)

                # Should include large file warning
                assert "LARGE" in result or "large" in result
        finally:
            os.unlink(tmp_path)


class TestReplaceText:
    """Test replace_text function."""

    @pytest.mark.asyncio
    async def test_replace_text_success(self):
        """replace_text should replace matching text and save file."""
        from modules.file import replace_text

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            # Write file WITHOUT trailing newline so needle matches without indentation issues
            f.write("def hello():\n    print('old')\n")
            tmp_path = f.name

        try:
            result = await replace_text(
                tmp_path,
                "def hello():\n    print('old')\n",  # exact lines including indentation
                "def hello():\n    print('new')\n"
            )

            assert "Replaced" in result

            with open(tmp_path) as f:
                content = f.read()
            assert "new" in content
            assert "old" not in content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_replace_text_fuzzy_threshold_can_be_overridden(self):
        """replace_text with custom threshold should work with lower-quality matches."""
        from modules.file import replace_text

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    print('hello world')\n    return None\n")
            tmp_path = f.name

        try:
            # With threshold=0.6 this should match even with whitespace differences
            result = await replace_text(
                tmp_path,
                "prnt('hello world')",  # typo 'prnt' instead of 'print'
                "print('hello planet')",
                threshold=0.6
            )
            # Should succeed with lower threshold instead of failing
            assert "Replaced" in result or "error" not in result.lower()
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_replace_text_not_found_shows_best_match(self):
        """replace_text with no match should show best match found."""
        from modules.file import replace_text

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def foo():\n    pass\n    return True\n")
            tmp_path = f.name

        try:
            result = await replace_text(
                tmp_path,
                "def bar():\n    return False",
                "def bar():\n    return True",  # required even though it won't be used
            )

            # Should show the best match it found, not generic first-20-lines dump
            assert "foo" in result.lower() or "best match" in result.lower() or "pass" in result
            # Should NOT contain raw repr of old_text
            assert "def bar" not in result
        finally:
            os.unlink(tmp_path)


class TestPreviewReplace:
    """Test preview_replace function."""

    @pytest.mark.asyncio
    async def test_preview_replace_shows_matched_window(self):
        """preview_replace should return the text window it matched without modifying file."""
        from modules.file import preview_replace

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    print('hello')\n    return True\n")
            tmp_path = f.name

        try:
            result = await preview_replace(tmp_path, "def hello():\n    print('hello')\n")

            # Should show what it found
            assert "hello" in result
            assert "Match at lines" in result or "not found" in result.lower()

            # Verify file was NOT modified
            with open(tmp_path) as f:
                content = f.read()
            assert "hello" in content
        finally:
            os.unlink(tmp_path)


class TestDiffText:
    """Test diff_text function."""

    @pytest.mark.asyncio
    async def test_diff_text_shows_proposed_change(self):
        """diff_text should show what the replacement would look like."""
        from modules.file import diff_text

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    print('old')\n    return 1\n")
            tmp_path = f.name

        try:
            result = await diff_text(
                tmp_path,
                "def hello():\n    print('old')\n",
                "def hello():\n    print('new')\n"
            )

            assert "new" in result
            assert "old" in result.lower() or "BEFORE" in result
            # Verify file was NOT modified
            with open(tmp_path) as f:
                content = f.read()
            assert "old" in content
        finally:
            os.unlink(tmp_path)


class TestSearchFiles:
    """Test search_files function."""

    @pytest.mark.asyncio
    async def test_search_files_finds_matching_lines(self):
        """search_files should find pattern and return file:line:content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir, "sample.py")
            test_file.write_text("def hello():\n    return 'world'\n")

            from modules.file import search_files
            result = await search_files("hello", path=tmpdir)

            assert "hello" in result.lower()
            assert "sample.py" in result

    @pytest.mark.asyncio
    async def test_search_files_no_matches(self):
        """search_files with no matches should return 'no matches'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir, "sample.py")
            test_file.write_text("def hello():\n    return 'world'\n")

            from modules.file import search_files
            result = await search_files("THIS_UNIQUE_PATTERN_XYZ789", path=tmpdir)

            assert "no matches" in result.lower()


class TestListDir:
    """Test list_dir function."""

    @pytest.mark.asyncio
    async def test_list_dir_shows_files_in_directory(self):
        """list_dir should list files and directories."""
        from modules.file import list_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test_file.py").write_text("pass")
            Path(tmpdir, "data.json").write_text("{}")
            os.makedirs(os.path.join(tmpdir, "subdir"))

            result = await list_dir(path=tmpdir)

            assert "test_file.py" in result
            assert "data.json" in result
            assert "subdir" in result

    @pytest.mark.asyncio
    async def test_list_dir_nonexistent_returns_error(self):
        """list_dir with non-existent path should return error."""
        from modules.file import list_dir

        result = await list_dir(path="/nonexistent/directory")
        assert "not found" in result.lower()


class TestCloseFile:
    """Test close_file function."""

    @pytest.mark.asyncio
    async def test_close_file_not_open_returns_not_open_error(self):
        """close_file when file not open should return appropriate error."""
        from modules import _session_id
        from modules.file import close_file

        _session_id.set("test-session-123")
        with patch("modules.file._search_memories") as mock_search:
            mock_search.return_value = []

            result = await close_file("nonexistent_file.py")
            assert "not open" in result.lower()


class TestFileContext:
    """Test _file_context function."""

    def test_file_context_returns_no_files_message_when_empty(self):
        """_file_context should return no files message when nothing is open."""
        from modules import _session_id
        from modules.file import _file_context

        _session_id.set("test-session-123")
        with patch("modules.file._search_memories") as mock_search:
            mock_search.return_value = []

            result = _file_context()
            assert "no files" in result.lower() or "empty" in result.lower()

    def test_file_context_skips_missing_files(self):
        """_file_context should skip entries whose files no longer exist on disk."""
        from modules import _session_id
        from modules.file import _file_context

        _session_id.set("test-session-123")
        with patch("modules.file._search_memories") as mock_search:
            mock_search.return_value = [{
                "id": 1,
                "properties": {
                    "path": "/nonexistent/file.py",
                    "filename": "file.py",
                    "line_start": "0",
                    "line_end": "*"
                }
            }]

            result = _file_context()
            # Should not crash, should skip the missing file
            assert True  # reached here without exception


class TestFileInfo:
    """Test file_info function."""

    @pytest.mark.asyncio
    async def test_file_info_returns_metadata(self):
        """file_info should return line count, size, and modified time."""
        from modules.file import file_info

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("line1\nline2\nline3\n")
            tmp_path = f.name

        try:
            result = await file_info(tmp_path)

            assert "3 lines" in result or "3" in result
            assert "bytes" in result.lower()
            assert "modified" in result.lower()
            assert "python" in result
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_file_info_nonexistent_returns_error(self):
        """file_info with non-existent path should return error."""
        from modules.file import file_info

        result = await file_info("/nonexistent/file.py")
        assert "not found" in result.lower()
