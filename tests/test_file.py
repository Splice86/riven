"""Tests for the file module."""

import pytest
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestEditResult:
    """Test EditResult dataclass for structured responses."""

    def test_successful_result_creates_string(self):
        """EditResult.to_string() formats success message correctly."""
        from modules.file import EditResult

        result = EditResult(
            success=True,
            path="/tmp/test.py",
            message="Replaced lines 10-15",
            changed=True,
            line_start=10,
            line_end=15,
            similarity=0.95,
        )

        output = result.to_string()

        assert "✅" in output
        assert "Replaced lines 10-15" in output
        assert "Lines 10-15" in output
        assert "95%" in output

    def test_failed_result_creates_string(self):
        """EditResult.to_string() formats error message correctly."""
        from modules.file import EditResult

        result = EditResult(
            success=False,
            path="/tmp/test.py",
            message="Text not found",
            similarity=0.72,
        )

        output = result.to_string()

        assert "❌" in output
        assert "Text not found" in output
        assert "72%" in output

    def test_failed_result_with_syntax_error(self):
        """EditResult shows syntax error details for failed Python edits."""
        from modules.file import EditResult

        result = EditResult(
            success=False,
            path="/tmp/test.py",
            message="Syntax validation failed",
            syntax_error="Syntax error at line 5: invalid syntax",
        )

        output = result.to_string()

        assert "Syntax validation failed" in output
        assert "Syntax error" in output
        assert "line 5" in output

    def test_result_with_diff(self):
        """EditResult includes diff in output when present."""
        from modules.file import EditResult

        result = EditResult(
            success=True,
            path="/tmp/test.py",
            message="Applied replacement",
            changed=True,
            diff="--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-old\n+new",
        )

        output = result.to_string()

        assert "--- a/test.py" in output
        assert "+new" in output

    def test_result_optional_fields_omitted_when_none(self):
        """EditResult omits optional fields when they are None."""
        from modules.file import EditResult

        result = EditResult(
            success=True,
            path="/tmp/test.py",
            message="Success",
        )

        output = result.to_string()

        assert "Success" in output
        assert "Lines" not in output
        assert "%" not in output

    def test_str_dunder_calls_to_string(self):
        """str(result) returns same as result.to_string()."""
        from modules.file import EditResult

        result = EditResult(
            success=True,
            path="/tmp/test.py",
            message="Success",
        )

        assert str(result) == result.to_string()


class TestReplacement:
    """Test Replacement dataclass for batch operations."""

    def test_creates_replacement_with_valid_data(self):
        """Replacement accepts old_str and new_str."""
        from modules.file import Replacement

        rep = Replacement(old_str="old text", new_str="new text")

        assert rep.old_str == "old text"
        assert rep.new_str == "new text"

    def test_rejects_non_string_old_str(self):
        """Replacement raises TypeError if old_str is not a string."""
        from modules.file import Replacement

        with pytest.raises(TypeError):
            Replacement(old_str=123, new_str="new text")

    def test_rejects_non_string_new_str(self):
        """Replacement raises TypeError if new_str is not a string."""
        from modules.file import Replacement

        with pytest.raises(TypeError):
            Replacement(old_str="old text", new_str=456)

    def test_empty_strings_allowed(self):
        """Replacement allows empty strings (useful for insert/delete)."""
        from modules.file import Replacement

        rep = Replacement(old_str="", new_str="inserted")
        assert rep.old_str == ""
        assert rep.new_str == "inserted"

        rep2 = Replacement(old_str="deleted", new_str="")
        assert rep2.old_str == "deleted"
        assert rep2.new_str == ""


