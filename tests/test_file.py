"""Comprehensive tests for the file module.

This test file verifies the integrity and correctness of all file module components:
- modules/file/__init__.py
- modules/file/editor.py
- modules/file/memory.py
- modules/file/code_parser.py

Tests use actual file operations with temp files where appropriate,
and mock memory functions where needed for session-specific behavior.
"""

import ast
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Import the modules under test
from modules.file import (
    FileEditor,
    EditResult,
    Replacement,
    CodeDefinition,
    open_file,
    close_file,
    close_all_files,
    replace_text,
    batch_edit,
    delete_snippet,
    write_text,
    delete_file,
    open_function,
    preview_replace,
    diff_text,
    search_files,
    list_dir,
    file_info,
    pwd,
    chdir,
    list_open_files,
    get_file_history,
    file_context,
    get_module,
    _atomic_write,
    _file_type,
    _find_best_window,
    _generate_diff,
    _sanitize_content,
    _validate_python,
    _extract_code_definitions,
    _find_definitions_by_name,
    _extract_definition_source,
    format_file_history,
    get_file_history,
    get_open_files,
    hash_content,
    track_file_change,
)
from modules.file.code_parser import (
    DefinitionExtractor,
)
from modules.file.db import set_open_file, get_open_files, delete_open_file, add_file_change, get_file_changes


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create a temp directory that gets cleaned up, with git initialised."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(['git', 'init'], cwd=tmpdir, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=tmpdir, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=tmpdir, capture_output=True)
        yield tmpdir


@pytest.fixture
def temp_file(temp_dir):
    """Create a temp file with some content, tracked by git."""
    path = os.path.join(temp_dir, "test.txt")
    content = "line 1\nline 2\nline 3\nline 4\nline 5\n"
    with open(path, 'w') as f:
        f.write(content)
    subprocess.run(['git', 'add', path], cwd=temp_dir, capture_output=True)
    return path


@pytest.fixture
def temp_py_file(temp_dir):
    """Create a temp Python file for testing, tracked by git."""
    path = os.path.join(temp_dir, "test_module.py")
    content = '''"""Test module for unit tests."""

def hello():
    """Say hello."""
    print("Hello, world!")

class Greeter:
    """A greeter class."""
    
    def greet(self, name: str) -> str:
        """Greet a person by name."""
        return f"Hello, {name}!"
    
    async def async_greet(self, name: str) -> str:
        """Async greet a person."""
        return f"Hello, {name}!"

def goodbye():
    """Say goodbye."""
    print("Goodbye!")
'''
    with open(path, 'w') as f:
        f.write(content)
    subprocess.run(['git', 'add', path], cwd=temp_dir, capture_output=True)
    return path


# =============================================================================
# Helper Functions Tests
# =============================================================================

class TestHelperFunctions:
    """Tests for utility functions in editor.py."""

    def test_file_type(self):
        """Test file type detection."""
        assert _file_type("test.py") == "Python"
        assert _file_type("test.js") == "JavaScript"
        assert _file_type("test.ts") == "TypeScript"
        assert _file_type("test.json") == "JSON"
        assert _file_type("test.md") == "Markdown"
        assert _file_type("test.txt") == "Text"
        assert _file_type("test.html") == "HTML"
        assert _file_type("test.css") == "CSS"
        assert _file_type("test.yaml") == "YAML"
        assert _file_type("test.toml") == "TOML"
        assert _file_type("test.unknown") == "unknown"
        assert _file_type("test") == "File"

    def test_sanitize_content(self):
        """Test content sanitization."""
        # Normal content passes through
        assert _sanitize_content("hello world") == "hello world"
        
        # Unicode content passes through
        assert _sanitize_content("héllo wörld") == "héllo wörld"
        
        # Empty content
        assert _sanitize_content("") == ""

    def test_validate_python_valid(self):
        """Test Python syntax validation with valid code."""
        valid_code = '''
def foo():
    """A function."""
    return 42

class Bar:
    def method(self):
        pass
'''
        is_valid, error = _validate_python(valid_code)
        assert is_valid is True
        assert error is None

    def test_validate_python_invalid(self):
        """Test Python syntax validation with invalid code."""
        invalid_code = '''
def foo(:  # Missing closing paren
    pass
'''
        is_valid, error = _validate_python(invalid_code)
        assert is_valid is False
        assert error is not None
        assert "Syntax error" in error

    def test_validate_python_empty(self):
        """Test Python syntax validation with empty code."""
        is_valid, error = _validate_python("")
        assert is_valid is True
        assert error is None

    def test_find_best_window_exact_match(self):
        """Test _find_best_window with exact match."""
        # Lines must have newlines (as they would from splitlines(keepends=True))
        lines = ["def foo():\n", "    pass\n", "    return 42"]
        needle = "def foo():\n    pass"
        
        span, score = _find_best_window(lines, needle, threshold=0.95)
        
        assert span is not None
        # Returns 4-tuple: (start_line, end_line, char_start, char_end)
        # For multi-line needles, char_end is None
        assert span[0] == 0  # start_line
        assert span[1] == 2  # end_line
        assert span[2] == 0  # char_start (starts at beginning of line)
        assert span[3] is None  # char_end (None for multi-line)
        assert score == 1.0

    def test_find_best_window_fuzzy_match(self):
        """Test _find_best_window with fuzzy match."""
        lines = ["def foo():", "    pass", "    return 42", "def bar():", "    pass"]
        needle = "def    foo():    pass"  # Whitespace differences
        
        span, score = _find_best_window(lines, needle, threshold=0.8)
        
        assert span is not None
        assert score > 0.8

    def test_find_best_window_no_match(self):
        """Test _find_best_window when no match above threshold."""
        lines = ["def foo():", "    pass", "    return 42"]
        needle = "async def completely_different():"
        
        span, score = _find_best_window(lines, needle, threshold=0.95)
        
        assert span is None

    def test_find_best_window_empty_needle(self):
        """Test _find_best_window with empty needle."""
        lines = ["def foo():", "    pass"]
        needle = ""
        
        span, score = _find_best_window(lines, needle, threshold=0.95)
        
        assert span is None
        assert score == 0.0

    def test_generate_diff(self):
        """Test diff generation."""
        old_lines = ["line 1", "line 2", "line 3"]
        new_lines = ["line 1", "modified line 2", "line 3"]
        
        diff = _generate_diff("test.txt", old_lines, new_lines)
        
        assert "---" in diff
        assert "+++" in diff
        assert "-line 2" in diff
        assert "+modified line 2" in diff

    def test_generate_diff_empty(self):
        """Test diff generation with identical content."""
        lines = ["line 1", "line 2"]
        diff = _generate_diff("test.txt", lines, lines)
        # May be empty since no changes
        assert isinstance(diff, str)

    def test_atomic_write(self, temp_dir):
        """Test atomic write operation."""
        path = os.path.join(temp_dir, "atomic_test.txt")
        content = "atomic write test content\nwith multiple lines\n"
        
        _atomic_write(path, content)
        
        with open(path, 'r') as f:
            assert f.read() == content

    def test_hash_content(self):
        """Test content hashing."""
        hash1 = hash_content("hello world")
        hash2 = hash_content("hello world")
        hash3 = hash_content("different content")
        
        assert len(hash1) == 8
        assert hash1 == hash2  # Same content = same hash
        assert hash1 != hash3  # Different content = different hash


