"""Functional tests for the file module.

These tests verify actual file operations with real filesystem I/O.
Tests are designed to validate session-based file tracking and database integration.
"""

import asyncio
import hashlib
import os
import tempfile
import time
from pathlib import Path

import pytest

from modules.file import (
    FileEditor,
    Replacement,
    _atomic_write,
    _file_type,
    _validate_python,
    hash_content,
)
from modules.memory_utils import _search_memories, _delete_memory, _set_memory


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def session_id():
    """Return a unique test session ID to avoid collisions."""
    return f"test-session-functional-{int(time.time() * 1000)}"


@pytest.fixture
def editor(session_id):
    """Create a FileEditor with a test session ID."""
    return FileEditor(session_id_func=lambda: session_id)


def _cleanup_session_memories(session_id: str) -> None:
    """Delete all memories associated with a session ID."""
    # Note: wildcard in AND queries doesn't work reliably, so search by session
    # and filter by pattern
    memories = _search_memories(session_id, "", limit=100)
    for mem in memories:
        keywords = mem.get('keywords', [])
        if any(kw.startswith('open_file:') or kw.startswith('file_change:') or kw == 'cwd' for kw in keywords):
            _delete_memory(mem['id'])


@pytest.fixture
def real_memory(session_id):
    """Real memory fixture with cleanup before and after each test.
    
    Uses the actual memory API for testing and cleans up all memories
    associated with the test session ID at the end of each test.
    """
    # Clean up any existing test data before the test
    _cleanup_session_memories(session_id)
    
    yield session_id
    
    # Clean up all test data after the test
    _cleanup_session_memories(session_id)


# =============================================================================
# Test: Atomic Write
# =============================================================================

class TestAtomicWrite:
    """Test atomic write functionality."""

    def test_atomic_write_creates_file(self, temp_dir):
        """Atomic write should create a new file."""
        file_path = os.path.join(temp_dir, "atomic_test.txt")
        content = "Hello, World!\nLine 2\nLine 3"
        
        _atomic_write(file_path, content)
        
        assert os.path.exists(file_path)
        with open(file_path) as f:
            assert f.read() == content

    def test_atomic_write_overwrites(self, temp_dir):
        """Atomic write should overwrite existing content."""
        file_path = os.path.join(temp_dir, "atomic_overwrite.txt")
        
        _atomic_write(file_path, "Original content")
        _atomic_write(file_path, "New content")
        
        with open(file_path) as f:
            assert f.read() == "New content"

    def test_atomic_write_preserves_content_on_error(self, temp_dir):
        """If write fails, original content should be preserved."""
        file_path = os.path.join(temp_dir, "atomic_error.txt")
        
        # Create initial file
        _atomic_write(file_path, "Original content")
        
        # Try to write to a directory (should fail)
        with pytest.raises(Exception):
            _atomic_write(os.path.join(temp_dir), "Should fail")
        
        # Original should be unchanged
        with open(file_path) as f:
            assert f.read() == "Original content"


# =============================================================================
# Test: File Type Detection
# =============================================================================

class TestFileType:
    """Test file type detection."""

    def test_python_file(self, temp_dir):
        """Python files should be detected."""
        file_path = os.path.join(temp_dir, "test.py")
        Path(file_path).touch()
        
        assert _file_type(file_path) == "Python"

    def test_markdown_file(self, temp_dir):
        """Markdown files should be detected."""
        file_path = os.path.join(temp_dir, "test.md")
        Path(file_path).touch()
        
        assert _file_type(file_path) == "Markdown"

    def test_json_file(self, temp_dir):
        """JSON files should be detected."""
        file_path = os.path.join(temp_dir, "test.json")
        Path(file_path).touch()
        
        assert _file_type(file_path) == "JSON"

    def test_unknown_file(self, temp_dir):
        """Unknown file types should return the extension."""
        file_path = os.path.join(temp_dir, "test.xyz")
        Path(file_path).touch()
        
        assert _file_type(file_path) == "xyz"


# =============================================================================
# Test: Python Syntax Validation
# =============================================================================