class TestFileEditSession:
    """Test FileEditSession dataclass for tracking edit operations."""

    def test_creates_session_with_required_fields(self):
        """FileEditSession requires session_id and tool_name."""
        from modules.file import FileEditSession

        session = FileEditSession(
            session_id="edit_abc123",
            tool_name="batch_edit",
        )

        assert session.session_id == "edit_abc123"
        assert session.tool_name == "batch_edit"
        assert session.status == "pending"
        assert session.files == []
        assert session.operations == 0

    def test_creates_session_with_all_fields(self):
        """FileEditSession accepts all optional fields."""
        from modules.file import FileEditSession

        session = FileEditSession(
            session_id="edit_xyz789",
            tool_name="single_edit",
            files=["/tmp/file1.py", "/tmp/file2.py"],
            operations=2,
            status="completed",
            diff="--- diff here ---",
            original_snapshots={"/tmp/file1.py": "original content"},
            modified_snapshots={"/tmp/file1.py": "new content"},
        )

        assert len(session.files) == 2
        assert session.operations == 2
        assert session.status == "completed"
        assert "/tmp/file1.py" in session.original_snapshots

    def test_to_dict_serialization(self):
        """FileEditSession.to_dict() returns JSON-safe dict."""
        from modules.file import FileEditSession

        session = FileEditSession(
            session_id="edit_test",
            tool_name="test_tool",
        )

        data = session.to_dict()

        assert data["session_id"] == "edit_test"
        assert data["tool_name"] == "test_tool"
        assert isinstance(data["created_at"], str)  # ISO format string

    def test_from_dict_deserialization(self):
        """FileEditSession.from_dict() recreates session from dict."""
        from modules.file import FileEditSession

        data = {
            "session_id": "edit_restored",
            "tool_name": "restored_tool",
            "files": ["/tmp/restored.py"],
            "operations": 1,
            "status": "completed",
            "created_at": "2025-01-15T10:30:00",
            "diff": "--- restored ---",
            "original_snapshots": {},
            "modified_snapshots": {},
        }

        session = FileEditSession.from_dict(data)

        assert session.session_id == "edit_restored"
        assert session.tool_name == "restored_tool"
        assert session.created_at == datetime(2025, 1, 15, 10, 30, 0)
        assert session.status == "completed"

    def test_status_defaults_to_pending(self):
        """FileEditSession status defaults to 'pending'."""
        from modules.file import FileEditSession

        session = FileEditSession(
            session_id="edit_default",
            tool_name="test",
        )

        assert session.status == "pending"

    def test_valid_statuses(self):
        """FileEditSession accepts all valid status values."""
        from modules.file import FileEditSession

        for status in ["pending", "completed", "failed", "rolled_back"]:
            session = FileEditSession(
                session_id=f"edit_{status}",
                tool_name="test",
                status=status,
            )
            assert session.status == status


class TestAtomicWrite:
    """Test _atomic_write for robust file writing."""

    def test_atomic_write_creates_file(self):
        """_atomic_write creates the file with correct content."""
        from modules.file import _atomic_write

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            content = "Hello, atomic world!\n"
            _atomic_write(tmp_path, content)

            with open(tmp_path, 'r') as f:
                assert f.read() == content
        finally:
            os.unlink(tmp_path)

    def test_atomic_write_overwrites_existing(self):
        """_atomic_write overwrites existing file content."""
        from modules.file import _atomic_write

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            tmp.write("original content")
            tmp_path = tmp.name

        try:
            new_content = "new content\n"
            _atomic_write(tmp_path, new_content)

            with open(tmp_path, 'r') as f:
                assert f.read() == new_content
        finally:
            os.unlink(tmp_path)

    def test_atomic_write_creates_parent_dirs(self):
        """_atomic_write creates parent directories if needed."""
        from modules.file import _atomic_write

        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "a", "b", "c", "file.txt")

            _atomic_write(nested_path, "nested content\n")

            with open(nested_path, 'r') as f:
                assert f.read() == "nested content\n"

    def test_atomic_write_handles_empty_content(self):
        """_atomic_write handles empty content correctly."""
        from modules.file import _atomic_write

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            _atomic_write(tmp_path, "")

            with open(tmp_path, 'r') as f:
                assert f.read() == ""
        finally:
            os.unlink(tmp_path)

    def test_atomic_write_handles_large_content(self):
        """_atomic_write handles large content correctly."""
        from modules.file import _atomic_write

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            large_content = "x" * 100000  # 100KB
            _atomic_write(tmp_path, large_content)

            with open(tmp_path, 'r') as f:
                assert len(f.read()) == 100000
        finally:
            os.unlink(tmp_path)

    def test_atomic_write_cleans_up_temp_on_error(self):
        """_atomic_write cleans up temp file on error."""
        from modules.file import _atomic_write

        import unittest.mock

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = os.path.join(tmpdir, "file.txt")
            content = "test content"

            # Mock os.replace to raise an error after the write succeeds
            original_replace = os.replace
            call_count = [0]

            def mock_replace(src, dst):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise OSError("mocked error")
                return original_replace(src, dst)

            with unittest.mock.patch('os.replace', side_effect=mock_replace):
                with pytest.raises(OSError):
                    _atomic_write(temp_path, content)

            # No temp files should remain in the directory
            files_after = os.listdir(tmpdir)
            assert len(files_after) == 0, f"Temp file not cleaned up: {files_after}"