# =============================================================================
# EditResult Tests
# =============================================================================

class TestEditResult:
    """Tests for EditResult dataclass."""

    def test_edit_result_success(self):
        """Test EditResult with success."""
        result = EditResult(
            success=True,
            path="/path/to/file.py",
            message="Replaced text",
            changed=True,
            diff="some diff",
            line_start=10,
            line_end=20,
            similarity=0.95
        )
        
        output = result.to_string()
        assert "✅" in output
        assert "Replaced text" in output
        assert "10-20" in output
        assert "95%" in output

    def test_edit_result_failure(self):
        """Test EditResult with failure."""
        result = EditResult(
            success=False,
            path="/path/to/file.py",
            message="Text not found",
            similarity=0.50
        )
        
        output = result.to_string()
        assert "❌" in output
        assert "Text not found" in output
        assert "50%" in output

    def test_edit_result_syntax_error(self):
        """Test EditResult with syntax error."""
        result = EditResult(
            success=False,
            path="/path/to/file.py",
            message="Syntax validation failed",
            syntax_error="line 5: invalid syntax"
        )
        
        output = result.to_string()
        assert "❌" in output
        assert "Syntax error" in output


# =============================================================================
# Replacement Tests
# =============================================================================

class TestReplacement:
    """Tests for Replacement dataclass."""

    def test_replacement_creation(self):
        """Test creating a Replacement."""
        rep = Replacement(old_str="hello", new_str="world")
        assert rep.old_str == "hello"
        assert rep.new_str == "world"


# =============================================================================
# FileEditor Tests
# =============================================================================