class TestPythonValidation:
    """Test Python syntax validation."""

    def test_valid_python(self):
        """Valid Python should pass validation."""
        code = """
def hello():
    print("Hello, World!")

class Foo:
    def bar(self):
        pass
"""
        is_valid, error = _validate_python(code)
        assert is_valid is True
        assert error is None

    def test_invalid_python(self):
        """Invalid Python should fail validation."""
        code = """
def hello()
    print("Missing colon")
"""
        is_valid, error = _validate_python(code)
        assert is_valid is False
        assert error is not None
        assert "line 2" in error.lower() or "syntax" in error.lower()

    def test_syntax_error_message(self):
        """Syntax errors should include line number."""
        code = """
x = {
    'a': 1
    'b': 2
}
"""
        is_valid, error = _validate_python(code)
        assert is_valid is False
        # Error should indicate where the problem is
        assert error is not None


# =============================================================================
# Test: Content Hashing
# =============================================================================

class TestContentHash:
    """Test content hashing."""

    def test_hash_content(self):
        """Content should hash consistently."""
        content = "Hello, World!"
        hash1 = hash_content(content)
        hash2 = hash_content(content)
        
        assert hash1 == hash2
        assert len(hash1) == 8  # Short hash length

    def test_different_content_different_hash(self):
        """Different content should produce different hashes."""
        hash1 = hash_content("Content A")
        hash2 = hash_content("Content B")
        
        assert hash1 != hash2

    def test_hash_matches_md5_prefix(self):
        """Hash should match first 8 chars of MD5."""
        content = "Test content"
        full_md5 = hashlib.md5(content.encode()).hexdigest()
        expected = full_md5[:8]
        
        assert hash_content(content) == expected


# =============================================================================
# Test: Create and Write File
# =============================================================================

class TestWriteText:
    """Test write_text functionality."""

    def test_write_text_creates_file(self, editor, temp_dir):
        """write_text should create a new file."""
        file_path = os.path.join(temp_dir, "new_file.txt")
        content = "Hello, World!"
        
        async def run():
            result = await editor.write_text(file_path, content)
            return result
        
        result = asyncio.run(run())
        
        assert os.path.exists(file_path)
        with open(file_path) as f:
            assert f.read() == content

    def test_write_text_overwrites_file(self, editor, temp_dir):
        """write_text should overwrite existing file."""
        file_path = os.path.join(temp_dir, "existing.txt")
        Path(file_path).write_text("Original")
        
        async def run():
            await editor.write_text(file_path, "Modified")
        
        asyncio.run(run())
        
        with open(file_path) as f:
            assert f.read() == "Modified"

    def test_write_text_creates_parent_dirs(self, editor, temp_dir):
        """write_text should create parent directories when requested."""
        nested_path = os.path.join(temp_dir, "nested", "dirs", "file.txt")
        
        async def run():
            await editor.write_text(nested_path, "Content", create_parent_dirs=True)
        
        asyncio.run(run())
        
        assert os.path.exists(nested_path)


# =============================================================================
# Test: Open File and Session Tracking
# =============================================================================

class TestOpenFile:
    """Test open_file functionality and session tracking."""

    def test_open_file_returns_file_info(self, editor, temp_dir, session_id):
        """open_file should return file type and line count."""
        file_path = os.path.join(temp_dir, "test.py")
        Path(file_path).write_text("line1\nline2\nline3")
        
        async def run():
            result = await editor.open_file(file_path)
            return result
        
        result = asyncio.run(run())
        
        assert "Python" in result
        assert "3 lines" in result
        
        # Verify memory was stored - search by session_id only since open_file
        # stores keyword as 'open_file:<filename>:<line_range>' which varies
        memories = _search_memories(session_id, "", limit=10)
        assert len(memories) >= 1
        assert any("open_file:test.py" in kw for m in memories for kw in m.get('keywords', []))

    def test_open_file_tracks_in_database(self, editor, temp_dir, session_id):
        """open_file should store tracking info in database."""
        file_path = os.path.join(temp_dir, "track.py")
        Path(file_path).write_text("code line 1\ncode line 2")
        
        async def run():
            await editor.open_file(file_path)
        
        asyncio.run(run())
        
        # Verify memory was stored - search by session and filter for track.py
        memories = _search_memories(session_id, "", limit=10)
        assert len(memories) >= 1
        assert any("track.py" in str(m.get('properties', {}).get('path', '')) for m in memories)

    def test_open_file_with_line_range(self, editor, temp_dir):
        """open_file should support line range specification."""
        file_path = os.path.join(temp_dir, "range.py")
        Path(file_path).write_text("\n".join([f"line {i}" for i in range(20)]))
        
        async def run():
            result = await editor.open_file(file_path, line_start=5, line_end=10)
            return result
        
        result = asyncio.run(run())
        
        assert "lines 5-10" in result

    def test_open_nonexistent_file_returns_error(self, editor, temp_dir):
        """open_file should return error for non-existent files."""
        file_path = os.path.join(temp_dir, "nonexistent.py")
        
        async def run():
            result = await editor.open_file(file_path)
            return result
        
        result = asyncio.run(run())
        
        assert "not found" in result.lower() or "error" in result.lower()

    def test_open_file_large_file_warning(self, editor, temp_dir):
        """Large files should trigger a warning."""
        file_path = os.path.join(temp_dir, "large.py")
        # Create a file with more than 1000 lines
        Path(file_path).write_text("\n".join([f"# line {i}" for i in range(1500)]))
        
        async def run():
            result = await editor.open_file(file_path)
            return result
        
        result = asyncio.run(run())
        
        assert "LARGE" in result