class TestVerifyWrite:
    """Test _verify_write for post-write verification."""

    def test_verify_write_returns_true_for_match(self):
        """_verify_write returns True when content matches."""
        from modules.file import _verify_write

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            tmp.write("test content")
            tmp_path = tmp.name

        try:
            assert _verify_write(tmp_path, "test content") is True
        finally:
            os.unlink(tmp_path)

    def test_verify_write_returns_false_for_mismatch(self):
        """_verify_write returns False when content differs."""
        from modules.file import _verify_write

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            tmp.write("original content")
            tmp_path = tmp.name

        try:
            assert _verify_write(tmp_path, "different content") is False
        finally:
            os.unlink(tmp_path)

    def test_verify_write_returns_false_for_missing_file(self):
        """_verify_write returns False for non-existent file."""
        from modules.file import _verify_write

        assert _verify_write("/nonexistent/path/file.txt", "content") is False

    def test_verify_write_returns_false_on_read_error(self):
        """_verify_write returns False when file can't be read."""
        from modules.file import _verify_write

        # Even if file exists but can't be read
        # (this is hard to test without chmod tricks, so we test missing file)
        assert _verify_write("/root/.hidden_file", "content") is False


class TestSanitizeContent:
    """Test _sanitize_content for encoding edge cases."""

    def test_clean_content_unchanged(self):
        """_sanitize_content leaves clean content unchanged."""
        from modules.file import _sanitize_content

        content = "Hello, world!\nThis is normal text."
        assert _sanitize_content(content) == content

    def test_removes_high_surrogates(self):
        """_sanitize_content removes high surrogates (U+D800-U+DBFF)."""
        from modules.file import _sanitize_content

        # U+D800 is a high surrogate
        content = "Hello\ud800World"
        result = _sanitize_content(content)
        assert "\ud800" not in result

    def test_removes_low_surrogates(self):
        """_sanitize_content removes low surrogates (U+DC00-U+DFFF)."""
        from modules.file import _sanitize_content

        # U+DFFF is a low surrogate
        content = "Hello\udfffWorld"
        result = _sanitize_content(content)
        assert "\udfff" not in result

    def test_replaces_surrogates_with_replacement_char(self):
        """_sanitize_content replaces surrogates with Unicode replacement char."""
        from modules.file import _sanitize_content

        content = "Test\ud800 surrogate"
        result = _sanitize_content(content)
        assert "\ufffd" in result  # Unicode replacement character

    def test_handles_mixed_surrogates(self):
        """_sanitize_content handles mixed surrogate pairs."""
        from modules.file import _sanitize_content

        # Invalid surrogate sequence
        content = "Line1\nLine2\ud800\udfff\nLine3"
        result = _sanitize_content(content)
        # Should not raise, should replace surrogates
        assert isinstance(result, str)

    def test_handles_empty_string(self):
        """_sanitize_content handles empty string."""
        from modules.file import _sanitize_content

        assert _sanitize_content("") == ""

    def test_handles_unicode_content(self):
        """_sanitize_content preserves valid Unicode."""
        from modules.file import _sanitize_content

        content = "Hello, 世界! 🎉 émoji"
        assert _sanitize_content(content) == content


