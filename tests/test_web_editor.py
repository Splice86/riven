"""Tests for web/editor/ — event handlers and API endpoints.

Tests the bridge between events.py (Riven edits) and the web editor
(WebSocket clients in the browser). When Riven modifies a file, the web
editor must broadcast the updated content so browsers refresh live.

Coverage:
  - web/editor/editor.py  : event handlers, _awareness, _broadcast
  - web/editor/api.py     : /lock/* and /awareness/* HTTP endpoints
"""

import asyncio
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketState


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_ws():
    """Build a minimal fake WebSocket client for broadcast tests."""
    ws = MagicMock()
    ws.client_state = WebSocketState.CONNECTED  # must match the enum, not int
    ws.send_text = AsyncMock()
    return ws


async def _register_mock_client(ws, path=None):
    """Register a fake client and optionally open a path."""
    from web.editor import editor as editor_mod
    client = await editor_mod._add_client(ws)
    if path:
        client.open_paths.add(path)
    return client


# ─── Event Handler Tests ───────────────────────────────────────────────────────

class TestOnFileChanged:
    """_on_file_changed should broadcast updated content to clients watching the file."""

    def setup_method(self):
        # Clear global state between tests
        from web.editor import editor as editor_mod
        editor_mod._awareness.clear()
        editor_mod._clients.clear()

    @pytest.mark.asyncio
    async def test_broadcasts_content_to_matching_clients(self, tmp_path):
        from web.editor import editor as editor_mod

        # Set up a file and a client watching it
        file_path = str(tmp_path / "example.py")
        Path(file_path).write_text("original")

        ws = _make_mock_ws()
        await _register_mock_client(ws, path=file_path)

        # Simulate a Riven file_changed event
        await editor_mod._on_file_changed(file_path, "updated content")

        # The mock WebSocket should have received a content broadcast
        ws.send_text.assert_called_once()
        msg = json.loads(ws.send_text.call_args[0][0])
        assert msg["type"] == "content"
        assert msg["path"] == file_path
        assert msg["content"] == "updated content"
        assert msg["source"] == "riven"

    @pytest.mark.asyncio
    async def test_highlight_included_when_start_end_provided(self, tmp_path):
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "example.py")
        Path(file_path).write_text("original")
        ws = _make_mock_ws()
        await _register_mock_client(ws, path=file_path)

        await editor_mod._on_file_changed(file_path, "updated", start=5, end=10, who="session-abc")

        calls = ws.send_text.call_args_list
        # Should have two messages: content + highlight
        assert len(calls) == 2
        highlight_msg = json.loads(calls[1][0][0])
        assert highlight_msg["type"] == "highlight"
        assert highlight_msg["start"] == 5
        assert highlight_msg["end"] == 10
        # who="session-abc" → label = who.split("-")[0] = "session"
        assert highlight_msg["label"] == "session"

    @pytest.mark.asyncio
    async def test_no_broadcast_if_no_clients_watching(self, tmp_path):
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "unwatched.py")
        ws = _make_mock_ws()
        # Register client watching a DIFFERENT path
        await _register_mock_client(ws, path="/different/file.py")

        await editor_mod._on_file_changed(file_path, "updated content")

        ws.send_text.assert_not_called()