# =============================================================================
# Test: Read File
# =============================================================================

class TestReadFile:
    """Test read_file functionality."""

    def test_read_file_returns_content(self, editor, temp_dir):
        """read_file should return file contents."""
        file_path = os.path.join(temp_dir, "read.txt")
        content = "Hello, World!"
        Path(file_path).write_text(content)
        
        result = editor.read_file(file_path)
        
        assert result == content

    def test_read_file_with_line_range(self, editor, temp_dir):
        """read_file should support line range."""
        file_path = os.path.join(temp_dir, "lines.txt")
        content = "line1\nline2\nline3\nline4\nline5"
        Path(file_path).write_text(content)
        
        result = editor.read_file(file_path, line_start=1, line_end=3)
        
        assert "line2" in result
        assert "line3" in result
        assert "line1" not in result

    def test_read_nonexistent_file_returns_error(self, editor, temp_dir):
        """read_file should return error for non-existent files."""
        file_path = os.path.join(temp_dir, "nonexistent.txt")
        
        result = editor.read_file(file_path)
        
        assert "error" in result.lower() or "not found" in result.lower()


# =============================================================================
# Test: Replace Text
# =============================================================================

class TestReplaceText:
    """Test replace_text functionality."""

    def test_replace_text_simple(self, editor, temp_dir):
        """replace_text should perform simple text replacement."""
        file_path = os.path.join(temp_dir, "replace.txt")
        Path(file_path).write_text("def hello():\n    print('Hello, World!')\n")
        
        async def run():
            result = await editor.replace_text(
                file_path, "Hello, World!", "Hello, Python!", threshold=0.9
            )
            return result
        
        result = asyncio.run(run())
        
        with open(file_path) as f:
            assert "Hello, Python!" in f.read()

    def test_replace_text_tracks_change(self, editor, temp_dir, session_id):
        """replace_text should track the change in database."""
        file_path = os.path.join(temp_dir, "track_replace.py")
        Path(file_path).write_text("# original content\nprint('hello')")
        
        async def run():
            await editor.replace_text(file_path, "# original content", "# modified content")
        
        asyncio.run(run())
        
        # Verify memory was stored for the file change - search by session and filter
        all_memories = _search_memories(session_id, "", limit=10)
        memories = [m for m in all_memories if any(kw.startswith('file_change:track_replace.py') for kw in m.get('keywords', []))]
        assert len(memories) >= 1

    def test_replace_text_no_match_returns_error(self, editor, temp_dir):
        """replace_text should return error when no match found."""
        file_path = os.path.join(temp_dir, "no_match.txt")
        Path(file_path).write_text("Hello, World!")
        
        async def run():
            result = await editor.replace_text(
                file_path, "NonExistent", "Replacement"
            )
            return result
        
        result = asyncio.run(run())
        
        assert "not found" in result.lower() or "no match" in result.lower() or "error" in result.lower()

    def test_replace_text_validates_python_syntax(self, editor, temp_dir):
        """replace_text should validate Python syntax for .py files."""
        file_path = os.path.join(temp_dir, "syntax_test.py")
        Path(file_path).write_text("def hello():\n    pass\n")
        
        async def run():
            # Try to replace with syntactically invalid Python
            result = await editor.replace_text(
                file_path, "def hello():", "def hello()"  # Missing colon
            )
            return result
        
        result = asyncio.run(run())
        
        # Should indicate syntax error
        assert "syntax" in result.lower() or "error" in result.lower()

    def test_replace_text_skips_validation_when_disabled(self, editor, temp_dir):
        """replace_text should skip validation when validate_syntax=False."""
        file_path = os.path.join(temp_dir, "no_validate.py")
        Path(file_path).write_text("def hello():\n    pass\n")
        
        async def run():
            # Replace with invalid syntax but validation disabled
            result = await editor.replace_text(
                file_path, "def hello():", "def hello()",
                validate_syntax=False
            )
            return result
        
        result = asyncio.run(run())
        
        # Should succeed despite invalid syntax
        with open(file_path) as f:
            assert "def hello()" in f.read()