class TestValidatePython:
    """Test _validate_python for syntax checking."""

    def test_valid_python_returns_true(self):
        """_validate_python returns True for valid Python code."""
        from modules.file import _validate_python

        valid_code = "def hello():\n    return 'world'\n"
        is_valid, error = _validate_python(valid_code)
        assert is_valid is True
        assert error is None

    def test_valid_python_with_complex_code(self):
        """_validate_python handles complex but valid Python."""
        from modules.file import _validate_python

        valid_code = """
class MyClass:
    def __init__(self, x):
        self.x = x

    def method(self, y):
        return self.x + y

result = MyClass(10).method(5)
"""
        is_valid, error = _validate_python(valid_code)
        assert is_valid is True
        assert error is None

    def test_syntax_error_returns_false(self):
        """_validate_python returns False for invalid syntax."""
        from modules.file import _validate_python

        invalid_code = "def broken(:\n    pass"  # Missing parameter name
        is_valid, error = _validate_python(invalid_code)
        assert is_valid is False
        assert error is not None
        assert "Syntax error" in error

    def test_syntax_error_includes_line_number(self):
        """_validate_python includes line number in error message."""
        from modules.file import _validate_python

        invalid_code = "line1\nline2\nline3\n    bad indentation here"
        is_valid, error = _validate_python(invalid_code)
        assert is_valid is False
        assert "line 4" in error or "line 4" in str(error)

    def test_empty_string_returns_true(self):
        """_validate_python accepts empty string."""
        from modules.file import _validate_python

        is_valid, error = _validate_python("")
        assert is_valid is True

    def test_whitespace_only_returns_true(self):
        """_validate_python accepts whitespace-only content."""
        from modules.file import _validate_python

        is_valid, error = _validate_python("   \n\n   \t   \n")
        assert is_valid is True


class TestModuleRegistration:
    """Test module registration and CalledFn/ContextFn setup."""

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


class TestCountTokens:
    """Tests for _count_tokens() helper."""

    def test_count_tokens_basic(self):
        """_count_tokens should return rough token count."""
        from modules.file import _count_tokens

        assert _count_tokens("hello world") == 2
        assert _count_tokens("a" * 8) == 2  # 8 chars / 4
        assert _count_tokens("") == 0

    def test_count_tokens_large_text(self):
        """_count_tokens should handle large texts."""
        from modules.file import _count_tokens

        text = "x" * 1000
        assert _count_tokens(text) == 250  # 1000 / 4


class TestFileType:
    """Tests for _file_type() helper."""

    def test_file_type_python(self):
        """_file_type should return 'python' for .py files."""
        from modules.file import _file_type

        assert _file_type("script.py") == "python"
        assert _file_type("/path/to/module.py") == "python"

    def test_file_type_yaml(self):
        """_file_type should return 'yaml' for .yaml and .yml files."""
        from modules.file import _file_type

        assert _file_type("config.yaml") == "yaml"
        assert _file_type("config.yml") == "yaml"

    def test_file_type_json(self):
        """_file_type should return 'json' for .json files."""
        from modules.file import _file_type

        assert _file_type("data.json") == "json"

    def test_file_type_markdown(self):
        """_file_type should return 'markdown' for .md files."""
        from modules.file import _file_type

        assert _file_type("README.md") == "markdown"

    def test_file_type_shell(self):
        """_file_type should return 'shell' for shell scripts."""
        from modules.file import _file_type

        assert _file_type("script.sh") == "shell"
        assert _file_type("script.bash") == "shell"
        assert _file_type("script.zsh") == "shell"

    def test_file_type_rust(self):
        """_file_type should return 'rust' for .rs files."""
        from modules.file import _file_type

        assert _file_type("main.rs") == "rust"

    def test_file_type_javascript(self):
        """_file_type should return 'javascript' for .js files."""
        from modules.file import _file_type

        assert _file_type("app.js") == "javascript"
        assert _file_type("app.ts") == "typescript"

    def test_file_type_unknown(self):
        """_file_type should return extension for unknown types."""
        from modules.file import _file_type

        assert _file_type("random.xyz") == "xyz"
        assert _file_type("noextension") == "file"