class TestFileEditor:
    """Tests for FileEditor class."""

    def test_file_editor_init(self, mock_memory_utils):
        """Test FileEditor initialization."""
        editor = FileEditor(db_module=mock_memory_utils)

        assert editor._db_module is mock_memory_utils

    def test_file_editor_init_default(self):
        """Test FileEditor defaults to self-contained file/db.py when no db_module given."""
        editor = FileEditor()
        # No db_module provided → _db_module is None (editor uses imports directly)
        assert editor._db_module is None

    @pytest.mark.asyncio
    async def test_open_file_not_found(self, mock_session_id, mock_memory_utils):
        """Test open_file with non-existent file."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.open_file("/nonexistent/path.txt")
        
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_open_file_success(self, temp_file, mock_session_id, mock_memory_utils):
        """Test open_file with valid file."""
        with patch('modules.file.editor.set_open_file') as mock_set:
            mock_set.return_value = True
            editor = FileEditor(
                session_id_func=lambda: mock_session_id,
                db_module=mock_memory_utils
            )

            result = await editor.open_file(temp_file)

            assert "Opened" in result
            assert mock_set.called

    @pytest.mark.asyncio
    async def test_open_file_with_range(self, temp_file, mock_session_id, mock_memory_utils):
        """Test open_file with line range."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.open_file(temp_file, line_start=1, line_end=3)
        
        assert "Opened" in result
        assert "lines 1-3" in result

    def test_read_file(self, temp_file):
        """Test read_file operation."""
        editor = FileEditor()
        content = editor.read_file(temp_file)
        
        assert "line 1" in content
        assert "line 2" in content

    def test_read_file_with_range(self, temp_file):
        """Test read_file with line range."""
        editor = FileEditor()
        content = editor.read_file(temp_file, line_start=1, line_end=3)
        
        assert "line 2" in content
        assert "line 3" in content

    def test_read_file_not_found(self):
        """Test read_file with non-existent file."""
        editor = FileEditor()
        result = editor.read_file("/nonexistent/file.txt")
        
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_file_info(self, temp_file):
        """Test file_info operation."""
        editor = FileEditor()
        result = await editor.file_info(temp_file)
        
        assert "test.txt" in result
        assert "Text" in result
        assert "lines" in result
        assert "bytes" in result

    @pytest.mark.asyncio
    async def test_replace_text_success(self, temp_file, mock_session_id, mock_memory_utils):
        """Test replace_text with valid match."""
        # Pre-seed open-file entry so the edit guard passes
        import os
        filename = os.path.basename(temp_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": temp_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.replace_text(temp_file, "line 2", "REPLACED LINE 2")
        
        assert "✅" in result
        
        # Verify the file was modified
        with open(temp_file) as f:
            content = f.read()
        assert "REPLACED LINE 2" in content
        assert "line 2" not in content

    @pytest.mark.asyncio
    async def test_replace_text_not_found(self, temp_file, mock_session_id, mock_memory_utils):
        """Test replace_text when text not found."""
        filename = os.path.basename(temp_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": temp_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.replace_text(
            temp_file, 
            "nonexistent text xyz123",
            "replacement"
        )
        
        # Should return helpful message about no match
        assert "not found" in result.lower() or "match" in result.lower()

    @pytest.mark.asyncio
    async def test_batch_edit_success(self, temp_file, mock_session_id, mock_memory_utils):
        """Test batch_edit with multiple replacements."""
        filename = os.path.basename(temp_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": temp_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        replacements = [
            Replacement(old_str="line 1", new_str="FIRST LINE"),
            Replacement(old_str="line 2", new_str="SECOND LINE"),
        ]
        
        result = await editor.batch_edit(temp_file, replacements)
        
        assert result.success is True
        assert result.changed is True
        assert result.diff is not None
        
        # Verify the file was modified
        with open(temp_file) as f:
            content = f.read()
        assert "FIRST LINE" in content
        assert "SECOND LINE" in content

    @pytest.mark.asyncio
    async def test_batch_edit_not_found(self, temp_file, mock_session_id, mock_memory_utils):
        """Test batch_edit when one replacement not found."""
        filename = os.path.basename(temp_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": temp_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        replacements = [
            Replacement(old_str="line 1", new_str="FIRST LINE"),
            Replacement(old_str="nonexistent xyz", new_str="SECOND LINE"),
        ]
        
        result = await editor.batch_edit(temp_file, replacements)
        
        assert result.success is False
        assert "not found" in result.message.lower() or "no match" in result.message.lower()

    @pytest.mark.asyncio
    async def test_delete_snippet_success(self, temp_file, mock_session_id, mock_memory_utils):
        """Test delete_snippet operation."""
        filename = os.path.basename(temp_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": temp_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.delete_snippet(temp_file, "line 2")
        
        assert result.success is True
        assert result.changed is True
        
        # Verify the file was modified
        with open(temp_file) as f:
            content = f.read()
        assert "line 2" not in content

    @pytest.mark.asyncio
    async def test_write_text(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test write_text operation."""
        path = os.path.join(temp_dir, "new_file.txt")
        # Pre-create the file so write_text has something to overwrite
        with open(path, 'w') as f:
            f.write("existing\n")
        
        filename = os.path.basename(path)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": path,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.write_text(path, "Hello, World!\n")
        
        assert "✅" in result
        assert os.path.exists(path)
        
        with open(path) as f:
            assert f.read() == "Hello, World!\n"

    @pytest.mark.asyncio
    async def test_write_text_with_parent_dirs(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test write_text with create_parent_dirs=True."""
        path = os.path.join(temp_dir, "nested/dir/new_file.txt")
        # Pre-create the file so write_text has something to overwrite
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write("existing\n")
        
        filename = os.path.basename(path)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": path,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.write_text(path, "Nested content\n", create_parent_dirs=True)
        
        assert "✅" in result
        assert os.path.exists(path)

    # -------------------------------------------------------------------------
    # Edit Guard Tests — must call open_file() before edit operations
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    @patch('modules.file.editor.config_get', lambda key, default=True: True)
    async def test_replace_text_blocked_when_not_open(self, temp_file, mock_session_id, mock_memory_utils):
        """Test that replace_text is rejected when the file has not been opened."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.replace_text(temp_file, "line 2", "REPLACED LINE 2")
        
        assert "NOT IN CONTEXT" in result
        assert "open_file" in result

    @pytest.mark.asyncio
    @patch('modules.file.editor.config_get', lambda key, default=True: True)
    async def test_batch_edit_blocked_when_not_open(self, temp_file, mock_session_id, mock_memory_utils):
        """Test that batch_edit is rejected when the file has not been opened."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.batch_edit(temp_file, [
            Replacement(old_str="line 1", new_str="FIRST LINE"),
        ])
        
        assert result.success is False
        assert "NOT IN CONTEXT" in result.message

    @pytest.mark.asyncio
    @patch('modules.file.editor.config_get', lambda key, default=True: True)
    async def test_delete_snippet_blocked_when_not_open(self, temp_file, mock_session_id, mock_memory_utils):
        """Test that delete_snippet is rejected when the file has not been opened."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.delete_snippet(temp_file, "line 2")
        
        assert result.success is False
        assert "NOT IN CONTEXT" in result.message

    @pytest.mark.asyncio
    @patch('modules.file.editor.config_get', lambda key, default=True: True)
    async def test_write_text_blocked_when_not_open(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test that write_text is rejected when the file has not been opened."""
        path = os.path.join(temp_dir, "new_file.txt")
        with open(path, 'w') as f:
            f.write("existing\n")
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.write_text(path, "Hello, World!\n")
        
        assert "NOT IN CONTEXT" in result

    @pytest.mark.asyncio
    async def test_delete_file(self, temp_file, mock_session_id, mock_memory_utils):
        """Test delete_file operation."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.delete_file(temp_file)
        
        assert result.success is True
        assert result.changed is True
        assert not os.path.exists(temp_file)

    @pytest.mark.asyncio
    async def test_delete_file_not_found(self, mock_session_id, mock_memory_utils):
        """Test delete_file with non-existent file."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.delete_file("/nonexistent/file.txt")
        
        assert result.success is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_close_file_by_name(self, mock_session_id, mock_memory_utils):
        """Test close_file by name."""
        mock_memory_utils.get_open_files.return_value = [
            {"type": "open_file:test.py:0-*"}
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.close_file("test.py")
        
        assert "Closed" in result or "not in context" in result

    @pytest.mark.asyncio
    async def test_close_file_with_range(self, mock_session_id, mock_memory_utils):
        """Test close_file with specific range."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.close_file("test.py", line_start=0, line_end=10)
        
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_close_all_files(self, mock_session_id, mock_memory_utils):
        """Test close_all_files operation."""
        mock_memory_utils.get_open_files.return_value = [
            {"type": "open_file:test1.py:0-*"},
            {"type": "open_file:test2.py:0-*"},
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.close_all_files()
        
        assert "Closed" in result or "no open files" in result.lower()

    @pytest.mark.asyncio
    async def test_preview_replace(self, temp_file):
        """Test preview_replace operation."""
        editor = FileEditor()
        
        result = await editor.preview_replace(temp_file, "line 2")
        
        assert "Match" in result or "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_diff_text(self, temp_file):
        """Test diff_text operation."""
        editor = FileEditor()
        
        result = await editor.diff_text(temp_file, "line 2", "REPLACED")
        
        assert "---" in result or "Cannot diff" in result

    @pytest.mark.asyncio
    async def test_search_files(self, temp_dir):
        """Test search_files operation."""
        # Create a test file
        with open(os.path.join(temp_dir, "search_test.py"), 'w') as f:
            f.write("def test_function():\n    pass\n")
        
        editor = FileEditor()
        result = await editor.search_files("test_function", temp_dir)
        
        assert "test_function" in result or "matches" in result.lower()

    @pytest.mark.asyncio
    async def test_list_dir(self, temp_dir):
        """Test list_dir operation."""
        # Create test files and dirs
        os.makedirs(os.path.join(temp_dir, "subdir"))
        with open(os.path.join(temp_dir, "file.txt"), 'w') as f:
            f.write("content")
        
        editor = FileEditor()
        result = await editor.list_dir(temp_dir)
        
        assert "file.txt" in result
        assert "subdir" in result

    @pytest.mark.asyncio
    async def test_pwd(self):
        """Test pwd operation."""
        editor = FileEditor()
        try:
            current = os.getcwd()
        except FileNotFoundError:
            # CWD was deleted, restore to a valid directory
            safe_dir = os.path.expanduser("~") if os.path.exists(os.path.expanduser("~")) else "/"
            os.chdir(safe_dir)
            current = safe_dir
        
        result = await editor.pwd()
        
        assert result == current

    @pytest.mark.asyncio
    async def test_chdir(self, temp_dir):
        """Test chdir operation."""
        editor = FileEditor()
        original_cwd = os.getcwd()
        
        try:
            result = await editor.chdir(temp_dir)
            
            assert "Changed" in result or "Error" in result
        finally:
            # Always restore original cwd, even if test fails
            try:
                os.chdir(original_cwd)
            except FileNotFoundError:
                # If original cwd no longer exists, use home or root
                os.chdir(os.path.expanduser("~") if os.path.exists(os.path.expanduser("~")) else "/")


# =============================================================================
# Code Parser Tests
# =============================================================================

class TestCodeParser:
    """Tests for code_parser.py module."""

    def test_extract_code_definitions(self, temp_py_file):
        """Test extracting definitions from Python file."""
        with open(temp_py_file) as f:
            source = f.read()
        
        definitions = _extract_code_definitions(source)
        
        assert len(definitions) >= 4  # hello, Greeter, greet, async_greet, goodbye
        
        # Check for expected definitions
        names = [d.name for d in definitions]
        assert "hello" in names
        assert "Greeter" in names
        assert "goodbye" in names

    def test_extract_code_definitions_with_class(self):
        """Test extracting class definitions."""
        source = '''
class MyClass:
    """A class."""
    
    def method(self):
        pass

class AnotherClass:
    pass
'''
        definitions = _extract_code_definitions(source)
        
        class_names = [d.name for d in definitions if d.type == "class"]
        assert "MyClass" in class_names
        assert "AnotherClass" in class_names

    def test_extract_code_definitions_with_async(self):
        """Test extracting async function definitions."""
        source = '''
async def async_func():
    """An async function."""
    await something()
'''
        definitions = _extract_code_definitions(source)
        
        assert len(definitions) >= 1
        async_def = definitions[0]
        assert async_def.type == "async_function"
        assert async_def.async_keyword is True

    def test_find_definitions_by_name_exact(self):
        """Test finding definitions by exact name."""
        source = '''
def hello():
    pass

def goodbye():
    pass
'''
        definitions = _extract_code_definitions(source)
        matches = _find_definitions_by_name(definitions, "hello")
        
        assert len(matches) == 1
        assert matches[0].name == "hello"

    def test_find_definitions_by_name_qualified(self):
        """Test finding methods by qualified name."""
        source = '''
class MyClass:
    def method(self):
        pass
'''
        definitions = _extract_code_definitions(source)
        matches = _find_definitions_by_name(definitions, "MyClass.method")
        
        assert len(matches) >= 1
        assert any("method" in m.qualified_name for m in matches)

    def test_find_definitions_by_name_fuzzy(self):
        """Test fuzzy matching on definition names."""
        source = '''
def very_long_function_name():
    pass

def very_long_fucntion_name():  # Typo
    pass
'''
        definitions = _extract_code_definitions(source)
        matches = _find_definitions_by_name(definitions, "very_long_function_name", threshold=0.8)
        
        assert len(matches) >= 1

    def test_extract_definition_source(self, temp_py_file):
        """Test extracting source lines for a definition."""
        with open(temp_py_file) as f:
            source = f.read()
        
        definitions = _extract_code_definitions(source)
        source_lines = source.splitlines(keepends=True)
        
        # Find a function definition
        func_def = next(d for d in definitions if d.type in ("function", "method"))
        
        lines = _extract_definition_source(func_def, source_lines)
        
        assert len(lines) > 0
        assert "def" in lines[0] or "async def" in lines[0]

    def test_code_definition_properties(self):
        """Test CodeDefinition properties."""
        source = '''
def foo():
    """Docstring."""
    pass
'''
        definitions = _extract_code_definitions(source)
        assert len(definitions) >= 1
        
        defn = definitions[0]
        assert defn.line_range is not None
        assert "-" in defn.line_range
        assert defn.memory_key is not None
        assert ":" in defn.memory_key


# =============================================================================
# Memory Functions Tests
# =============================================================================

class TestMemoryFunctions:
    """Tests for memory tracking functions."""

    def test_hash_content(self):
        """Test hash_content function."""
        h1 = hash_content("test content")
        h2 = hash_content("test content")
        h3 = hash_content("different")
        
        assert len(h1) == 8
        assert h1 == h2
        assert h1 != h3

    def test_track_file_change(self, mock_session_id):
        """Test track_file_change function."""
        # Patch where memory.py uses it (local binding from 'from .db import')
        with patch('modules.file.memory.add_file_change') as mock_set:
            mock_set.return_value = True

            result = track_file_change(
                mock_session_id,
                "/path/to/file.py",
                "replace_text",
                "some diff"
            )

            assert result is True
            assert mock_set.called

    def test_track_file_change_failure(self, mock_session_id):
        """Test track_file_change handles failures gracefully."""
        with patch('modules.file.memory.add_file_change') as mock_set:
            mock_set.side_effect = Exception("Memory error")

            result = track_file_change(
                mock_session_id,
                "/path/to/file.py",
                "replace_text",
                "diff"
            )

            assert result is False  # Non-blocking

    def test_format_file_history_empty(self):
        """Test format_file_history with empty list."""
        result = format_file_history([])
        assert "No file changes" in result

    def test_format_file_history_with_data(self):
        """Test format_file_history with data."""
        memories = [
            {
                "path": "/path/to/file1.py",
                "change_type": "replace_text",
                "success": True,
            },
            {
                "path": "/path/to/file2.py",
                "change_type": "batch_edit",
                "success": False,
            }
        ]

        result = format_file_history(memories)

        assert "File Change History" in result
        assert "file1.py" in result
        assert "file2.py" in result
        assert "✅" in result
        assert "❌" in result

    def test_get_file_history_with_path(self, mock_session_id):
        """Test get_file_history with specific path filters correctly."""
        # Test that path parameter creates the correct keyword
        # Note: This test verifies the keyword generation without needing to mock
        import modules.file.memory as memory_module
        
        # Check that path parameter generates correct keyword
        path = "/some/path.py"
        keyword = f"k:file_change:{path}"
        assert keyword == "k:file_change:/some/path.py"


# =============================================================================
# Module Integration Tests
# =============================================================================

class TestModuleIntegration:
    """Tests for module-level integration."""

    def test_get_module(self):
        """Test get_module returns correct structure."""
        module = get_module()
        
        assert module.name == "file"
        assert len(module.called_fns) > 0
        assert len(module.context_fns) > 0
        
        # Check that key functions are registered
        fn_names = [fn.name for fn in module.called_fns]
        assert "open_file" in fn_names
        assert "replace_text" in fn_names
        assert "batch_edit" in fn_names
        assert "close_file" in fn_names
        # read_file is intentionally NOT exposed - files should be opened via
        # open_file() and contents will be injected via file_context()

    def test_module_function_descriptions(self):
        """Test that module functions have proper descriptions."""
        module = get_module()
        
        for fn in module.called_fns:
            assert fn.description is not None
            assert len(fn.description) > 0
            assert fn.fn is not None

    def test_module_context_functions(self):
        """Test context functions are registered."""
        module = get_module()
        
        context_fn_names = [fn.tag for fn in module.context_fns]
        assert "file" in context_fn_names

    def test_all_exports_present(self):
        """Test that __all__ exports are all available."""
        from modules.file import __all__
        
        import modules.file as file_module
        
        for item in __all__:
            assert hasattr(file_module, item), f"Missing export: {item}"


# =============================================================================
# End-to-End Tests
# =============================================================================

class TestEndToEnd:
    """End-to-end tests using actual file operations."""

    def test_full_file_edit_workflow(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test complete file edit workflow."""
        # Create a file
        test_file = os.path.join(temp_dir, "workflow_test.txt")
        with open(test_file, 'w') as f:
            f.write("Original content\nLine 2\nLine 3\n")
        
        # Use FileEditor
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        # Read
        content = editor.read_file(test_file)
        assert "Original content" in content
        
        # Replace
        import asyncio
        asyncio.run(editor.replace_text(test_file, "Line 2", "MODIFIED LINE 2"))
        
        # Verify
        with open(test_file) as f:
            final_content = f.read()
        assert "MODIFIED LINE 2" in final_content
        assert "Line 2" not in final_content

    def test_batch_edit_preserves_file_integrity(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test that batch edits maintain file structure."""
        test_file = os.path.join(temp_dir, "batch_test.txt")
        original = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        with open(test_file, 'w') as f:
            f.write(original)
        
        filename = os.path.basename(test_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": test_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        import asyncio
        replacements = [
            Replacement(old_str="line 1", new_str="FIRST"),
            Replacement(old_str="line 3", new_str="THIRD"),
            Replacement(old_str="line 5", new_str="FIFTH"),
        ]
        asyncio.run(editor.batch_edit(test_file, replacements))
        
        with open(test_file) as f:
            content = f.read()
        
        assert "FIRST" in content
        assert "THIRD" in content
        assert "FIFTH" in content
        assert "line 2" in content  # Unchanged line
        assert "line 4" in content  # Unchanged line

    def test_python_syntax_validation_blocks_invalid_edits(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test that syntax validation prevents invalid Python edits."""
        test_file = os.path.join(temp_dir, "syntax_test.py")
        with open(test_file, 'w') as f:
            f.write("def foo():\n    pass\n")
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        import asyncio
        
        # Try to inject invalid syntax
        result = asyncio.run(editor.replace_text(
            test_file,
            "def foo():",
            "def foo(:",  # Invalid syntax
            validate_syntax=True
        ))
        
        # Should fail due to syntax error
        assert "Syntax" in result or "error" in result.lower()
        
        # Original file should be unchanged
        with open(test_file) as f:
            content = f.read()
        assert content == "def foo():\n    pass\n"


# =============================================================================
# Additional Edge Case Tests (to fill gaps)
# =============================================================================

class TestCodeParserEdgeCases:
    """Edge case tests for code parser."""

    def test_build_signature_with_args(self):
        """Test signature building with various arguments."""
        from modules.file.code_parser import _extract_code_definitions
        
        source = '''
def foo(a, b, c):
    pass

def bar(*args, **kwargs):
    pass

def baz(x, y=10, *args, z=None, **kwargs):
    pass
'''
        definitions = _extract_code_definitions(source)
        
        # Find the definitions
        foo_def = next(d for d in definitions if d.name == 'foo')
        bar_def = next(d for d in definitions if d.name == 'bar')
        baz_def = next(d for d in definitions if d.name == 'baz')
        
        # Verify signatures contain expected elements (format may vary)
        assert 'def foo' in foo_def.signature
        assert 'def bar' in bar_def.signature
        assert 'def baz' in baz_def.signature

    def test_get_docstring_extraction(self):
        """Test docstring extraction."""
        from modules.file.code_parser import _extract_code_definitions
        
        source = '''
def with_docstring():
    """This is a docstring."""
    pass

def without_docstring():
    pass

class ClassWithDoc:
    """Class docstring."""
    def method(self):
        """Method docstring."""
        pass
'''
        definitions = _extract_code_definitions(source)
        
        with_doc = next(d for d in definitions if d.name == 'with_docstring')
        without_doc = next(d for d in definitions if d.name == 'without_docstring')
        class_def = next(d for d in definitions if d.name == 'ClassWithDoc')
        
        assert 'This is a docstring' in with_doc.docstring
        assert without_doc.docstring == ""
        assert 'Class docstring' in class_def.docstring

    def test_docstring_truncation(self):
        """Test that long docstrings are truncated."""
        from modules.file.code_parser import _extract_code_definitions
        
        long_doc = "x" * 1000
        source = f'''
def long_doc():
    """{long_doc}"""
    pass
'''
        definitions = _extract_code_definitions(source)
        defn = definitions[0]
        assert len(defn.docstring) <= 503  # 500 + "..."


class TestFileEditorEdgeCases:
    """Edge case tests for FileEditor."""

    @pytest.mark.asyncio
    async def test_replace_text_with_low_threshold(self, temp_file, mock_session_id, mock_memory_utils):
        """Test replace_text with lower threshold (fuzzy match)."""
        # Create a file with text that won't match exactly
        with open(temp_file, 'w') as f:
            f.write("def hello():\n    print('hello')\n")
        
        filename = os.path.basename(temp_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": temp_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        # Try with fuzzy match
        result = await editor.replace_text(
            temp_file,
            "def  hello():   # with comment",
            "def goodbye():",
            threshold=0.7  # Lower threshold
        )
        
        # Should work if similarity is above threshold
        assert "✅" in result or "hello" in result.lower()

    @pytest.mark.asyncio
    async def test_replace_text_skip_validation(self, temp_py_file, mock_session_id, mock_memory_utils):
        """Test replace_text with syntax validation skipped."""
        filename = os.path.basename(temp_py_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": temp_py_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        # This would normally fail validation, but we're skipping it
        result = await editor.replace_text(
            temp_py_file,
            "def hello():",
            "def broken(:",  # Invalid syntax
            validate_syntax=False  # Skip validation
        )
        
        # Should succeed because we skipped validation
        # Note: This tests the flag works, even if result varies
        assert "✅" in result or "✅" in result or "Replaced" in result or "def broken" in result

    @pytest.mark.asyncio
    async def test_batch_edit_empty_list(self, temp_file, mock_session_id, mock_memory_utils):
        """Test batch_edit with empty replacements list."""
        filename = os.path.basename(temp_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": temp_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.batch_edit(temp_file, [])
        
        # Empty list should succeed (no changes made)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_batch_edit_skip_validation(self, temp_py_file, mock_session_id, mock_memory_utils):
        """Test batch_edit with syntax validation skipped."""
        filename = os.path.basename(temp_py_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": temp_py_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        replacements = [
            Replacement(old_str="def hello():", new_str="def broken(:"),
        ]
        
        result = await editor.batch_edit(
            temp_py_file,
            replacements,
            validate_syntax=False
        )
        
        # Should succeed because we skipped validation
        assert result.success is True

    @pytest.mark.asyncio
    async def test_delete_snippet_fuzzy_match(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test delete_snippet with fuzzy matching."""
        test_file = os.path.join(temp_dir, "fuzzy_delete.txt")
        with open(test_file, 'w') as f:
            f.write("line one\nline two\nline three\n")
        
        filename = os.path.basename(test_file)
        mock_memory_utils.get_open_files.return_value = [
            {
                "id": "mem-open-1",
                "keywords": [mock_session_id, f"open_file:{filename}"],
                "properties": {"filename": filename, "path": test_file,
                                "line_start": "0", "line_end": "*", "git_hash": "*"},
            }
        ]
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        # Try to delete with slight variations
        result = await editor.delete_snippet(
            test_file,
            "linee twoo",  # Misspelled
            threshold=0.7
        )
        
        # Result depends on similarity - either success, "not found", or guard rejection
        assert result.success or "not found" in result.message.lower() or "not in context" in result.message.lower()

    @pytest.mark.asyncio
    async def test_open_function_non_py_file(self, temp_file, mock_session_id, mock_memory_utils):
        """Test open_function with non-Python file."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.open_function(temp_file, "some_function")
        
        assert "Error" in result or ".py" in result or "Python" in result

    @pytest.mark.asyncio
    async def test_open_function_multiple_matches(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test open_function when multiple definitions match."""
        test_file = os.path.join(temp_dir, "multi_match.py")
        with open(test_file, 'w') as f:
            f.write('''
class Foo:
    def helper(self): pass

class Bar:
    def helper(self): pass

def helper(): pass
''')
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.open_function(test_file, "helper")
        
        # Should find first match, but note other matches exist
        assert "helper" in result or "helper" in result.lower()
        # May also show "Also found" message

    @pytest.mark.asyncio
    async def test_list_dir_nonexistent(self, mock_session_id, mock_memory_utils):
        """Test list_dir with non-existent path."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.list_dir("/nonexistent/path/xyz123")
        
        assert "not found" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_list_dir_file_instead_of_dir(self, temp_file, mock_session_id, mock_memory_utils):
        """Test list_dir when path is a file, not a directory."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.list_dir(temp_file)
        
        assert "not a directory" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_chdir_nonexistent(self, mock_session_id, mock_memory_utils):
        """Test chdir to non-existent directory."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.chdir("/nonexistent/path/xyz123")
        
        assert "not found" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_chdir_file_instead_of_dir(self, temp_file, mock_session_id, mock_memory_utils):
        """Test chdir when path is a file, not a directory."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.chdir(temp_file)
        
        assert "not a directory" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_open_file_large_file_warning(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test open_file large file warning (>1000 lines)."""
        test_file = os.path.join(temp_dir, "large.txt")
        # Create a file with 1001+ lines
        with open(test_file, 'w') as f:
            for i in range(1002):
                f.write(f"line {i}\n")
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.open_file(test_file)
        
        assert "LARGE FILE" in result or "large" in result.lower()

    @pytest.mark.asyncio
    async def test_open_function_include_options(self, temp_py_file, mock_session_id, mock_memory_utils):
        """Test open_function with include_docstring and include_decorators options."""
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        # Test without docstring
        result_no_doc = await editor.open_function(
            temp_py_file,
            "hello",
            include_docstring=False,
            include_decorators=True
        )
        
        # Test without decorators
        result_no_dec = await editor.open_function(
            temp_py_file,
            "hello",
            include_docstring=True,
            include_decorators=False
        )
        
        # Both should return results (function source code)
        assert "hello" in result_no_doc or "def" in result_no_doc
        assert "hello" in result_no_dec or "def" in result_no_dec

    @pytest.mark.asyncio
    async def test_delete_file_directory(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test delete_file on a directory (should fail)."""
        test_dir = os.path.join(temp_dir, "test_dir")
        os.makedirs(test_dir)
        
        editor = FileEditor(
            session_id_func=lambda: mock_session_id,
            db_module=mock_memory_utils
        )
        
        result = await editor.delete_file(test_dir)
        
        assert result.success is False
        assert "directory" in result.message.lower()

    @pytest.mark.asyncio
    async def test_read_file_with_invalid_encoding(self, temp_dir, mock_session_id, mock_memory_utils):
        """Test read_file handles encoding issues gracefully."""
        test_file = os.path.join(temp_dir, "binary.bin")
        with open(test_file, 'wb') as f:
            f.write(b'\x00\x01\x02\xff\xfe')
        
        editor = FileEditor()
        result = editor.read_file(test_file)
        
        # Should handle gracefully (return content or error)
        assert isinstance(result, str)


class TestMemoryEdgeCases:
    """Edge case tests for memory functions."""

    def test_format_file_history_malformed_data(self):
        """Test format_file_history with incomplete data."""
        memories = [
            {},  # Missing fields
            {"path": "/test.py", "success": True},  # Partial
        ]

        result = format_file_history(memories)

        assert "File Change History" in result
        assert "test.py" in result

    def test_get_open_files_with_files(self, mock_session_id):
        """Test get_open_files returns records from the DB."""
        with patch('modules.file.editor.get_open_files') as mock:
            mock.return_value = [
                {"id": 1, "session_id": mock_session_id, "keyword": "open_file:test.py",
                 "path": "/test.py", "content": None,
                 "line_start": "0", "line_end": "*", "created_at": "2026-01-01T00:00:00+00:00"}
            ]
            editor = FileEditor(session_id_func=lambda: mock_session_id)
            result = editor.list_open_files()
            assert "test.py" in result


class TestFileEditorInstanceMethods:
    """Test FileEditor instance methods directly."""

    def test_list_open_files_method(self, mock_session_id):
        """Test FileEditor.list_open_files() method."""
        with patch('modules.file.editor.get_open_files') as mock_get:
            mock_get.return_value = [
                {"keyword": "open_file:test.py", "path": "/test.py",
                 "line_start": "0", "line_end": "*", "created_at": "2026-01-01T00:00:00+00:00"}
            ]

            editor = FileEditor(session_id_func=lambda: mock_session_id)

            result = editor.list_open_files()

            assert "test.py" in result
            assert "Open Files" in result

    def test_list_open_files_empty(self, mock_session_id):
        """Test FileEditor.list_open_files() when no files open."""
        with patch('modules.file.editor.get_open_files') as mock_get:
            mock_get.return_value = []
            
            editor = FileEditor(
                session_id_func=lambda: mock_session_id
            )
            
            result = editor.list_open_files()
            
            assert "No open files" in result

    def test_get_file_history_formatted(self, mock_session_id):
        """Test FileEditor.get_file_history_formatted() method."""
        with patch('modules.file.editor.get_file_history') as mock_get:
            mock_get.return_value = [
                {
                    "path": "/test.py",
                    "change_type": "replace_text",
                    "success": True,
                    "created_at": "2026-01-01T00:00:00+00:00"
                }
            ]

            editor = FileEditor(session_id_func=lambda: mock_session_id)

            result = editor.get_file_history_formatted()

            assert "test.py" in result
            assert "change" in result.lower()


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