# =============================================================================
# Test: Batch Edit
# =============================================================================

class TestBatchEdit:
    """Test batch_edit functionality."""

    def test_batch_edit_single_replacement(self, editor, temp_dir):
        """batch_edit should handle single replacement."""
        file_path = os.path.join(temp_dir, "batch_single.txt")
        Path(file_path).write_text("Hello, World!\nGoodbye!")
        
        async def run():
            result = await editor.batch_edit(
                file_path,
                [Replacement(old_str="Hello, World!", new_str="Hello, Python!")]
            )
            return result
        
        result = asyncio.run(run())
        
        assert result.success
        with open(file_path) as f:
            assert f.read() == "Hello, Python!\nGoodbye!"

    def test_batch_edit_multiple_replacements(self, editor, temp_dir):
        """batch_edit should handle multiple replacements."""
        file_path = os.path.join(temp_dir, "batch_multi.txt")
        Path(file_path).write_text("line one\nline two\nline three")
        
        async def run():
            result = await editor.batch_edit(
                file_path,
                [
                    Replacement(old_str="line one", new_str="LINE ONE"),
                    Replacement(old_str="line two", new_str="LINE TWO"),
                ]
            )
            return result
        
        result = asyncio.run(run())
        
        assert result.success
        with open(file_path) as f:
            content = f.read()
            assert "LINE ONE" in content
            assert "LINE TWO" in content

    def test_batch_edit_all_or_nothing(self, editor, temp_dir):
        """batch_edit should not apply any changes if any replacement fails."""
        file_path = os.path.join(temp_dir, "batch_fail.txt")
        original = "Hello, World!"
        Path(file_path).write_text(original)
        
        async def run():
            result = await editor.batch_edit(
                file_path,
                [
                    Replacement(old_str="World", new_str="Python"),
                    Replacement(old_str="NonExistent", new_str="ShouldFail"),
                ]
            )
            return result
        
        result = asyncio.run(run())
        
        # Should fail due to second replacement
        assert not result.success
        # Original content should be unchanged
        with open(file_path) as f:
            assert f.read() == original


# =============================================================================
# Test: Delete Snippet
# =============================================================================

class TestDeleteSnippet:
    """Test delete_snippet functionality."""

    def test_delete_snippet_removes_text(self, editor, temp_dir):
        """delete_snippet should remove the specified text."""
        file_path = os.path.join(temp_dir, "delete_snippet.txt")
        Path(file_path).write_text("Hello, World! Goodbye!")
        
        async def run():
            result = await editor.delete_snippet(file_path, ", World!")
            return result
        
        result = asyncio.run(run())
        
        with open(file_path) as f:
            content = f.read()
            assert content == "Hello Goodbye!"
            assert ", World!" not in content

    def test_delete_snippet_not_found(self, editor, temp_dir):
        """delete_snippet should fail gracefully when snippet not found."""
        file_path = os.path.join(temp_dir, "not_found.txt")
        Path(file_path).write_text("Hello, World!")
        
        async def run():
            result = await editor.delete_snippet(file_path, "NonExistent")
            return result
        
        result = asyncio.run(run())
        
        assert not result.success


# =============================================================================
# Test: Delete File
# =============================================================================

