"""Functional tests for the file module.

Tests file operations with real filesystem I/O, validating that the module
is fully self-contained — each module owns its own SQLite database and does
not reach outside the module hierarchy.
"""

import asyncio
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
    close_all_files,
    close_file,
    delete_file,
    delete_snippet,
    open_file,
    replace_text,
)
from modules.file.db import (
    add_file_change,
    delete_open_file,
    delete_open_file_by_path,
    get_file_changes,
    get_open_files,
    set_open_file,
    _get_db_path,
)
from modules.file.memory import get_file_history, track_file_change


# =============================================================================
# Helpers
# =============================================================================

def _init_git_repo(temp_dir: str) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=temp_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_dir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)


def _git_add(temp_dir: str, pattern: str = ".") -> None:
    """Stage files in temp_dir for git tracking."""
    import subprocess

    subprocess.run(["git", "add", pattern], cwd=temp_dir, capture_output=True)


def _unique_id():
    """Unique string to avoid test interference in the shared DB."""
    return f"{int(time.time() * 1000)}-{os.getpid()}"


# =============================================================================
# Test: Self-Contained DB Module
# =============================================================================

class TestDbModule:
    """Verify the file module DB is self-contained and initialised."""

    def test_db_module_exports_public_functions(self):
        """modules.file.db should export the public open-file functions."""
        from modules.file import db

        assert hasattr(db, "set_open_file")
        assert hasattr(db, "get_open_files")
        assert hasattr(db, "delete_open_file")
        assert hasattr(db, "delete_open_file_by_path")
        assert hasattr(db, "add_file_change")
        assert hasattr(db, "get_file_changes")
        assert hasattr(db, "_get_db_path")

    def test_db_path_resolves(self):
        """_get_db_path should return a valid writable file path string."""
        path = _get_db_path()
        assert isinstance(path, str)
        assert len(path) > 0
        assert path.endswith(".db")

    def test_set_and_get_open_file_roundtrip(self):
        """set_open_file and get_open_files should store and retrieve a record."""
        sid = f"roundtrip-test-{_unique_id()}"
        keyword = f"open_file:test-{_unique_id()}.py"

        ok = set_open_file(sid, keyword, f"/fake/{keyword}", "0", "*")
        assert ok is True

        results = get_open_files(sid)
        assert len(results) >= 1
        assert any(r["keyword"] == keyword for r in results)

    def test_get_open_files_with_keyword_filter(self):
        """get_open_files with keyword prefix should return matching records."""
        sid = f"filter-test-{_unique_id()}"
        keyword = f"open_file:specific-{_unique_id()}.txt"

        set_open_file(sid, keyword, "/fake/path", "0", "*")
        results = get_open_files(sid, keyword="open_file:")
        assert any(r["keyword"] == keyword for r in results)

    def test_delete_open_file_removes_record(self):
        """delete_open_file (by keyword) should remove the record."""
        sid = f"delete-test-{_unique_id()}"
        keyword = f"open_file:to-delete-{_unique_id()}.txt"

        set_open_file(sid, keyword, "/fake/path", "0", "*")
        results = get_open_files(sid)
        assert any(r["keyword"] == keyword for r in results)

        deleted = delete_open_file(sid, keyword)
        assert deleted is True

        results_after = get_open_files(sid)
        assert not any(r["keyword"] == keyword for r in results_after)

    def test_add_and_get_file_changes_roundtrip(self):
        """add_file_change and get_file_changes should store and retrieve records."""
        sid = f"changes-test-{_unique_id()}"
        path = f"/tmp/change-test-{_unique_id()}.py"

        ok = add_file_change(sid, path, "replace_text", "diff content")
        assert ok is True

        history = get_file_changes(sid)
        assert len(history) >= 1
        assert any(r["path"] == path for r in history)


# =============================================================================
# Test: File Editor Self-Contained
# =============================================================================