class TestGetCwd:
    """Tests for _get_cwd() helper."""

    def test_get_cwd_returns_string(self):
        """_get_cwd should return a string."""
        from modules.file import _get_cwd

        result = _get_cwd()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_cwd_is_valid_path(self):
        """_get_cwd should return a valid path."""
        from modules.file import _get_cwd

        result = _get_cwd()
        assert os.path.isabs(result) or result == "."


class TestFileHelp:
    """Tests for _file_help() helper."""

    def test_file_help_returns_string(self):
        """_file_help should return a string."""
        from modules.file import _file_help

        result = _file_help()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_file_help_contains_tools(self):
        """_file_help should document file tools."""
        from modules.file import _file_help

        result = _file_help()
        assert "pwd" in result
        assert "chdir" in result
        assert "open_file" in result
        assert "replace_text" in result

    def test_file_help_contains_workflow(self):
        """_file_help should document the workflow."""
        from modules.file import _file_help

        result = _file_help()
        assert "Workflow" in result
        assert "Guidelines" in result


class TestGenerateUnifiedDiff:
    """Tests for _generate_unified_diff() helper."""

    def test_generate_unified_diff_basic(self):
        """_generate_unified_diff should generate diff output."""
        from modules.file import _generate_unified_diff

        old_lines = ["line1\n", "line2\n", "line3\n"]
        new_lines = ["line1\n", "line2 modified\n", "line3\n"]

        result = _generate_unified_diff("/test/file.py", old_lines, new_lines)

        assert "---" in result
        assert "+++" in result
        assert "-line2" in result
        assert "+line2 modified" in result

    def test_generate_unified_diff_additions(self):
        """_generate_unified_diff should show additions."""
        from modules.file import _generate_unified_diff

        old_lines = ["line1\n"]
        new_lines = ["line1\n", "line2\n"]

        result = _generate_unified_diff("/test/file.py", old_lines, new_lines)

        assert "+++" in result
        assert "+line2" in result

    def test_generate_unified_diff_deletions(self):
        """_generate_unified_diff should show deletions."""
        from modules.file import _generate_unified_diff

        old_lines = ["line1\n", "line2\n"]
        new_lines = ["line1\n"]

        result = _generate_unified_diff("/test/file.py", old_lines, new_lines)

        assert "---" in result
        assert "-line2" in result

    def test_generate_unified_diff_no_changes(self):
        """_generate_unified_diff should return empty for identical content."""
        from modules.file import _generate_unified_diff

        lines = ["line1\n", "line2\n"]
        result = _generate_unified_diff("/test/file.py", lines, lines)

        # unified_diff returns empty when no changes
        assert result == ""

    def test_generate_unified_diff_custom_context(self):
        """_generate_unified_diff should respect context parameter."""
        from modules.file import _generate_unified_diff

        old_lines = ["line1\n", "line2\n", "line3\n", "line4\n", "line5\n"]
        new_lines = ["line1\n", "line2 modified\n", "line3\n", "line4\n", "line5\n"]

        result = _generate_unified_diff("/test/file.py", old_lines, new_lines, context=1)

        assert "@@" in result


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
                "    print('hello planet')",  # Note: properly indented
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


class TestPwd:
    """Tests for pwd() function."""

    @pytest.mark.asyncio
    async def test_pwd_returns_current_directory(self):
        """pwd should return the current working directory."""
        from modules.file import pwd

        result = await pwd()

        # Should return a valid directory path
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0
        # Should be an absolute path
        assert os.path.isabs(result) or result.startswith('/')