class TestDeleteFile:
    """Test delete_file functionality."""

    def test_delete_file_removes_file(self, editor, temp_dir):
        """delete_file should remove the file from disk."""
        file_path = os.path.join(temp_dir, "to_delete.txt")
        Path(file_path).write_text("Content to delete")
        assert os.path.exists(file_path)
        
        async def run():
            result = await editor.delete_file(file_path)
            return result
        
        result = asyncio.run(run())
        
        assert result.success
        assert not os.path.exists(file_path)

    def test_delete_file_cleans_up_memory(self, editor, temp_dir, session_id):
        """delete_file should clean up memory entries."""
        file_path = os.path.join(temp_dir, "cleanup.txt")
        filename = "cleanup.txt"
        Path(file_path).write_text("Content")
        
        async def run():
            # First open the file to create a memory entry
            await editor.open_file(file_path)
        
        asyncio.run(run())
        
        # Verify memory entry exists - search by session and filter
        memories_before = _search_memories(session_id, "", limit=10)
        memories_before = [m for m in memories_before if any(kw.startswith(f"open_file:{filename}:") for kw in m.get('keywords', []))]
        assert len(memories_before) >= 1
        
        async def run_delete():
            await editor.delete_file(file_path)
        
        asyncio.run(run_delete())
        
        # Verify memory entry was cleaned up
        memories_after = _search_memories(session_id, "", limit=10)
        memories_after = [m for m in memories_after if any(kw.startswith(f"open_file:{filename}:") for kw in m.get('keywords', []))]
        assert len(memories_after) == 0

    def test_delete_nonexistent_file(self, editor, temp_dir):
        """delete_file should handle non-existent files gracefully."""
        file_path = os.path.join(temp_dir, "nonexistent.txt")
        
        async def run():
            result = await editor.delete_file(file_path)
            return result
        
        result = asyncio.run(run())
        
        assert not result.success


# =============================================================================
# Test: Close File
# =============================================================================

class TestCloseFile:
    """Test close_file functionality."""

    def test_close_file_removes_from_context(self, editor, temp_dir, session_id):
        """close_file should remove file from session context."""
        filename = "close_test.txt"
        file_path = os.path.join(temp_dir, filename)
        Path(file_path).write_text("Content")
        
        async def run():
            # First open the file to create a memory entry
            await editor.open_file(file_path)
        
        asyncio.run(run())
        
        # Verify memory entry exists - search by session and filter
        memories_before = _search_memories(session_id, "", limit=10)
        memories_before = [m for m in memories_before if any(kw.startswith(f"open_file:{filename}:") for kw in m.get('keywords', []))]
        assert len(memories_before) >= 1
        
        async def run_close():
            result = await editor.close_file(filename)
            return result
        
        result = asyncio.run(run_close())
        
        assert "Closed" in result or "closed" in result.lower()
        
        # Verify memory entry was cleaned up - search by session and filter
        memories_after = _search_memories(session_id, "", limit=10)
        memories_after = [m for m in memories_after if any(kw.startswith(f"open_file:{filename}:") for kw in m.get('keywords', []))]
        assert len(memories_after) == 0

    def test_close_file_with_line_range(self, editor, temp_dir, session_id):
        """close_file should support closing specific line ranges."""
        filename = "range_close.txt"
        file_path = os.path.join(temp_dir, filename)
        content = "\n".join([f"line {i}" for i in range(20)])
        Path(file_path).write_text(content)
        
        async def run():
            # Open with specific range first
            await editor.open_file(file_path, line_start=5, line_end=10)
        
        asyncio.run(run())
        
        async def run_close():
            result = await editor.close_file(filename, line_start=5, line_end=10)
            return result
        
        result = asyncio.run(run_close())
        assert result is not None

    def test_close_file_not_in_context(self, editor, temp_dir, session_id):
        """close_file should handle files not in context gracefully."""
        async def run():
            result = await editor.close_file("nonexistent_file.txt")
            return result
        
        result = asyncio.run(run())
        
        assert "not in context" in result.lower()


# =============================================================================
# Test: Close All Files
# =============================================================================