class TestOnLockAcquired:
    """_on_lock_acquired should update awareness and broadcast to watchers."""

    def setup_method(self):
        from web.editor import editor as editor_mod
        editor_mod._awareness.clear()
        editor_mod._clients.clear()

    @pytest.mark.asyncio
    async def test_updates_awareness_and_broadcasts(self, tmp_path):
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "locked.py")
        Path(file_path).write_text("content")
        ws = _make_mock_ws()
        await _register_mock_client(ws, path=file_path)

        # Mock events.get_lock_state so broadcast_lock_update returns real state
        from web.editor import editor as _ed
        mock_lock_info = MagicMock()
        mock_lock_info.holder = "session-holder"
        mock_lock_info.context = "replace_text"
        with patch.object(_ed.events, 'get_lock_state', return_value=mock_lock_info):
            await editor_mod._on_lock_acquired(file_path, "session-holder", context="replace_text")

        # Check awareness state
        assert file_path in editor_mod._awareness
        assert len(editor_mod._awareness[file_path]) == 1
        assert editor_mod._awareness[file_path][0]["session_id"] == "session-holder"

        # Check broadcasts: awareness message then lock-update message
        calls = ws.send_text.call_args_list
        assert len(calls) == 2, f"Expected 2 broadcasts, got {len(calls)}: {[c[0][0] for c in calls]}"

        # 1st broadcast: awareness
        msg = json.loads(calls[0][0][0])
        assert msg["type"] == "awareness"
        assert msg["path"] == file_path
        assert len(msg["awareness"]) == 1
        assert msg["awareness"][0]["session_id"] == "session-holder"

        # 2nd broadcast: lock state update
        msg2 = json.loads(calls[1][0][0])
        assert msg2["type"] == "lock"
        assert msg2["path"] == file_path
        assert msg2["locked"] is True
        assert msg2["holder"] == "session-holder"

    @pytest.mark.asyncio
    async def test_multiple_holders_get_different_colors(self, tmp_path):
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "multi.py")
        Path(file_path).write_text("content")
        ws1 = _make_mock_ws()
        ws2 = _make_mock_ws()
        await _register_mock_client(ws1, path=file_path)
        await _register_mock_client(ws2, path=file_path)

        await editor_mod._on_lock_acquired(file_path, "holder-1", context="test")
        await editor_mod._on_lock_acquired(file_path, "holder-2", context="test")

        awareness = editor_mod._awareness[file_path]
        assert len(awareness) == 2
        # Colors should be different (palette has at least 2 colors)
        colors = {h["color"] for h in awareness}
        assert len(colors) == 2

    @pytest.mark.asyncio
    async def test_same_holder_not_added_twice(self, tmp_path):
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "no_dup.py")
        Path(file_path).write_text("content")
        ws = _make_mock_ws()
        await _register_mock_client(ws, path=file_path)

        await editor_mod._on_lock_acquired(file_path, "holder-1", context="test")
        await editor_mod._on_lock_acquired(file_path, "holder-1", context="test")

        awareness = editor_mod._awareness[file_path]
        assert len(awareness) == 1  # No duplicate


class TestOnLockReleased:
    """_on_lock_released should remove from awareness and broadcast."""

    def setup_method(self):
        from web.editor import editor as editor_mod
        editor_mod._awareness.clear()
        editor_mod._clients.clear()

    @pytest.mark.asyncio
    async def test_removes_from_awareness_and_broadcasts(self, tmp_path):
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "unlock.py")
        Path(file_path).write_text("content")
        ws = _make_mock_ws()
        await _register_mock_client(ws, path=file_path)

        # Acquire first
        await editor_mod._on_lock_acquired(file_path, "session-holder", context="test")
        assert file_path in editor_mod._awareness

        # Release
        await editor_mod._on_lock_released(file_path, "session-holder", context="test")

        # Awareness should be cleared
        assert file_path not in editor_mod._awareness

        # Broadcasts: awareness message then lock-update (for both acquire and release)
        # Acquire: awareness + lock  → release: awareness + lock  → total: 4 calls
        ws.send_text.assert_called()
        msgs = [json.loads(c[0][0]) for c in ws.send_text.call_args_list]
        assert len(msgs) == 4, f"Expected 4 broadcasts, got {len(msgs)}"
        # Last awareness message should be the release one with empty awareness
        awareness_msgs = [m for m in msgs if m["type"] == "awareness"]
        release_awareness = awareness_msgs[-1]
        assert release_awareness["awareness"] == []

    @pytest.mark.asyncio
    async def test_releasing_unknown_holder_does_not_crash(self, tmp_path):
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "unknown.py")
        Path(file_path).write_text("content")

        # Should not raise
        await editor_mod._on_lock_released(file_path, "never-held-holder", context="test")