class TestChdir:
    """Tests for chdir() function."""

    @pytest.mark.asyncio
    async def test_chdir_to_existing_directory(self):
        """chdir should change to an existing directory."""
        from modules import _session_id
        from modules.file import chdir

        _session_id.set("test-session-chdir")

        # Use a known existing directory
        result = await chdir("/tmp")

        assert result == os.path.abspath("/tmp")

    @pytest.mark.asyncio
    async def test_chdir_to_nonexistent_raises(self):
        """chdir to non-existent path should raise FileNotFoundError."""
        from modules.file import chdir

        with pytest.raises(FileNotFoundError):
            await chdir("/nonexistent/directory/that/does/not/exist")

    @pytest.mark.asyncio
    async def test_chdir_to_file_raises(self):
        """chdir to a file path should raise NotADirectoryError."""
        from modules.file import chdir

        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp_path = f.name

        try:
            with pytest.raises(NotADirectoryError):
                await chdir(tmp_path)
        finally:
            os.unlink(tmp_path)


class TestCloseAllFiles:
    """Tests for close_all_files() function."""

    @pytest.mark.asyncio
    async def test_close_all_files_clears_memory(self):
        """close_all_files should clear all file entries from memory."""
        from modules import _session_id
        from modules.file import close_all_files, open_file

        _session_id.set("test-session-closeall")

        # Create a temp file and open it
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("test content\n")
            tmp_path = f.name

        try:
            with patch("modules.file.requests.post") as mock_post:
                mock_post.return_value = MagicMock(status_code=200)
                await open_file(tmp_path)

            # Close all files
            result = await close_all_files()

            assert "Closed" in result
            assert "open files" in result
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_close_all_files_when_none_open(self):
        """close_all_files should return 0 when no files are open."""
        from modules import _session_id
        from modules.file import close_all_files

        _session_id.set("test-session-closeall-empty")

        result = await close_all_files()

        assert "Closed 0" in result


class TestWriteText:
    """Tests for write_text() function."""

    @pytest.mark.asyncio
    async def test_write_text_creates_file(self):
        """write_text should create a new file with the given content."""
        from modules.file import write_text

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "new_file.py")
            content = "def hello():\n    return 'world'\n"

            result = await write_text(file_path, content)

            # File should exist
            assert os.path.exists(file_path)
            # Content should match
            with open(file_path, 'r') as f:
                assert f.read() == content
            # Result should mention file info
            assert "new_file.py" in result
            assert "1 lines" in result or "2 lines" in result

    @pytest.mark.asyncio
    async def test_write_text_overwrites_existing(self):
        """write_text should overwrite an existing file."""
        from modules.file import write_text

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "existing.py")

            # Create initial file
            with open(file_path, 'w') as f:
                f.write("original content\n")

            # Overwrite with new content
            new_content = "new content\n"
            result = await write_text(file_path, new_content)

            # Content should be new
            with open(file_path, 'r') as f:
                assert f.read() == new_content
            assert "existing.py" in result

    @pytest.mark.asyncio
    async def test_write_text_creates_parent_dirs(self):
        """write_text should create parent directories if they don't exist."""
        from modules.file import write_text

        with tempfile.TemporaryDirectory() as tmp_dir:
            nested_path = os.path.join(tmp_dir, "a", "b", "c", "nested.py")
            content = "# nested file\n"

            result = await write_text(nested_path, content)

            assert os.path.exists(nested_path)
            assert "nested.py" in result

    @pytest.mark.asyncio
    async def test_write_text_empty_content(self):
        """write_text should handle empty content."""
        from modules.file import write_text

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "empty.py")

            result = await write_text(file_path, "")

            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert f.read() == ""
            assert "empty.py" in result

    @pytest.mark.asyncio
    async def test_write_text_large_content(self):
        """write_text should handle large content."""
        from modules.file import write_text

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "large.py")
            # Generate ~100KB of content
            content = "x" * 100000

            result = await write_text(file_path, content)

            assert os.path.exists(file_path)
            with open(file_path, 'r') as f:
                assert len(f.read()) == 100000