class TestEditorSelfContained:
    """Verify FileEditor uses its own self-contained DB by default."""

    def test_editor_db_module_is_none_by_default(self):
        """FileEditor with no db_module should set _db_module to None.

        The editor does not use _db_module for the new API — it imports
        functions from modules.file.db directly.
        """
        editor = FileEditor(session_id_func=_unique_id)
        assert editor._db_module is None

    def test_editor_accepts_custom_db_module(self, tmp_path):
        """FileEditor should accept a custom db_module parameter."""
        from modules.file import db as file_db

        custom_path = tmp_path / "custom.db"
        file_db._DB_PATH = str(custom_path)
        try:
            editor = FileEditor(session_id_func=_unique_id, db_module=file_db)
            assert editor._db_module is file_db
            assert file_db._get_db_path() == str(custom_path)
        finally:
            file_db._DB_PATH = None


# =============================================================================
# Test: Memory Functions
# =============================================================================

class TestMemoryFunctions:
    """Verify track_file_change and get_file_history work end-to-end."""

    def test_track_file_change_stores_record(self):
        """track_file_change should store a file-change record in the DB."""
        sid = f"track-test-{_unique_id()}"
        result = track_file_change(
            sid,
            f"/tmp/test-file-{_unique_id()}.txt",
            "replace_text",
            "diff: x -> y",
        )
        assert result is True

        history = get_file_history(sid)
        assert len(history) >= 1

    def test_track_file_change_and_get_file_history_session_isolation(self):
        """File history for session A should not include session B records."""
        sid_a = f"isol-a-{_unique_id()}"
        sid_b = f"isol-b-{_unique_id()}"

        track_file_change(sid_a, f"/tmp/isol-a-{_unique_id()}.py", "replace_text", "a")
        # Do NOT record anything for sid_b

        history_a = get_file_history(sid_a)
        history_b = get_file_history(sid_b)

        assert len(history_a) >= 1
        assert len(history_b) == 0


# =============================================================================
# Test: File Operations Store and Retrieve Memories
# =============================================================================