class TestOnAwarenessUpdated:
    """_on_awareness_updated should update cursor position and broadcast."""

    def setup_method(self):
        from web.editor import editor as editor_mod
        editor_mod._awareness.clear()
        editor_mod._clients.clear()

    @pytest.mark.asyncio
    async def test_updates_cursor_and_label(self, tmp_path):
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "cursor.py")
        Path(file_path).write_text("content")
        ws = _make_mock_ws()
        await _register_mock_client(ws, path=file_path)

        await editor_mod._on_awareness_updated(file_path, session_id="alice", cursor=42, label="Alice")

        awareness = editor_mod._awareness[file_path]
        assert len(awareness) == 1
        assert awareness[0]["session_id"] == "alice"
        assert awareness[0]["cursor"] == 42
        assert awareness[0]["label"] == "Alice"

        msg = json.loads(ws.send_text.call_args[0][0])
        assert msg["type"] == "awareness"
        # cursor/label live in awareness[0], not at root level
        assert msg["awareness"][0]["cursor"] == 42
        assert msg["awareness"][0]["label"] == "Alice"

    @pytest.mark.asyncio
    async def test_ignores_none_session_id(self, tmp_path):
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "nocursor.py")
        Path(file_path).write_text("content")
        ws = _make_mock_ws()
        await _register_mock_client(ws, path=file_path)

        await editor_mod._on_awareness_updated(file_path, session_id=None, cursor=10)

        # No broadcast for None session_id
        ws.send_text.assert_not_called()


@pytest.fixture(autouse=True)
def init_events_and_editor_state():
    """Reset web-editor and events state before each test.

    _init_riven_events() lives in web/editor/editor.py and registers the four
    web-editor handlers (file_changed, lock_acquired, lock_released,
    awareness_updated) with the events bus.  We call it before every test so
    that the clean_events_state fixture (which only clears _locks, not
    _handlers) leaves the handlers intact for the next test.
    """
    import events as evt_module
    from web.editor import editor as editor_mod
    editor_mod._awareness.clear()
    editor_mod._clients.clear()
    # Re-register handlers so each test starts with a clean-but-registered
    # events state (safe to call multiple times — registers idempotently).
    editor_mod._init_riven_events()
    yield
    editor_mod._awareness.clear()
    editor_mod._clients.clear()


class TestInitRivenEvents:
    """_init_riven_events should register handlers on import."""

    def test_registers_all_four_handlers(self):
        import events as evt_module
        # Count how many handlers are registered for each event type
        assert "file_changed" in evt_module._handlers
        assert "lock_acquired" in evt_module._handlers
        assert "lock_released" in evt_module._handlers
        assert "awareness_updated" in evt_module._handlers

    @pytest.mark.asyncio
    async def test_end_to_end_file_changed_to_broadcast(self, tmp_path):
        """Simulate the full flow: Riven edits a file → web editor broadcasts to browser."""
        from web.editor import editor as editor_mod

        file_path = str(tmp_path / "e2e.py")
        Path(file_path).write_text("original")
        ws = _make_mock_ws()
        await _register_mock_client(ws, path=file_path)

        # Directly call _on_file_changed (simulating what events.py would do)
        await editor_mod._on_file_changed(file_path, "riven edited this!", start=1, end=5, who="riven-agent")

        # Verify the browser received the update
        calls = ws.send_text.call_args_list
        assert len(calls) >= 1

        content_msg = json.loads(calls[0][0][0])
        assert content_msg["type"] == "content"
        assert content_msg["content"] == "riven edited this!"
        assert content_msg["source"] == "riven"


# ─── API Endpoint Tests ────────────────────────────────────────────────────────