class TestBatchEdit:
    """Tests for batch_edit() function."""

    @pytest.mark.asyncio
    async def test_batch_edit_single_replacement(self):
        """batch_edit should apply a single replacement."""
        from modules.file import batch_edit, Replacement

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = f.name

        try:
            replacements = [Replacement(old_str="    return 'world'", new_str="    return 'planet'")]
            result = await batch_edit(tmp_path, replacements)

            assert result.success is True
            assert result.changed is True
            assert "1 replacement" in result.message
            with open(tmp_path, 'r') as f:
                assert "return 'planet'" in f.read()
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_batch_edit_multiple_replacements(self):
        """batch_edit should apply multiple replacements in one operation."""
        from modules.file import batch_edit, Replacement

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def foo():\n    x = 1\n    y = 2\n    return x\n")
            tmp_path = f.name

        try:
            replacements = [
                Replacement(old_str="    x = 1", new_str="    x = 10"),
                Replacement(old_str="    y = 2", new_str="    y = 20"),
            ]
            result = await batch_edit(tmp_path, replacements)

            assert result.success is True
            assert "2 replacement" in result.message
            with open(tmp_path, 'r') as f:
                content = f.read()
                assert "x = 10" in content
                assert "y = 20" in content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_batch_edit_not_found(self):
        """batch_edit should return error when text not found."""
        from modules.file import batch_edit, Replacement

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = f.name

        try:
            replacements = [Replacement(old_str="nonexistent text", new_str="something")]
            result = await batch_edit(tmp_path, replacements)

            assert result.success is False
            assert "not found" in result.message.lower() or "no match" in result.message.lower()
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_batch_edit_syntax_validation(self):
        """batch_edit should validate Python syntax for .py files."""
        from modules.file import batch_edit, Replacement

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = f.name

        try:
            # This replacement would create invalid syntax (no indentation)
            replacements = [Replacement(old_str="def hello():", new_str="def broken")]
            result = await batch_edit(tmp_path, replacements)

            assert result.success is False
            assert "syntax" in result.message.lower()
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_batch_edit_returns_diff(self):
        """batch_edit should return a diff of changes."""
        from modules.file import batch_edit, Replacement

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = f.name

        try:
            replacements = [Replacement(old_str="    return 'world'", new_str="    return 'planet'")]
            result = await batch_edit(tmp_path, replacements)

            assert result.success is True
            assert result.diff is not None
            assert "--- " in result.diff
            assert "+++ " in result.diff
        finally:
            os.unlink(tmp_path)


class TestDeleteSnippet:
    """Tests for delete_snippet() function."""

    @pytest.mark.asyncio
    async def test_delete_snippet_success(self):
        """delete_snippet should remove the first occurrence of a snippet."""
        from modules.file import delete_snippet

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    print('hello')\n    return True\n")
            tmp_path = f.name

        try:
            result = await delete_snippet(tmp_path, "    print('hello')")

            assert result.success is True
            assert result.changed is True
            assert "deleted" in result.message.lower()
            with open(tmp_path, 'r') as f:
                content = f.read()
                assert "print('hello')" not in content
                assert "return True" in content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_delete_snippet_not_found(self):
        """delete_snippet should return error when snippet not found."""
        from modules.file import delete_snippet

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return True\n")
            tmp_path = f.name

        try:
            result = await delete_snippet(tmp_path, "nonexistent snippet")

            assert result.success is False
            assert "not found" in result.message.lower() or "no match" in result.message.lower()
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_delete_snippet_returns_diff(self):
        """delete_snippet should return a diff showing the deletion."""
        from modules.file import delete_snippet

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    print('hello')\n    return True\n")
            tmp_path = f.name

        try:
            result = await delete_snippet(tmp_path, "    print('hello')")

            assert result.success is True
            assert result.diff is not None
            assert "--- " in result.diff
            assert "+++ " in result.diff
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_delete_snippet_fuzzy_match(self):
        """delete_snippet should use fuzzy matching."""
        from modules.file import delete_snippet

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    print('hello')\n    return True\n")
            tmp_path = f.name

        try:
            # Use slightly different text (typo) - should still match with lower threshold
            result = await delete_snippet(tmp_path, "  prnt('hello')", threshold=0.6)

            assert result.success is True
            assert result.changed is True
        finally:
            os.unlink(tmp_path)