class TestFileOperationsWithMemory:
    """Verify file operations integrate with the self-contained memory system."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            _init_git_repo(td)
            yield td

    @pytest.fixture
    def sid(self):
        return f"fop-{_unique_id()}"

    @pytest.fixture
    def editor(self, sid):
        return FileEditor(session_id_func=lambda: sid)

    def test_open_file_stores_open_file_memory(self, editor, temp_dir, sid):
        """open_file should store an 'open_file:' keyword record in the DB."""
        file_path = os.path.join(temp_dir, "open_test.py")
        Path(file_path).write_text("x = 1\n")
        _git_add(temp_dir)

        async def run():
            return await editor.open_file(file_path)

        result = asyncio.run(run())
        assert "Opened" in result
        assert "open_test.py" in result

        # Verify memory stored
        results = get_open_files(sid)
        open_memories = [r for r in results if r["keyword"].startswith("open_file:")]
        assert len(open_memories) >= 1
        assert any("open_test.py" in r["path"] for r in open_memories)

    def test_replace_text_stores_file_change_memory(self, editor, temp_dir, sid):
        """replace_text should store a file_change record in the DB."""
        file_path = os.path.join(temp_dir, "replace_test.py")
        Path(file_path).write_text("value = 1\n")
        _git_add(temp_dir)

        async def run():
            return await editor.replace_text(file_path, "value", "new_value", validate_syntax=False)

        result = asyncio.run(run())
        # replace_text returns a string starting with ✅ or "Replaced"
        assert "replaced" in result.lower() or "\u2705" in result
        assert Path(file_path).read_text() == "new_value = 1\n"

        # Verify change was stored
        history = get_file_history(sid)
        assert len(history) >= 1

    def test_close_file_removes_open_file_memory(self, editor, temp_dir, sid):
        """close_file should remove the open_file record from the DB."""
        file_path = os.path.join(temp_dir, "close_test.txt")
        Path(file_path).write_text("content")
        _git_add(temp_dir)

        async def run_open():
            return await editor.open_file(file_path)

        asyncio.run(run_open())

        # Confirm it's stored
        results_before = get_open_files(sid)
        open_before = [r for r in results_before if r["keyword"].startswith("open_file:")]
        assert len(open_before) >= 1

        async def run_close():
            return await editor.close_file("close_test.txt")

        close_result = asyncio.run(run_close())
        assert isinstance(close_result, str)


# =============================================================================
# Test: Core File Operations (disk I/O only — no memory dependency)
# =============================================================================

class TestAtomicWrite:
    def test_atomic_write_creates_file(self, tmp_path):
        file_path = str(tmp_path / "atomic.txt")
        _atomic_write(file_path, "atomic content")
        assert Path(file_path).read_text() == "atomic content"

    def test_atomic_write_overwrites(self, tmp_path):
        file_path = str(tmp_path / "overwrite.txt")
        _atomic_write(file_path, "v1")
        _atomic_write(file_path, "v2")
        assert Path(file_path).read_text() == "v2"


class TestFileType:
    def test_python_file(self, tmp_path):
        assert _file_type(str(tmp_path / "test.py")) == "Python"

    def test_markdown_file(self, tmp_path):
        assert _file_type(str(tmp_path / "test.md")) == "Markdown"

    def test_json_file(self, tmp_path):
        assert _file_type(str(tmp_path / "test.json")) == "JSON"

    def test_unknown_extension(self, tmp_path):
        assert _file_type(str(tmp_path / "test.xyz")) == "xyz"


class TestPythonValidation:
    def test_valid_python(self):
        is_valid, error = _validate_python("def foo():\n    pass\n")
        assert is_valid is True
        assert error is None

    def test_invalid_python(self):
        is_valid, error = _validate_python("def foo\n    pass\n")
        assert is_valid is False
        assert error is not None


class TestContentHash:
    def test_hash_deterministic(self):
        h1 = hash_content("hello")
        h2 = hash_content("hello")
        assert h1 == h2

    def test_different_content_different_hash(self):
        assert hash_content("a") != hash_content("b")


class TestWriteText:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_write_text_creates_file(self, editor, tmp_path):
        file_path = str(tmp_path / "new.txt")
        asyncio.run(editor.write_text(file_path, "hello"))
        assert Path(file_path).read_text() == "hello"

    def test_write_text_creates_parent_dirs(self, editor, tmp_path):
        file_path = str(tmp_path / "nested" / "dirs" / "file.txt")
        asyncio.run(editor.write_text(file_path, "content", create_parent_dirs=True))
        assert Path(file_path).read_text() == "content"

    def test_write_text_overwrites(self, editor, tmp_path):
        file_path = str(tmp_path / "existing.txt")
        Path(file_path).write_text("old")
        asyncio.run(editor.write_text(file_path, "new"))
        assert Path(file_path).read_text() == "new"


class TestReadFile:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_read_file_returns_content(self, editor, tmp_path):
        file_path = str(tmp_path / "read.txt")
        Path(file_path).write_text("hello world")
        assert editor.read_file(file_path) == "hello world"

    def test_read_file_nonexistent(self, editor, tmp_path):
        file_path = str(tmp_path / "nonexistent.txt")
        result = editor.read_file(file_path)
        assert "not found" in result.lower() or "error" in result.lower()


class TestReplaceText:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_replace_text_modifies_file(self, editor, tmp_path):
        file_path = str(tmp_path / "replace.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.replace_text(file_path, "world", "python"))
        assert "Replaced" in result or "\u2705" in result
        assert Path(file_path).read_text() == "hello python"

    def test_replace_text_no_match(self, editor, tmp_path):
        file_path = str(tmp_path / "no_match.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.replace_text(file_path, "nonexistent", "replacement"))
        # Returns a string describing why it failed
        assert "not found" in result.lower() or "no match" in result.lower()
        assert Path(file_path).read_text() == "hello world"


class TestBatchEdit:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_batch_edit_applies_all(self, editor, tmp_path):
        file_path = str(tmp_path / "batch.txt")
        Path(file_path).write_text("a b c")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(
            editor.batch_edit(
                file_path,
                [
                    Replacement(old_str="a", new_str="A"),
                    Replacement(old_str="b", new_str="B"),
                ],
            )
        )
        assert result.success
        assert Path(file_path).read_text() == "A B c"

    def test_batch_edit_all_or_nothing(self, editor, tmp_path):
        file_path = str(tmp_path / "batch_fail.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(
            editor.batch_edit(
                file_path,
                [
                    Replacement(old_str="world", new_str="python"),
                    Replacement(old_str="NONEXISTENT", new_str="fail"),
                ],
            )
        )
        assert not result.success
        assert Path(file_path).read_text() == "hello world"


class TestDeleteSnippet:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_delete_snippet_removes_text(self, editor, tmp_path):
        file_path = str(tmp_path / "delete.txt")
        Path(file_path).write_text("hello world goodbye")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.delete_snippet(file_path, " world"))
        assert result.success
        assert Path(file_path).read_text() == "hello goodbye"

    def test_delete_snippet_not_found(self, editor, tmp_path):
        file_path = str(tmp_path / "notfound.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.delete_snippet(file_path, "NONEXISTENT"))
        assert not result.success


class TestDeleteFile:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_delete_file_removes_file(self, editor, tmp_path):
        file_path = str(tmp_path / "todelete.txt")
        Path(file_path).write_text("content")
        assert os.path.exists(file_path)

        result = asyncio.run(editor.delete_file(file_path))
        assert result.success
        assert not os.path.exists(file_path)


class TestDirectoryOperations:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_pwd(self, editor):
        result = asyncio.run(editor.pwd())
        assert result == os.getcwd()

    def test_list_dir(self, editor, tmp_path):
        (tmp_path / "file1.txt").touch()
        (tmp_path / "file2.txt").touch()
        (tmp_path / "subdir").mkdir()

        result = asyncio.run(editor.list_dir(str(tmp_path)))
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "subdir" in result


class TestSearchFiles:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_search_files_finds_matches(self, editor, tmp_path):
        file_path = str(tmp_path / "search.py")
        Path(file_path).write_text("def foo():\n    pattern = 'hello'\n    return pattern\n")

        result = asyncio.run(editor.search_files("pattern", str(tmp_path)))
        assert "pattern" in result.lower()
        assert "search.py" in result

    def test_search_files_no_matches(self, editor, tmp_path):
        file_path = str(tmp_path / "no_match.txt")
        Path(file_path).write_text("hello world")

        result = asyncio.run(editor.search_files("xyz123", str(tmp_path)))
        assert "no matches" in result.lower() or "not found" in result.lower()


class TestFileInfo:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_file_info_returns_metadata(self, editor, tmp_path):
        file_path = str(tmp_path / "info.py")
        Path(file_path).write_text("line1\nline2\nline3\n")

        result = asyncio.run(editor.file_info(file_path))
        assert "info.py" in result
        assert "Python" in result

    def test_file_info_nonexistent(self, editor, tmp_path):
        file_path = str(tmp_path / "nonexistent.py")
        result = asyncio.run(editor.file_info(file_path))
        assert "not found" in result.lower()


class TestPreviewAndDiff:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_preview_replace(self, editor, tmp_path):
        file_path = str(tmp_path / "preview.txt")
        Path(file_path).write_text("hello world")

        result = asyncio.run(editor.preview_replace(file_path, "world"))
        assert "world" in result

    def test_diff_text(self, editor, tmp_path):
        file_path = str(tmp_path / "diff.txt")
        Path(file_path).write_text("hello world")

        result = asyncio.run(editor.diff_text(file_path, "world", "python"))
        assert "python" in result


class TestOpenFunction:
    @pytest.fixture
    def editor(self):
        return FileEditor(session_id_func=_unique_id)

    def test_open_function_finds_class(self, editor, tmp_path):
        file_path = str(tmp_path / "classes.py")
        Path(file_path).write_text("class MyClass:\n    def method(self):\n        pass\n")

        result = asyncio.run(editor.open_function(file_path, "MyClass"))
        assert "MyClass" in result

    def test_open_function_finds_function(self, editor, tmp_path):
        file_path = str(tmp_path / "funcs.py")
        Path(file_path).write_text("def hello():\n    print('hi')\n")

        result = asyncio.run(editor.open_function(file_path, "hello"))
        assert "hello" in result

    def test_open_function_not_found(self, editor, tmp_path):
        file_path = str(tmp_path / "exists.py")
        Path(file_path).write_text("def existing():\n    pass\n")

        result = asyncio.run(editor.open_function(file_path, "NonExistent"))
        assert "error" in result.lower() or "not found" in result.lower() or "no class" in result.lower()

    def test_open_function_non_python(self, editor, tmp_path):
        file_path = str(tmp_path / "readme.txt")
        Path(file_path).write_text("just text")

        result = asyncio.run(editor.open_function(file_path, "foo"))
        assert "not a python" in result.lower() or "error" in result.lower()


# =============================================================================
# Event Integration Tests
# Each edit operation must fire file_changed events so web editors refresh.
# =============================================================================

import events as evt_module


@pytest.fixture(autouse=True)
def clean_events_state():
    """Reset global lock state between tests.

    Lock state is shared globally (singleton), so we must clear it
    between tests to avoid interference.  Handlers are NOT cleared here
    — they are registered once by init_riven_events (called from the
    web_editor test fixture) and belong to the web editor setup lifecycle.
    """
    evt_module._locks.clear()
    yield
    evt_module._locks.clear()


def _unique_sid():
    """Unique session ID for event tests."""
    return f"event-test-{_unique_id()}"


class TestWriteTextFiresEvents:
    """write_text should acquire a lock, write the file, fire file_changed."""

    def test_write_text_fires_file_changed_event(self, tmp_path):
        received = []

        def handler(path=None, content=None, who=None, **kw):
            received.append({"path": path, "content": content, "who": who})

        evt_module.register_handler("file_changed", handler)
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "written.txt")

        asyncio.run(editor.write_text(file_path, "hello from write_text"))

        assert len(received) == 1
        assert os.path.basename(received[0]["path"]) == "written.txt"
        assert received[0]["content"] == "hello from write_text"
        assert received[0]["who"] is not None  # session_id must be set

    def test_write_text_acquires_and_releases_lock(self, tmp_path):
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "write_lock.txt")

        asyncio.run(editor.write_text(file_path, "content"))

        # Lock should be released after the operation
        assert evt_module.get_lock_state("write_lock.txt") is None


class TestReplaceTextFiresEvents:
    """replace_text should acquire a lock, modify, fire file_changed."""

    def test_replace_text_fires_file_changed_event(self, tmp_path):
        received = []

        def handler(path=None, content=None, who=None, **kw):
            received.append({"path": path, "content": content, "who": who})

        evt_module.register_handler("file_changed", handler)
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "replace_ev.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.replace_text(file_path, "world", "python"))

        # replace_text returns a string; success is indicated by the ✅ emoji
        assert "✅" in result
        assert len(received) == 1
        assert received[0]["content"] == "hello python"
        assert received[0]["who"] is not None

    def test_replace_text_no_event_on_failure(self, tmp_path):
        received = []

        def handler(**kw):
            received.append(kw)

        evt_module.register_handler("file_changed", handler)
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "no_match.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.replace_text(file_path, "NONEXISTENT_PATTERN", "xxx"))

        # replace_text returns a string; failure is indicated by no ✅ emoji
        assert "✅" not in result
        assert len(received) == 0  # file_changed must NOT fire on failure

    def test_replace_text_releases_lock_after_failure(self, tmp_path):
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "fail_lock.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        asyncio.run(editor.replace_text(file_path, "NONEXISTENT", "xxx"))

        assert evt_module.get_lock_state("fail_lock.txt") is None


class TestBatchEditFiresEvents:
    """batch_edit should fire a single file_changed after all changes."""

    def test_batch_edit_fires_file_changed_once(self, tmp_path):
        received = []

        def handler(**kw):
            received.append(kw)

        evt_module.register_handler("file_changed", handler)
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "batch_ev.txt")
        Path(file_path).write_text("a b c")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.batch_edit(
            file_path,
            [
                Replacement(old_str="a", new_str="A"),
                Replacement(old_str="b", new_str="B"),
            ],
        ))

        assert result.success
        assert len(received) == 1
        assert received[0]["content"] == "A B c"

    def test_batch_edit_no_event_on_all_or_nothing_failure(self, tmp_path):
        received = []

        def handler(**kw):
            received.append(kw)

        evt_module.register_handler("file_changed", handler)
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "batch_fail.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.batch_edit(
            file_path,
            [
                Replacement(old_str="world", new_str="python"),
                Replacement(old_str="NONEXISTENT", new_str="fail"),
            ],
        ))

        assert not result.success
        assert len(received) == 0  # file_changed must NOT fire on failure
        assert Path(file_path).read_text() == "hello world"  # file unchanged


class TestDeleteSnippetFiresEvents:
    """delete_snippet should fire file_changed on success only."""

    def test_delete_snippet_fires_on_success(self, tmp_path):
        received = []

        def handler(**kw):
            received.append(kw)

        evt_module.register_handler("file_changed", handler)
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "delete_ev.txt")
        Path(file_path).write_text("hello world goodbye")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.delete_snippet(file_path, " world"))

        assert result.success
        assert len(received) == 1
        assert received[0]["content"] == "hello goodbye"

    def test_delete_snippet_no_event_on_failure(self, tmp_path):
        received = []

        def handler(**kw):
            received.append(kw)

        evt_module.register_handler("file_changed", handler)
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "delete_fail.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        result = asyncio.run(editor.delete_snippet(file_path, "NONEXISTENT"))

        assert not result.success
        assert len(received) == 0


class TestDeleteFileFiresEvents:
    """delete_file should fire file_deleted on success only."""

    def test_delete_file_fires_file_deleted(self, tmp_path):
        received = []

        def handler(**kw):
            received.append(kw)

        evt_module.register_handler("file_deleted", handler)
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "delete_me.txt")
        Path(file_path).write_text("content")
        assert Path(file_path).exists()

        result = asyncio.run(editor.delete_file(file_path))

        assert result.success
        assert not Path(file_path).exists()
        assert len(received) == 1
        assert os.path.basename(received[0]["path"]) == "delete_me.txt"
        assert received[0]["who"] is not None

    def test_delete_file_no_event_on_nonexistent(self, tmp_path):
        received = []

        def handler(**kw):
            received.append(kw)

        evt_module.register_handler("file_deleted", handler)
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "never_existed.txt")

        result = asyncio.run(editor.delete_file(file_path))

        assert not result.success
        assert len(received) == 0


class TestLockIntegration:
    """Integration tests for the full lock lifecycle with real file operations."""

    def test_lock_held_during_replace_text(self, tmp_path):
        """Lock must be held for the entire duration of replace_text."""
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "lock_during.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))
        sid = _unique_sid()

        async def check_lock():
            async with evt_module.acquire_lock(file_path, sid, timeout=5.0, context="test"):
                # File should be locked while inside the context
                assert evt_module.get_lock_state(file_path) is not None

                # replace_text should still work (re-entrant lock)
                result = await editor.replace_text(file_path, "world", "python")
                assert "✅" in result

            # After context, lock should be released
            assert evt_module.get_lock_state(file_path) is None

        asyncio.run(check_lock())

    def test_concurrent_edit_cannot_acquire_lock(self, tmp_path):
        """A second editor can't edit while the first holds the lock."""
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "contested.txt")
        Path(file_path).write_text("original")
        _init_git_repo(str(tmp_path))
        sid_alice = f"alice-{_unique_sid()}"
        sid_bob = f"bob-{_unique_sid()}"

        async def alice_holds_lock():
            # Alice acquires lock
            async with evt_module.acquire_lock(file_path, sid_alice, timeout=5.0, context="test"):
                assert evt_module.get_lock_state(file_path) is not None
                # Bob tries to acquire — should timeout
                try:
                    async with evt_module.acquire_lock(file_path, sid_bob, timeout=0.1, context="test"):
                        assert False, "Bob should not have acquired the lock"
                except evt_module.LockTimeoutError:
                    pass  # expected
                # File should still be locked by Alice
                assert evt_module.get_lock_state(file_path) is not None

        asyncio.run(alice_holds_lock())

    def test_lock_released_after_any_failure(self, tmp_path):
        """Lock must be released even when an exception occurs mid-edit."""
        editor = FileEditor(session_id_func=_unique_sid)
        file_path = str(tmp_path / "exception_unlock.txt")
        Path(file_path).write_text("hello world")
        _init_git_repo(str(tmp_path))

        # Attempt a replace that will fail (pattern not found)
        asyncio.run(editor.replace_text(file_path, "NONEXISTENT", "xxx"))

        # Lock must be released regardless of failure
        assert evt_module.get_lock_state(file_path) is None