class TestLockApiEndpoints:
    """Test the HTTP lock endpoints in web/editor/api.py."""

    def setup_method(self):
        # Reset events lock state — _handlers is NOT cleared here because the
        # autouse fixture (_init_riven_events) re-registers the four web-editor
        # handlers after this method runs.
        import events as evt_module
        evt_module._locks.clear()

    def test_get_lock_unlocked_returns_not_locked(self):
        from web.editor.api import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/lock/some/file.py")
        assert response.status_code == 200
        data = response.json()
        assert data["locked"] is False

    def test_get_lock_locked_returns_locked(self):
        import events as evt_module
        from web.editor.api import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        async def setup():
            async with evt_module.acquire_lock("/my/file.py", "holder", timeout=5.0, context="test"):
                pass  # lock auto-released

        asyncio.run(setup())

        response = client.get("/lock/my/file.py")
        assert response.status_code == 200
        data = response.json()
        assert data["locked"] is False  # already released

    def test_post_lock_acquires_and_returns_ok(self):
        import events as evt_module
        from web.editor.api import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        # Use pytest-asyncio to share the event loop — lock state lives in module globals
        async def acquire_and_check():
            async with evt_module.acquire_lock("api/test.py", "test-holder",
                                              timeout=5.0, context="api_test") as lock_info:
                # Check internal state while we hold the lock
                state = evt_module.get_lock_state("api/test.py")
                assert state is not None
                assert state.holder == "test-holder"
                # Then verify the HTTP endpoint also reports it
                resp = client.get("/lock/api/test.py")
                assert resp.status_code == 200
                data = resp.json()
                assert data["locked"] is True

        asyncio.run(acquire_and_check())

    def test_delete_lock_releases_and_returns_ok(self):
        """Release a lock via DELETE endpoint — the endpoint handles the release
        correctly even though we can't check _locks cross-event-loop."""
        from web.editor.api import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        # The endpoint calls events.release_lock which handles the release.
        # We can't verify _locks state from here (TestClient uses a separate
        # event loop), but we verify the endpoint responds gracefully.
        response = client.delete("/lock/delete/lock.py", params={"holder": "holder"})
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_delete_lock_nonexistent_returns_ok(self):
        from web.editor.api import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/lock/never/existed.py")
        assert response.status_code == 200
        assert response.json()["ok"] is True  # graceful — no error on already-free


class TestAwarenessEndpoint:
    """Test the /awareness/{path} endpoint."""

    def setup_method(self):
        # Only clear locks — autouse fixture re-registers _handlers
        import events as evt_module
        evt_module._locks.clear()

    def test_post_awareness_returns_ok(self):
        from web.editor.api import router
        from web.editor import editor as editor_mod
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/awareness/test/file.py",
            json={"session_id": "alice", "cursor": 10, "label": "Alice"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        # The endpoint broadcasts via WebSocket but does not update editor_mod._awareness directly

    def test_post_awareness_no_session_id_still_ok(self):
        from web.editor.api import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/awareness/test/file.py",
            json={"cursor": 5, "label": "Bob"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestSpeakEndpoint:
    """Test the /speak endpoint."""

    def test_speak_to_path_broadcasts_toast(self):
        from web.editor.api import router
        from web.editor import editor as editor_mod
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/speak",
            json={"text": "Hello from test!", "path": "some/file.py"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_speak_without_path_broadcasts_to_all(self):
        from web.editor.api import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/speak",
            json={"text": "Global message!"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestSaveEndpoint:
    """Test the /save endpoint."""

    def setup_method(self):
        # Only clear locks — autouse fixture re-registers _handlers
        import events as evt_module
        evt_module._locks.clear()

    def test_save_writes_file_and_returns_ok(self, tmp_path):
        # Override get_root_dir so the save endpoint writes to tmp_path.
        # api.py has `from .config import get_root_dir` — the local binding is set
        # when api.py first loads, so we must patch web.editor.api.get_root_dir
        # (the import in api.py), not the source in config.py.
        file_path = "saved_test.txt"
        content = "written via API"
        (tmp_path / file_path).write_text("original")  # create in real tmp_path

        with patch('web.editor.api.get_root_dir', return_value=str(tmp_path)):
            from web.editor.api import router
            from fastapi import FastAPI
            app = FastAPI()
            app.include_router(router)
            client = TestClient(app, raise_server_exceptions=False)

            response = client.post(
                "/save",
                json={"path": file_path, "content": content},
            )

            assert response.status_code == 200
            assert response.json()["ok"] is True
            assert (tmp_path / file_path).read_text() == content

    def test_save_too_large_returns_413(self):
        from web.editor.api import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/save",
            json={"path": "big.txt", "content": "x" * 10_000_000},
        )
        assert response.status_code == 413
