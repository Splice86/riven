"""Tests for the process management API routes in api.py."""

import asyncio
import json
import time
from unittest.mock import patch, MagicMock

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from process_manager import Process, ProcessStatus, ProcessManager, ProcessEvent


# Patch process_manager module-level import in api.py
@pytest.fixture(autouse=True)
def mock_process_manager():
    """Replace process_manager singleton with a fresh ProcessManager for each test."""
    from process_manager import ProcessManager
    pm = ProcessManager()
    with patch("api.process_manager", pm):
        yield pm


@pytest.fixture
def client(mock_process_manager):
    """FastAPI test client with mocked process_manager."""
    import api
    return TestClient(api.app)


@pytest.fixture
def api_module(mock_process_manager):
    """Direct import of api module with mocked process_manager."""
    import api
    return api


# =============================================================================
# Health check
# =============================================================================

class TestHealthCheck:
    def test_root_returns_ok(self, client):
        """GET / should return status ok."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# =============================================================================
# list_processes
# =============================================================================

class TestListProcesses:
    def test_list_processes_empty(self, client, mock_process_manager):
        """GET /processes with no processes should return empty list."""
        resp = client.get("/processes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["processes"] == []
        assert data["count"] == 0

    def test_list_processes_returns_all(self, client, mock_process_manager):
        """GET /processes should return all registered processes."""
        # Add a process
        proc = Process(
            process_id="proc-001",
            shard_name="codehammer",
            shard={"name": "codehammer", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        mock_process_manager._processes["proc-001"] = proc

        resp = client.get("/processes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["processes"][0]["process_id"] == "proc-001"
        assert data["processes"][0]["shard_name"] == "codehammer"
        assert data["processes"][0]["status"] == "idle"

    def test_list_processes_filter_by_shard(self, client, mock_process_manager):
        """GET /processes?shard_name=X should filter by shard."""
        proc1 = Process(
            process_id="proc-001",
            shard_name="codehammer",
            shard={"name": "codehammer", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc2 = Process(
            process_id="proc-002",
            shard_name="planner",
            shard={"name": "planner", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        mock_process_manager._processes["proc-001"] = proc1
        mock_process_manager._processes["proc-002"] = proc2

        resp = client.get("/processes?shard_name=codehammer")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["processes"][0]["shard_name"] == "codehammer"

    def test_list_processes_filter_by_status(self, client, mock_process_manager):
        """GET /processes?status=running should filter by status."""
        proc1 = Process(
            process_id="proc-001",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc1.status = ProcessStatus.RUNNING
        mock_process_manager._processes["proc-001"] = proc1

        resp = client.get("/processes?status=running")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["processes"][0]["status"] == "running"


# =============================================================================
# spawn_process
# =============================================================================

class TestSpawnProcess:
    @patch("api.get_llm_config")
    @patch("api.get")
    @patch("api.glob.glob")
    @patch("builtins.open", MagicMock())
    @patch("yaml.safe_load")
    def test_spawn_process_success(self, mock_yaml, mock_glob, mock_get, mock_llm, client, mock_process_manager):
        """POST /processes with valid body should create a process."""
        mock_glob.return_value = []
        mock_get.return_value = "http://localhost:8030"
        mock_llm.return_value = {"model": "test", "url": "http://test"}

        resp = client.post("/processes", json={"shard_name": "codehammer"})
        assert resp.status_code == 200
        data = resp.json()
        assert "process_id" in data
        assert data["shard_name"] == "codehammer"
        assert data["status"] == "idle"
        assert "created_at" in data

    @patch("api.get_llm_config")
    @patch("api.get")
    @patch("api.glob.glob")
    @patch("builtins.open", MagicMock())
    @patch("yaml.safe_load")
    def test_spawn_process_with_message(self, mock_yaml, mock_glob, mock_get, mock_llm, client, mock_process_manager):
        """POST /processes with message should kick off async processing."""
        mock_glob.return_value = []
        mock_get.return_value = "http://localhost:8030"
        mock_llm.return_value = {"model": "test", "url": "http://test"}

        with patch("api.process_manager.spawn") as mock_spawn:
            mock_proc = MagicMock()
            mock_proc.process_id = "test-proc"
            mock_proc.shard_name = "codehammer"
            mock_proc.status = ProcessStatus.IDLE
            mock_proc.created_at.isoformat.return_value = "2025-01-01T00:00:00"
            mock_spawn.return_value = mock_proc

            resp = client.post("/processes", json={
                "shard_name": "codehammer",
                "message": "Fix the bug",
            })
            assert resp.status_code == 200

    def test_spawn_process_missing_shard_name(self, client, mock_process_manager):
        """POST /processes without shard_name should return 400."""
        resp = client.post("/processes", json={})
        assert resp.status_code == 400

    @patch("api.get_llm_config")
    @patch("api.get")
    @patch("api.glob.glob")
    @patch("builtins.open", MagicMock())
    @patch("yaml.safe_load")
    def test_spawn_process_with_custom_id(self, mock_yaml, mock_glob, mock_get, mock_llm, client, mock_process_manager):
        """POST /processes with custom process_id should use it."""
        mock_glob.return_value = []
        mock_get.return_value = "http://localhost:8030"
        mock_llm.return_value = {"model": "test", "url": "http://test"}

        resp = client.post("/processes", json={
            "shard_name": "default",
            "process_id": "my-custom-session-id",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["process_id"] == "my-custom-session-id"


# =============================================================================
# get_process
# =============================================================================

class TestGetProcess:
    def test_get_process_success(self, client, mock_process_manager):
        """GET /processes/{id} with valid ID should return process info."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="codehammer",
            shard={"name": "codehammer", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.status = ProcessStatus.RUNNING
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.get("/processes/test-proc-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["process_id"] == "test-proc-123"
        assert data["shard_name"] == "codehammer"
        assert data["status"] == "running"
        assert data["is_running"] is True
        assert data["is_done"] is False

    def test_get_process_not_found(self, client, mock_process_manager):
        """GET /processes/{id} with unknown ID should return 404."""
        resp = client.get("/processes/does-not-exist")
        assert resp.status_code == 404


# =============================================================================
# get_process_output
# =============================================================================

class TestGetProcessOutput:
    def test_get_output_success(self, client, mock_process_manager):
        """GET /processes/{id}/output should return events."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.add_event(ProcessEvent(type="token", content="hello"))
        proc.add_event(ProcessEvent(type="token", content=" world"))
        proc.add_event(ProcessEvent(type="thinking", content="thinking..."))
        proc.add_event(ProcessEvent(type="tool_call", name="run", args={"command": "ls"}))
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.get("/processes/test-proc-123/output")
        assert resp.status_code == 200
        data = resp.json()
        assert data["process_id"] == "test-proc-123"
        assert data["status"] == "idle"
        # Default: messages=True, others False
        output = data["output"]
        types = [e["type"] for e in output]
        assert "token" in types
        assert "thinking" not in types
        assert "tool_call" not in types

    def test_get_output_with_thinking(self, client, mock_process_manager):
        """GET /processes/{id}/output?thinking=true should include thinking."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.add_event(ProcessEvent(type="thinking", content="reasoning..."))
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.get("/processes/test-proc-123/output?thinking=true")
        assert resp.status_code == 200
        types = [e["type"] for e in resp.json()["output"]]
        assert "thinking" in types

    def test_get_output_with_tool_calls(self, client, mock_process_manager):
        """GET /processes/{id}/output?tool_calls=true should include tool calls."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.add_event(ProcessEvent(type="tool_call", name="run", args={"command": "ls"}))
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.get("/processes/test-proc-123/output?tool_calls=true")
        assert resp.status_code == 200
        types = [e["type"] for e in resp.json()["output"]]
        assert "tool_call" in types

    def test_get_output_with_errors(self, client, mock_process_manager):
        """GET /processes/{id}/output?errors=true should include errors."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.add_event(ProcessEvent(type="error", error="something broke"))
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.get("/processes/test-proc-123/output?errors=true")
        assert resp.status_code == 200
        types = [e["type"] for e in resp.json()["output"]]
        assert "error" in types

    def test_get_output_with_last_only(self, client, mock_process_manager):
        """GET /processes/{id}/output?last_only=true should filter to new events.
        
        Events added BEFORE _last_poll is set are 'old' and should be filtered out.
        Events added AFTER _last_poll are 'new' and should be returned.
        """
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        # Old events (before poll) — these get filtered out
        proc.add_event(ProcessEvent(type="token", content="OLD"))
        proc.add_event(ProcessEvent(type="token", content=" old2"))
        # Set _last_poll to mark the checkpoint
        proc._last_poll = time.time()
        # New events (after poll) — these get returned
        proc.add_event(ProcessEvent(type="token", content=" NEW"))
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.get("/processes/test-proc-123/output?last_only=true")
        assert resp.status_code == 200
        output = resp.json()["output"]
        # Should only include " NEW" (after _last_poll), not "OLD" or " old2"
        assert len(output) == 1
        assert output[0]["content"] == " NEW"

    def test_get_output_with_since(self, client, mock_process_manager):
        """GET /processes/{id}/output?since=TIMESTAMP should filter by timestamp."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.add_event(ProcessEvent(type="token", content="event1"))
        proc.add_event(ProcessEvent(type="token", content="event2"))
        mock_process_manager._processes["test-proc-123"] = proc

        old_ts = time.time() - 3600
        resp = client.get(f"/processes/test-proc-123/output?since={old_ts}")
        assert resp.status_code == 200
        # Should get both (both are newer than old_ts)
        assert len(resp.json()["output"]) == 2

    def test_get_output_not_found(self, client, mock_process_manager):
        """GET /processes/{id}/output with unknown ID should return 404."""
        resp = client.get("/processes/no-such-id/output")
        assert resp.status_code == 404


# =============================================================================
# stream_process_output
# =============================================================================

class TestStreamProcessOutput:
    def test_stream_process_output_returns_sse(self, client, mock_process_manager):
        """GET /processes/{id}/output/stream should return SSE stream."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.status = ProcessStatus.DONE  # Mark done so stream exits immediately
        mock_process_manager._processes["test-proc-123"] = proc

        # Use stream=True to get an iterator response
        with client.stream("GET", "/processes/test-proc-123/output/stream", timeout=1) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"

    def test_stream_process_output_not_found(self, client, mock_process_manager):
        """GET /processes/{id}/output/stream with unknown ID should return 404."""
        resp = client.get("/processes/no-such-id/output/stream")
        assert resp.status_code == 404

    def test_stream_process_output_filters_work(self, client, mock_process_manager):
        """SSE stream should respect filter query params."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.status = ProcessStatus.DONE  # Mark done so stream exits immediately
        mock_process_manager._processes["test-proc-123"] = proc

        with client.stream(
            "GET",
            "/processes/test-proc-123/output/stream?messages=true&thinking=true&tool_calls=true",
            timeout=1,
        ) as resp:
            assert resp.status_code == 200


# =============================================================================
# send_process_message
# =============================================================================

class TestSendProcessMessage:
    def test_send_process_message_success(self, client, mock_process_manager):
        """POST /processes/{id}/input should queue message for idle process."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        # Start in IDLE so message can be sent
        proc.status = ProcessStatus.IDLE
        mock_process_manager._processes["test-proc-123"] = proc

        with patch.object(mock_process_manager, "send_message", return_value=True) as mock_send:
            resp = client.post(
                "/processes/test-proc-123/input",
                json={"message": "Continue with the fix"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
            mock_send.assert_called_once_with("test-proc-123", "Continue with the fix")

    def test_send_process_message_not_idle(self, client, mock_process_manager):
        """POST /processes/{id}/input should return 409 if process not idle."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.status = ProcessStatus.RUNNING
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.post(
            "/processes/test-proc-123/input",
            json={"message": "hello"},
        )
        assert resp.status_code == 409

    def test_send_process_message_not_found(self, client, mock_process_manager):
        """POST /processes/{id}/input with unknown ID should return 404."""
        resp = client.post("/processes/no-such-id/input", json={"message": "hi"})
        assert resp.status_code == 404

    def test_send_process_message_missing_message(self, client, mock_process_manager):
        """POST /processes/{id}/input without message should return 400."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.status = ProcessStatus.IDLE
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.post("/processes/test-proc-123/input", json={})
        assert resp.status_code == 400


# =============================================================================
# stop_process
# =============================================================================

class TestStopProcess:
    def test_stop_process_success(self, client, mock_process_manager):
        """DELETE /processes/{id} should stop the process."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.status = ProcessStatus.RUNNING
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.delete("/processes/test-proc-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["stopped_status"] == "stopped"  # ProcessStatus.STOPPED.value

    def test_stop_process_not_found(self, client, mock_process_manager):
        """DELETE /processes/{id} with unknown ID should return 404."""
        resp = client.delete("/processes/no-such-id")
        assert resp.status_code == 404


# =============================================================================
# cleanup_process
# =============================================================================

class TestCleanupProcess:
    def test_cleanup_process_success(self, client, mock_process_manager):
        """DELETE /processes/{id}/cleanup should remove done process."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.status = ProcessStatus.DONE
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.delete("/processes/test-proc-123/cleanup")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert "test-proc-123" not in mock_process_manager._processes

    def test_cleanup_process_not_done(self, client, mock_process_manager):
        """DELETE /processes/{id}/cleanup should return 409 if process not done."""
        proc = Process(
            process_id="test-proc-123",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc.status = ProcessStatus.RUNNING
        mock_process_manager._processes["test-proc-123"] = proc

        resp = client.delete("/processes/test-proc-123/cleanup")
        assert resp.status_code == 409

    def test_cleanup_process_not_found(self, client, mock_process_manager):
        """DELETE /processes/{id}/cleanup with unknown ID should return 404."""
        resp = client.delete("/processes/no-such-id/cleanup")
        assert resp.status_code == 404