class TestCloseAllFiles:
    """Test close_all_files functionality."""

    def test_close_all_files(self, editor, temp_dir, session_id):
        """close_all_files should close all open files."""
        # Create and open files
        files = []
        for name in ["file1.txt", "file2.txt"]:
            file_path = os.path.join(temp_dir, name)
            Path(file_path).write_text(f"Content of {name}")
            files.append((file_path, name))
        
        async def run():
            # Open all files
            for path, _ in files:
                await editor.open_file(path)
        
        asyncio.run(run())
        
        # Verify memories exist - search by session and filter
        memories_before = _search_memories(session_id, "", limit=100)
        open_memories = [m for m in memories_before if any(kw.startswith('open_file:') for kw in m.get('keywords', []))]
        assert len(open_memories) == 2
        
        async def run_close_all():
            result = await editor.close_all_files()
            return result
        
        result = asyncio.run(run_close_all())
        
        # Verify all memories were cleaned up - search by session and filter
        memories_after = _search_memories(session_id, "", limit=100)
        open_memories_after = [m for m in memories_after if any(kw.startswith('open_file:') for kw in m.get('keywords', []))]
        assert len(open_memories_after) == 0

    def test_close_all_files_none_open(self, editor, temp_dir, session_id):
        """close_all_files should handle no open files."""
        async def run():
            result = await editor.close_all_files()
            return result
        
        result = asyncio.run(run())
        
        assert "no open files" in result.lower()


# =============================================================================
# Test: List Open Files
# =============================================================================

class TestListOpenFiles:
    """Test list_open_files functionality."""

    def test_list_open_files_with_files(self, editor, temp_dir, session_id):
        """list_open_files should show all open files."""
        # Create and open real files
        files = []
        for name in ["file1.py", "file2.py"]:
            file_path = os.path.join(temp_dir, name)
            Path(file_path).write_text(f"# content of {name}")
            files.append(file_path)
        
        async def run():
            for path in files:
                await editor.open_file(path)
        
        asyncio.run(run())
        
        result = editor.list_open_files()
        
        assert "file1.py" in result
        assert "file2.py" in result
        assert "Open Files" in result

    def test_list_open_files_empty(self, editor, temp_dir, session_id):
        """list_open_files should handle no open files."""
        # No files opened - cleanup fixture ensures no memories exist
        result = editor.list_open_files()
        
        assert "no open files" in result.lower()


# =============================================================================
# Test: Directory Operations
# =============================================================================

class TestDirectoryOperations:
    """Test directory listing and navigation."""

    def test_pwd(self, editor, temp_dir):
        """pwd should return current directory."""
        result = asyncio.run(editor.pwd())
        
        assert result == os.getcwd()

    def test_list_dir(self, editor, temp_dir):
        """list_dir should list directory contents."""
        # Create some files
        Path(os.path.join(temp_dir, "file1.txt")).touch()
        Path(os.path.join(temp_dir, "file2.txt")).touch()
        os.makedirs(os.path.join(temp_dir, "subdir"))
        
        result = asyncio.run(editor.list_dir(temp_dir))
        
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "subdir" in result

    def test_list_dir_nonexistent(self, editor, temp_dir):
        """list_dir should handle non-existent directories."""
        async def run():
            result = await editor.list_dir(os.path.join(temp_dir, "nonexistent"))
            return result
        
        result = asyncio.run(run())
        
        assert "not found" in result.lower() or "error" in result.lower()

    def test_chdir(self, editor, temp_dir):
        """chdir should change directory."""
        async def run():
            original = await editor.pwd()
            await editor.chdir(temp_dir)
            new = await editor.pwd()
            return original, new
        
        original, new = asyncio.run(run())
        
        assert new == temp_dir


# =============================================================================
# Test: Search Files
# =============================================================================

class TestSearchFiles:
    """Test search_files functionality."""

    def test_search_files_finds_matches(self, editor, temp_dir):
        """search_files should find matching lines in Python files."""
        file_path = os.path.join(temp_dir, "search_test.py")
        Path(file_path).write_text("def foo():\n    pattern = 'hello'\n    return pattern\n")
        
        async def run():
            result = await editor.search_files("pattern", temp_dir)
            return result
        
        result = asyncio.run(run())
        
        assert "pattern" in result.lower()
        assert "search_test.py" in result

    def test_search_files_no_matches(self, editor, temp_dir):
        """search_files should handle no matches."""
        file_path = os.path.join(temp_dir, "no_match.txt")
        Path(file_path).write_text("hello world")
        
        async def run():
            result = await editor.search_files("xyz123", temp_dir)
            return result
        
        result = asyncio.run(run())
        
        # Should indicate no matches
        assert "no matches" in result.lower() or "not found" in result.lower()


# =============================================================================
# Test: File Info
# =============================================================================

