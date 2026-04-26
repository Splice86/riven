"""Tests for process_manager.py - Process class and ProcessManager."""

import time
import uuid
from unittest.mock import patch, MagicMock

import pytest

from process_manager import (
    Process,
    ProcessEvent,
    ProcessManager,
    ProcessStatus,
    process_manager,
)


# =============================================================================
# Process Tests
# =============================================================================

class TestProcessBasics:
    """Basic Process object properties and behavior."""

    def test_process_default_status_is_idle(self):
        """New processes should start in IDLE state."""
        proc = Process(
            process_id="test-001",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        assert proc.status == ProcessStatus.IDLE
        assert not proc.is_done
        assert not proc.is_running

    def test_process_properties_reflect_status(self):
        """is_done and is_running should track status correctly."""
        proc = Process(
            process_id="test-001",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        # IDLE: not done, not running
        assert proc.is_done is False
        assert proc.is_running is False

        proc.status = ProcessStatus.RUNNING
        assert proc.is_done is False
        assert proc.is_running is True

        proc.status = ProcessStatus.DONE
        assert proc.is_done is True
        assert proc.is_running is False

        proc.status = ProcessStatus.STOPPED
        assert proc.is_done is True
        assert proc.is_running is False

    def test_process_elapsed_seconds_while_running(self):
        """elapsed_seconds should return None before start."""
        proc = Process(
            process_id="test-001",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        assert proc.elapsed_seconds is None

    def test_process_id_can_be_custom(self):
        """process_id should accept custom values (e.g., session IDs)."""
        custom_id = f"session-{uuid.uuid4().hex[:12]}"
        proc = Process(
            process_id=custom_id,
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        assert proc.process_id == custom_id


class TestProcessEvent:
    """ProcessEvent creation and serialization."""

    def test_event_to_dict_token(self):
        """Token events should serialize with type and content."""
        event = ProcessEvent(type="token", content="hello")
        d = event.to_dict()
        assert d["type"] == "token"
        assert d["content"] == "hello"
        assert "timestamp" in d

    def test_event_to_dict_tool_call(self):
        """Tool call events should include name and args."""
        event = ProcessEvent(
            type="tool_call",
            name="run",
            args={"command": "ls"},
        )
        d = event.to_dict()
        assert d["type"] == "tool_call"
        assert d["name"] == "run"
        assert d["args"] == {"command": "ls"}

    def test_event_to_dict_tool_result(self):
        """Tool result events should include result dict."""
        event = ProcessEvent(
            type="tool_result",
            name="run",
            result={"content": "file.txt"},
        )
        d = event.to_dict()
        assert d["type"] == "tool_result"
        assert d["name"] == "run"
        assert d["result"] == {"content": "file.txt"}

    def test_event_to_dict_error(self):
        """Error events should include error field."""
        event = ProcessEvent(type="error", error="something broke")
        d = event.to_dict()
        assert d["type"] == "error"
        assert d["error"] == "something broke"

    def test_event_timestamp_is_set_automatically(self):
        """Event timestamp should default to current time."""
        before = time.time()
        event = ProcessEvent(type="token", content="x")
        after = time.time()
        assert before <= event.timestamp <= after


class TestProcessGetOutput:
    """Test Process.get_output() with all filter combinations."""

    @pytest.fixture
    def proc_with_events(self):
        """Process with a mix of event types."""
        proc = Process(
            process_id="test-001",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        # Add a token
        proc.add_event(ProcessEvent(type="token", content="hello "))
        proc.add_event(ProcessEvent(type="token", content="world"))
        # Add thinking
        proc.add_event(ProcessEvent(type="thinking", content="let me think..."))
        # Add tool call
        proc.add_event(ProcessEvent(
            type="tool_call", name="run", args={"command": "ls"}
        ))
        # Add tool result
        proc.add_event(ProcessEvent(
            type="tool_result", name="run",
            result={"content": "file.txt"},
        ))
        # Add error
        proc.add_event(ProcessEvent(type="error", error="oops"))
        # Add done
        proc.add_event(ProcessEvent(type="done"))
        return proc

    def test_get_output_default_includes_only_tokens(self, proc_with_events):
        """Default get_output (no filters) should return only tokens."""
        events = proc_with_events.get_output()
        types = [e["type"] for e in events]
        assert types == ["token", "token"]

    def test_get_output_tokens_filter(self, proc_with_events):
        """messages=False should exclude tokens."""
        events = proc_with_events.get_output(messages=False)
        types = [e["type"] for e in events]
        assert "token" not in types

    def test_get_output_thinking_filter(self, proc_with_events):
        """thinking=True should include thinking events."""
        events = proc_with_events.get_output(thinking=True)
        types = [e["type"] for e in events]
        assert "thinking" in types
        # Should still include tokens (default)
        assert "token" in types

    def test_get_output_tool_calls_filter(self, proc_with_events):
        """tool_calls=True should include function call events."""
        events = proc_with_events.get_output(tool_calls=True)
        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "token" in types  # default

    def test_get_output_tool_results_filter(self, proc_with_events):
        """tool_results=True should include function result events."""
        events = proc_with_events.get_output(tool_results=True)
        types = [e["type"] for e in events]
        assert "tool_result" in types

    def test_get_output_errors_filter(self, proc_with_events):
        """errors=True should include error events."""
        events = proc_with_events.get_output(errors=True)
        types = [e["type"] for e in events]
        assert "error" in types
        # errors=True should also include 'done' events
        assert "done" in types

    def test_get_output_errors_false_excludes_errors(self, proc_with_events):
        """errors=False (default) should exclude error events."""
        events = proc_with_events.get_output()
        types = [e["type"] for e in events]
        assert "error" not in types
        assert "done" not in types

    def test_get_output_since_filter(self, proc_with_events):
        """since= timestamp should filter to only newer events."""
        # Filter with an old timestamp - should get all tokens
        old_ts = time.time() - 3600
        events = proc_with_events.get_output(messages=True, since=old_ts)
        assert len(events) == 2

    def test_get_output_last_only_returns_only_new_events(self, proc_with_events):
        """last_only=True should return only events added after _last_poll was set."""
        # Record time BEFORE adding new events
        time.sleep(0.02)
        poll_time = time.time()
        time.sleep(0.02)

        # Add a new token AFTER the poll time
        proc_with_events.add_event(ProcessEvent(
            type="token", content="NEW TOKEN AFTER POLL"
        ))

        # Manually set _last_poll to our recorded time
        proc_with_events._last_poll = poll_time

        # last_only=True should return only events added AFTER last poll
        events = proc_with_events.get_output(messages=True, last_only=True)

        # Should contain only the new token, not the old ones
        assert len(events) == 1
        assert events[0]["content"] == "NEW TOKEN AFTER POLL"

    def test_get_output_last_only_with_thinking(self, proc_with_events):
        """last_only combined with thinking filter should work."""
        time.sleep(0.02)
        poll_time = time.time()
        time.sleep(0.02)
        proc_with_events.add_event(ProcessEvent(
            type="thinking", content="NEW THINKING"
        ))
        proc_with_events._last_poll = poll_time

        events = proc_with_events.get_output(
            messages=True, thinking=True, last_only=True
        )
        contents = [e.get("content", "") for e in events]
        assert "NEW THINKING" in contents
        # Old tokens should NOT be included
        assert "hello " not in contents

    def test_get_output_multiple_filters_combined(self, proc_with_events):
        """All filters should be combinable."""
        events = proc_with_events.get_output(
            messages=True,
            thinking=True,
            tool_calls=True,
            tool_results=True,
            errors=True,
        )
        types = [e["type"] for e in events]
        assert "token" in types
        assert "thinking" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "error" in types
        assert "done" in types

    def test_add_event_appends_to_list(self, proc_with_events):
        """add_event should append to _events list."""
        initial_count = len(proc_with_events._events)
        proc_with_events.add_event(ProcessEvent(type="token", content="extra"))
        assert len(proc_with_events._events) == initial_count + 1

    def test_clear_output_removes_all_events(self, proc_with_events):
        """clear_output should remove all events."""
        assert len(proc_with_events._events) > 0
        proc_with_events.clear_output()
        assert len(proc_with_events._events) == 0


class TestProcessManagerBasics:
    """ProcessManager singleton behavior."""

    def test_singleton_instance_exists(self):
        """process_manager should be a ProcessManager instance."""
        from process_manager import process_manager as pm
        assert isinstance(pm, ProcessManager)

    def test_get_nonexistent_returns_none(self):
        """get() with unknown ID should return None."""
        assert process_manager.get("does-not-exist") is None

    def test_list_empty_returns_empty_list(self):
        """list() with no processes should return empty list."""
        with patch.object(process_manager, "_processes", {}):
            assert process_manager.list() == []

    def test_list_with_status_filter(self):
        """list(status=X) should filter by status."""
        with patch.object(process_manager, "_processes", {}):
            assert process_manager.list(status=ProcessStatus.RUNNING) == []

    def test_remove_nonexistent_returns_false(self):
        """remove() with unknown ID should return False."""
        with patch.object(process_manager, "_processes", {}):
            assert process_manager.remove("no-such-id") is False


class TestProcessManagerSpawn:
    """Test ProcessManager.spawn() behavior."""

    @pytest.fixture
    def pm(self):
        """Fresh ProcessManager for spawn tests."""
        return ProcessManager()

    @patch.object(ProcessManager, "_load_shard")
    @patch("process_manager.get_llm_config")
    @patch("process_manager.get")
    def test_spawn_generates_process_id(self, mock_get, mock_llm, mock_load, pm):
        """spawn() should auto-generate a proc-N hex ID."""
        mock_load.return_value = {"name": "default"}
        mock_llm.return_value = {"model": "test"}
        mock_get.return_value = "http://x"

        proc = pm.spawn("default")

        assert proc.process_id.startswith("proc-")
        assert len(proc.process_id) == len("proc-") + 12

    @patch.object(ProcessManager, "_load_shard")
    @patch("process_manager.get_llm_config")
    @patch("process_manager.get")
    def test_spawn_uses_provided_process_id(self, mock_get, mock_llm, mock_load, pm):
        """spawn() should use provided process_id."""
        mock_load.return_value = {"name": "default"}
        mock_llm.return_value = {"model": "test"}
        mock_get.return_value = "http://x"

        proc = pm.spawn("default", process_id="my-session-123")

        assert proc.process_id == "my-session-123"

    @patch.object(ProcessManager, "_load_shard")
    @patch("process_manager.get_llm_config")
    @patch("process_manager.get")
    def test_spawn_stores_in_registry(self, mock_get, mock_llm, mock_load, pm):
        """spawn() should register the process so it can be retrieved."""
        mock_load.return_value = {"name": "default"}
        mock_llm.return_value = {"model": "test"}
        mock_get.return_value = "http://x"

        proc = pm.spawn("default")

        assert pm.get(proc.process_id) is proc

    @patch.object(ProcessManager, "_load_shard")
    @patch("process_manager.get_llm_config")
    @patch("process_manager.get")
    def test_spawn_sets_shard_name(self, mock_get, mock_llm, mock_load, pm):
        """spawn() should store shard_name on process."""
        mock_load.return_value = {"name": "codehammer"}
        mock_llm.return_value = {"model": "test"}
        mock_get.return_value = "http://x"

        proc = pm.spawn("codehammer")

        assert proc.shard_name == "codehammer"

    @patch.object(ProcessManager, "_load_shard")
    @patch("process_manager.get_llm_config")
    @patch("process_manager.get")
    def test_spawn_without_message_leaves_idle(self, mock_get, mock_llm, mock_load, pm):
        """spawn() without message should leave status as IDLE."""
        mock_load.return_value = {"name": "default"}
        mock_llm.return_value = {"model": "test"}
        mock_get.return_value = "http://x"

        proc = pm.spawn("default")

        assert proc.status == ProcessStatus.IDLE

    @patch("process_manager.asyncio.create_task")
    @patch.object(ProcessManager, "_load_shard")
    @patch("process_manager.get_llm_config")
    @patch("process_manager.get")
    def test_spawn_with_message_kicks_off_async(
        self, mock_get, mock_llm, mock_load, mock_task, pm
    ):
        """spawn(message=...) should call asyncio.create_task."""
        mock_load.return_value = {"name": "default"}
        mock_llm.return_value = {"model": "test"}
        mock_get.return_value = "http://x"

        proc = pm.spawn("default", message="Fix the bug")

        mock_task.assert_called_once()

    @patch("process_manager.asyncio.create_task")
    @patch.object(ProcessManager, "_load_shard")
    @patch("process_manager.get_llm_config")
    @patch("process_manager.get")
    def test_spawn_max_processes_enforced(self, mock_get, mock_llm, mock_load, mock_task, pm):
        """spawn() should raise RuntimeError when max processes reached."""
        mock_load.return_value = {"name": "default"}
        mock_llm.return_value = {"model": "test"}
        mock_get.return_value = "http://x"
        pm._max_processes = 2

        pm.spawn("default")
        pm.spawn("default")

        with pytest.raises(RuntimeError, match="Max processes"):
            pm.spawn("default")


class TestProcessManagerOperations:
    """Test send_message, stop, list, remove, cleanup_done."""

    @pytest.fixture
    def pm_with_proc(self):
        """ProcessManager with one stored process."""
        pm = ProcessManager()
        proc = Process(
            process_id="test-proc-001",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        pm._processes["test-proc-001"] = proc
        return pm

    def test_get_returns_stored_process(self, pm_with_proc):
        """get() should return stored process by ID."""
        proc = pm_with_proc.get("test-proc-001")
        assert proc is not None
        assert proc.process_id == "test-proc-001"

    def test_list_returns_all_processes(self, pm_with_proc):
        """list() should return all stored processes."""
        procs = pm_with_proc.list()
        assert len(procs) == 1
        assert procs[0].process_id == "test-proc-001"

    def test_list_filters_by_shard(self, pm_with_proc):
        """list(shard_name=X) should filter by shard."""
        procs = pm_with_proc.list(shard_name="codehammer")
        assert len(procs) == 0
        procs = pm_with_proc.list(shard_name="default")
        assert len(procs) == 1

    def test_list_filters_by_status(self, pm_with_proc):
        """list(status=X) should filter by status."""
        procs = pm_with_proc.list(status=ProcessStatus.IDLE)
        assert len(procs) == 1
        procs = pm_with_proc.list(status=ProcessStatus.DONE)
        assert len(procs) == 0

    def test_remove_deletes_from_registry(self, pm_with_proc):
        """remove() should delete the process from _processes."""
        assert pm_with_proc.get("test-proc-001") is not None
        result = pm_with_proc.remove("test-proc-001")
        assert result is True
        assert pm_with_proc.get("test-proc-001") is None

    @patch("process_manager.asyncio.create_task")
    def test_send_message_idle_process_succeeds(self, mock_task, pm_with_proc):
        """send_message() should succeed for IDLE process."""
        result = pm_with_proc.send_message("test-proc-001", "hello")
        assert result is True
        mock_task.assert_called_once()

    def test_send_message_running_process_fails(self, pm_with_proc):
        """send_message() should fail for RUNNING process."""
        pm_with_proc._processes["test-proc-001"].status = ProcessStatus.RUNNING
        result = pm_with_proc.send_message("test-proc-001", "hello")
        assert result is False

    def test_send_message_nonexistent_process_fails(self, pm_with_proc):
        """send_message() should fail for unknown process ID."""
        result = pm_with_proc.send_message("no-such-process", "hello")
        assert result is False

    def test_stop_sets_cancellation_and_status(self, pm_with_proc):
        """stop() should set cancellation event and status to STOPPED."""
        result = pm_with_proc.stop("test-proc-001")
        assert result is True
        proc = pm_with_proc.get("test-proc-001")
        assert proc.status == ProcessStatus.STOPPED
        assert proc.completed_at is not None

    def test_stop_nonexistent_returns_false(self, pm_with_proc):
        """stop() should return False for unknown process."""
        result = pm_with_proc.stop("no-such-process")
        assert result is False

    def test_cleanup_done_removes_finished_processes(self, pm_with_proc):
        """cleanup_done() should remove DONE and STOPPED processes."""
        pm_with_proc._processes["test-proc-001"].status = ProcessStatus.DONE

        # Add a running process (should NOT be removed)
        proc2 = Process(
            process_id="test-proc-002",
            shard_name="default",
            shard={"name": "default", "modules": ["time"]},
            llm_config={"model": "test"},
        )
        proc2.status = ProcessStatus.RUNNING
        pm_with_proc._processes["test-proc-002"] = proc2

        removed = pm_with_proc.cleanup_done()
        assert removed == 1
        assert "test-proc-001" not in pm_with_proc._processes
        assert "test-proc-002" in pm_with_proc._processes


class TestProcessStatusEnum:
    """Test ProcessStatus enum values."""

    def test_process_status_values(self):
        """ProcessStatus should have all expected states."""
        assert ProcessStatus.IDLE.value == "idle"
        assert ProcessStatus.RUNNING.value == "running"
        assert ProcessStatus.DONE.value == "done"
        assert ProcessStatus.STOPPED.value == "stopped"

    def test_process_status_is_string_enum(self):
        """ProcessStatus values should be strings for JSON serialization."""
        assert isinstance(ProcessStatus.IDLE, str)
        assert ProcessStatus.IDLE == "idle"