class TestDiffTextUpdated:
    """Tests for updated diff_text() with unified diff."""

    @pytest.mark.asyncio
    async def test_diff_text_returns_unified_diff(self):
        """diff_text should return unified diff format."""
        from modules.file import diff_text

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = f.name

        try:
            result = await diff_text(
                tmp_path,
                "    return 'world'",
                "    return 'planet'"
            )

            assert "--- " in result
            assert "+++ " in result
            assert "unified diff" in result.lower()
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_diff_text_not_found(self):
        """diff_text should return error when text not found."""
        from modules.file import diff_text

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = f.name

        try:
            result = await diff_text(
                tmp_path,
                "nonexistent text",
                "some replacement"
            )

            assert "Cannot diff" in result
            assert "not found" in result.lower() or "cannot diff" in result.lower()
        finally:
            os.unlink(tmp_path)


class TestModuleRegistration:
    """Tests for new function registrations."""

    def test_batch_edit_is_registered(self):
        """batch_edit should be registered in the module."""
        from modules.file import get_module

        module = get_module()
        fn_names = [fn.name for fn in module.called_fns]
        assert "batch_edit" in fn_names

    def test_delete_snippet_is_registered(self):
        """delete_snippet should be registered in the module."""
        from modules.file import get_module

        module = get_module()
        fn_names = [fn.name for fn in module.called_fns]
        assert "delete_snippet" in fn_names

    def test_delete_file_is_registered(self):
        """delete_file should be registered in the module."""
        from modules.file import get_module

        module = get_module()
        fn_names = [fn.name for fn in module.called_fns]
        assert "delete_file" in fn_names

    def test_replace_text_has_validate_syntax_param(self):
        """replace_text registration should include validate_syntax parameter."""
        from modules.file import get_module

        module = get_module()
        replace_fn = next(fn for fn in module.called_fns if fn.name == "replace_text")
        assert "validate_syntax" in replace_fn.parameters["properties"]


class TestDeleteFile:
    """Tests for delete_file() function."""

    @pytest.mark.asyncio
    async def test_delete_file_success(self):
        """delete_file should delete a file and return success."""
        from modules.file import delete_file

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = f.name

        result = await delete_file(tmp_path)

        assert result.success is True
        assert result.changed is True
        assert "deleted" in result.message.lower()
        assert not os.path.exists(tmp_path)

    @pytest.mark.asyncio
    async def test_delete_file_not_found(self):
        """delete_file should return error when file not found."""
        from modules.file import delete_file

        result = await delete_file("/nonexistent/path/to/file.py")

        assert result.success is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_delete_file_returns_diff(self):
        """delete_file should return a diff showing deleted content."""
        from modules.file import delete_file

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            tmp_path = f.name

        result = await delete_file(tmp_path)

        assert result.success is True
        assert result.diff is not None
        assert "--- " in result.diff
        assert "+++ " in result.diff

    @pytest.mark.asyncio
    async def test_delete_file_is_directory(self):
        """delete_file should return error when path is a directory."""
        from modules.file import delete_file

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = await delete_file(tmp_dir)

            assert result.success is False
            assert "not a file" in result.message.lower()

    @pytest.mark.asyncio
    async def test_delete_file_preserves_path_in_result(self):
        """delete_file should include the path in the result."""
        from modules.file import delete_file

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("test content")
            tmp_path = f.name

        result = await delete_file(tmp_path)

        assert os.path.abspath(result.path) == os.path.abspath(tmp_path)