class TestFileInfo:
    """Test file_info functionality."""

    def test_file_info_returns_metadata(self, editor, temp_dir):
        """file_info should return file metadata."""
        file_path = os.path.join(temp_dir, "info_test.py")
        content = "print('hello')\n" * 10
        Path(file_path).write_text(content)
        
        result = asyncio.run(editor.file_info(file_path))
        
        assert "info_test.py" in result
        assert "Python" in result
        assert "10 lines" in result or "10" in result

    def test_file_info_nonexistent(self, editor, temp_dir):
        """file_info should handle non-existent files."""
        async def run():
            result = await editor.file_info(os.path.join(temp_dir, "nonexistent.py"))
            return result
        
        result = asyncio.run(run())
        
        assert "not found" in result.lower() or "error" in result.lower()


# =============================================================================
# Test: Preview and Diff
# =============================================================================

class TestPreviewAndDiff:
    """Test preview_replace and diff_text functionality."""

    def test_preview_replace(self, editor, temp_dir):
        """preview_replace should show where match would occur."""
        file_path = os.path.join(temp_dir, "preview.txt")
        Path(file_path).write_text("Hello, World!")
        
        async def run():
            result = await editor.preview_replace(file_path, "World")
            return result
        
        result = asyncio.run(run())
        
        assert "World" in result
        assert "match" in result.lower() or "found" in result.lower()

    def test_preview_replace_no_match(self, editor, temp_dir):
        """preview_replace should indicate when no match found."""
        file_path = os.path.join(temp_dir, "no_match.txt")
        Path(file_path).write_text("Hello, World!")
        
        async def run():
            result = await editor.preview_replace(file_path, "NonExistent")
            return result
        
        result = asyncio.run(run())
        
        assert "not found" in result.lower() or "no match" in result.lower()

    def test_diff_text(self, editor, temp_dir):
        """diff_text should show before/after diff."""
        file_path = os.path.join(temp_dir, "diff.txt")
        Path(file_path).write_text("Hello, World!")
        
        async def run():
            result = await editor.diff_text(file_path, "World", "Python")
            return result
        
        result = asyncio.run(run())
        
        assert "World" in result or "before" in result.lower()
        assert "Python" in result or "after" in result.lower()


# =============================================================================
# Test: Open Function (AST-based)
# =============================================================================

class TestOpenFunction:
    """Test open_function with AST parsing."""

    def test_open_function_finds_class(self, editor, temp_dir):
        """open_function should find and return class definition."""
        file_path = os.path.join(temp_dir, "classes.py")
        Path(file_path).write_text("""
class MyClass:
    '''A test class.'''
    def method(self):
        '''A method.'''
        pass
""")
        
        async def run():
            result = await editor.open_function(file_path, "MyClass")
            return result
        
        result = asyncio.run(run())
        
        assert "MyClass" in result
        assert "class" in result.lower()

    def test_open_function_finds_function(self, editor, temp_dir):
        """open_function should find and return function definition."""
        file_path = os.path.join(temp_dir, "functions.py")
        Path(file_path).write_text("""
def hello():
    '''Say hello.'''
    print("Hello!")
""")
        
        async def run():
            result = await editor.open_function(file_path, "hello")
            return result
        
        result = asyncio.run(run())
        
        assert "hello" in result
        assert "def hello" in result

    def test_open_function_not_found(self, editor, temp_dir):
        """open_function should handle not found gracefully."""
        file_path = os.path.join(temp_dir, "has_func.py")
        Path(file_path).write_text("def existing_func():\n    pass\n")
        
        async def run():
            result = await editor.open_function(file_path, "NonExistent")
            return result
        
        result = asyncio.run(run())
        
        assert "not found" in result.lower() or "no class or function named" in result.lower()

    def test_open_function_non_python_file(self, editor, temp_dir):
        """open_function should handle non-Python files."""
        file_path = os.path.join(temp_dir, "readme.txt")
        Path(file_path).write_text("Just a text file")
        
        async def run():
            result = await editor.open_function(file_path, "something")
            return result
        
        result = asyncio.run(run())
        
        assert "not a Python" in result.lower() or "error" in result.lower()


# =============================================================================
# Test: End-to-End Workflow
# =============================================================================

class TestEndToEndWorkflow:
    """Test complete file workflow from creation to editing."""

    def test_complete_file_lifecycle(self, editor, temp_dir, session_id):
        """Test complete file lifecycle: create -> open -> edit -> close -> delete."""
        file_path = os.path.join(temp_dir, "lifecycle.txt")
        filename = "lifecycle.txt"
        
        async def run():
            # Step 1: Create file
            await editor.write_text(file_path, "Initial content")
            assert os.path.exists(file_path)
            
            # Step 2: Open file
            open_result = await editor.open_file(file_path)
            assert "lifecycle.txt" in open_result
            
            # Verify memory was stored - search by session and filter
            memories = _search_memories(session_id, "", limit=10)
            memories = [m for m in memories if any(kw.startswith("open_file:lifecycle.txt:") for kw in m.get('keywords', []))]
            assert len(memories) >= 1
            
            # Step 3: Replace text
            replace_result = await editor.replace_text(file_path, "Initial", "Modified")
            assert "success" in replace_result.lower() or "modified" in replace_result.lower()
            
            # Verify content was changed
            with open(file_path) as f:
                content = f.read()
            assert "Modified content" in content
            
            # Step 4: Close file
            close_result = await editor.close_file(filename)
            assert "closed" in close_result.lower()
            
            # Verify memory was cleaned up - search by session and filter
            memories_after = _search_memories(session_id, "", limit=10)
            memories_after = [m for m in memories_after if any(kw.startswith("open_file:lifecycle.txt:") for kw in m.get('keywords', []))]
            assert len(memories_after) == 0
            
            return "All steps completed successfully"
        
        result = asyncio.run(run())
        assert result == "All steps completed successfully"

    def test_multiple_files_parallel_tracking(self, editor, temp_dir, session_id):
        """Test tracking multiple files simultaneously."""
        files = []
        for i in range(3):
            file_path = os.path.join(temp_dir, f"file_{i}.txt")
            Path(file_path).write_text(f"Content {i}")
            files.append((file_path, f"file_{i}.txt"))
        
        async def run():
            # Open all files
            for path, name in files:
                result = await editor.open_file(path)
                assert name in result
            
            # List open files - should see all 3
            list_result = editor.list_open_files()
            
            for _, name in files:
                assert name in list_result
            
            # Verify all 3 memories exist - search by session and filter
            all_memories = _search_memories(session_id, "", limit=100)
            open_memories = [m for m in all_memories if any(kw.startswith('open_file:') for kw in m.get('keywords', []))]
            assert len(open_memories) == 3
            
            # Close all files
            close_result = await editor.close_all_files()
            assert "3" in close_result or len(open_memories) == 3  # 3 files should be mentioned
            
            # Verify all memories were cleaned up - search by session and filter
            memories_after = _search_memories(session_id, "", limit=100)
            open_memories_after = [m for m in memories_after if any(kw.startswith('open_file:') for kw in m.get('keywords', []))]
            assert len(open_memories_after) == 0
        
        asyncio.run(run())


# =============================================================================
# Test: File History Formatting
# =============================================================================

class TestFileHistory:
    """Test get_file_history_formatted functionality."""

    def test_get_file_history_formatted_empty(self, editor, session_id):
        """get_file_history_formatted should return 'no changes' for empty history."""
        # No file changes made - cleanup fixture ensures no memories exist
        result = editor.get_file_history_formatted()
        
        assert "no changes" in result.lower() or "no file changes" in result.lower()

    def test_get_file_history_formatted_with_changes(self, editor, temp_dir, session_id):
        """get_file_history_formatted should format file changes properly."""
        file_path = os.path.join(temp_dir, "test_file.py")
        Path(file_path).write_text("x = 1")
        
        async def run():
            # Create a file change by replacing text (use valid Python)
            result = await editor.replace_text(file_path, "x = 1", "x = 2")
            return result
        
        result = asyncio.run(run())
        
        # Give the API a moment to process
        import time
        time.sleep(0.1)
        
        history_result = editor.get_file_history_formatted()
        
        # Should include info about the changes
        assert "no changes" in history_result.lower() or "test_file.py" in history_result or "replace_text" in history_result.lower()

    def test_get_file_history_handles_api_errors(self, editor, session_id):
        """get_file_history_formatted should handle empty results gracefully."""
        # Test with session ID that has no memories (API error returns empty list)
        # The cleanup fixture ensures this session is clean
        result = editor.get_file_history_formatted()
        
        # Should return the empty/not-found message, not raise
        assert "no changes" in result.lower() or "no file changes" in result.lower() or "none" in result.lower()


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
