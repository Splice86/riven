"""Tests for the workflow module."""

import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_workflow_state():
    """Reset workflow storage between tests to ensure isolation."""
    from modules import _session_id
    _session_id.set("test-session-workflow")
    yield
    _session_id.set("")


@pytest.fixture
def mock_db():
    """Mock workflow DB so we don't need a real DB connection.
    
    Patches the module where storage.py actually uses it (modules.workflow.storage.db).
    """
    storage = {}
    mock_db_module = MagicMock()
    mock_db_module.upsert = lambda **kw: storage.update(kw)
    mock_db_module.load = lambda session_id: storage.get("session_id") == session_id and dict(storage) or None
    mock_db_module.delete = lambda session_id: storage.pop("session_id", None)

    with patch("modules.workflow.storage.db", mock_db_module):
        yield mock_db_module, storage


# ─── Command function tests ────────────────────────────────────────────────────

class TestStartWorkflow:
    """Tests for start_workflow_cmd()."""

    def test_starts_empty_workflow(self, mock_db):
        from modules.workflow import start_workflow_cmd

        with mock_db[0]:
            result = start_workflow_cmd("OAuth login", "Build Google OAuth2 login")

        assert "Workflow started: OAuth login" in result
        assert "Build Google OAuth2 login" in result
        assert "No stages yet" in result

    def test_creates_state_with_workflow_id(self, mock_db):
        from modules.workflow import start_workflow_cmd
        from modules.workflow.storage import load_state

        with mock_db[0]:
            start_workflow_cmd("Test task", "Description")
            state = load_state()

        assert state is not None
        assert state.workflow_id.startswith("test_task_")
        assert state.current_stage_index == 0
        assert state.dynamic_stages == []

    def test_rejects_active_workflow(self, mock_db):
        from modules.workflow import start_workflow_cmd

        with mock_db[0]:
            start_workflow_cmd("First", "One")
            result = start_workflow_cmd("Second", "Two")

        assert "already active" in result


class TestAddStage:
    """Tests for add_stage_cmd()."""

    def test_adds_stage_to_workflow(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd, workflow_status_cmd

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            result = add_stage_cmd(
                "understand",
                "Explore the codebase",
                [{"id": "und_1", "description": "Explore auth module"}],
            )

        assert "Stage added: understand" in result
        assert "Steps (1):" in result
        assert "Explore auth module" in result

    def test_add_stage_without_workflow_returns_error(self, mock_db):
        from modules.workflow import add_stage_cmd

        with mock_db[0]:
            result = add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Do stuff"}])

        assert "No active workflow" in result

    def test_add_stage_with_gate(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            result = add_stage_cmd(
                "plan",
                "Plan the work",
                [{"id": "p1", "description": "Plan step"}],
                gate_description="Must list all files",
            )

        assert "Gate: Must list all files" in result

    def test_initializes_step_states_to_pending(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd
        from modules.workflow.storage import load_state
        from modules.workflow.models import StepStatus

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [
                {"id": "p1", "description": "Step one"},
                {"id": "p2", "description": "Step two"},
            ])
            state = load_state()

        assert state.step_states["p1"] == StepStatus.PENDING
        assert state.step_states["p2"] == StepStatus.PENDING

    def test_reports_total_stages_after_adding(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("understand", "Understand", [{"id": "u1", "description": "A"}])
            result = add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "B"}])

        assert "2 stage(s)" in result

    def test_auto_generates_step_id_if_missing(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd
        from modules.workflow.storage import load_state

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("test", "Test", [{"description": "Auto ID step"}])
            state = load_state()

        step = state.dynamic_stages[0].steps[0]
        assert step.id == "test_1"
        assert step.description == "Auto ID step"


class TestWorkflowStatus:
    """Tests for workflow_status_cmd()."""

    def test_no_workflow_returns_helpful_message(self, mock_db):
        from modules.workflow import workflow_status_cmd

        with mock_db[0]:
            result = workflow_status_cmd()

        assert "No active workflow" in result
        assert "start_workflow" in result

    def test_shows_stage_and_progress(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, workflow_status_cmd,
        )

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [
                {"id": "p1", "description": "Step one"},
                {"id": "p2", "description": "Step two"},
            ])
            result = workflow_status_cmd()

        assert "Stage: PLAN (1/1)" in result
        assert "Steps: 0/2 complete" in result
        assert "→ plan" in result  # current stage
        assert "○ future stages" not in result

    def test_shows_past_stages_with_check(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, workflow_status_cmd,
            mark_step_done_cmd, advance_stage_cmd,
        )

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("understand", "Understand", [
                {"id": "u1", "description": "Understand"},
            ])
            add_stage_cmd("plan", "Plan", [
                {"id": "p1", "description": "Plan"},
            ])
            mark_step_done_cmd("u1", "Done")
            advance_stage_cmd()
            result = workflow_status_cmd()

        assert "✓ understand" in result
        assert "→ plan" in result


class TestMarkStepDone:
    """Tests for mark_step_done_cmd()."""

    def test_marks_step_complete(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, mark_step_done_cmd,
        )
        from modules.workflow.storage import load_state
        from modules.workflow.models import StepStatus

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Do it"}])
            result = mark_step_done_cmd("p1", "Finished the thing")
            state = load_state()

        assert "marked done" in result
        assert state.step_states["p1"] == StepStatus.COMPLETE
        assert state.step_notes["p1"] == "Finished the thing"

    def test_unknown_step_id_returns_error(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd, mark_step_done_cmd

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Real step"}])
            result = mark_step_done_cmd("fake_id", "Notes")

        assert "Unknown step" in result

    def test_stage_complete_message_when_all_done(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, mark_step_done_cmd,
        )

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Only step"}])
            result = mark_step_done_cmd("p1", "Done")

        assert "Stage complete" in result
        assert "Ready to advance" in result

    def test_no_workflow_returns_error(self, mock_db):
        from modules.workflow import mark_step_done_cmd

        with mock_db[0]:
            result = mark_step_done_cmd("step_1", "Notes")

        assert "No active workflow" in result


class TestAdvanceStage:
    """Tests for advance_stage_cmd()."""

    def test_cannot_advance_with_incomplete_steps(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, advance_stage_cmd,
        )

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [
                {"id": "p1", "description": "Step one"},
                {"id": "p2", "description": "Step two"},
            ])
            result = advance_stage_cmd()

        assert "Cannot advance" in result
        assert "2 step(s) remaining" in result

    def test_advances_when_stage_complete(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, mark_step_done_cmd, advance_stage_cmd,
        )

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("understand", "Understand", [{"id": "u1", "description": "A"}])
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "B"}])
            mark_step_done_cmd("u1", "Done")
            result = advance_stage_cmd()

        assert "Advanced to: plan" in result

    def test_no_workflow_returns_error(self, mock_db):
        from modules.workflow import advance_stage_cmd

        with mock_db[0]:
            result = advance_stage_cmd()

        assert "No active workflow" in result

    def test_workflow_complete_at_end(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, mark_step_done_cmd, advance_stage_cmd,
        )

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Only stage"}])
            mark_step_done_cmd("p1", "Done")
            result = advance_stage_cmd()

        assert "Workflow complete" in result
        assert "Workflow complete" in result


class TestSkipStep:
    """Tests for skip_step_cmd()."""

    def test_skips_step_and_records_reason(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, skip_step_cmd,
        )
        from modules.workflow.storage import load_state
        from modules.workflow.models import StepStatus

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Skip me"}])
            result = skip_step_cmd("p1", "Not applicable for this task")
            state = load_state()

        assert "skipped" in result
        assert "Not applicable" in result
        assert state.step_states["p1"] == StepStatus.SKIPPED
        assert "SKIPPED:" in state.step_notes["p1"]

    def test_unknown_step_returns_error(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd, skip_step_cmd

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Real"}])
            result = skip_step_cmd("fake", "Because")

        assert "Unknown step" in result


class TestMarkStepInProgress:
    """Tests for mark_step_in_progress_cmd()."""

    def test_marks_step_in_progress(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, mark_step_in_progress_cmd,
        )
        from modules.workflow.storage import load_state
        from modules.workflow.models import StepStatus

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Work in progress"}])
            result = mark_step_in_progress_cmd("p1")
            state = load_state()

        assert "in progress" in result
        assert state.step_states["p1"] == StepStatus.IN_PROGRESS

    def test_unknown_step_returns_error(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd, mark_step_in_progress_cmd

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Real"}])
            result = mark_step_in_progress_cmd("fake")

        assert "Unknown step" in result


class TestAddStepNote:
    """Tests for add_step_note_cmd()."""

    def test_adds_note_to_step(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, add_step_note_cmd,
        )
        from modules.workflow.storage import load_state

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Step"}])
            result = add_step_note_cmd("p1", "Found an issue, needs rework")
            state = load_state()

        assert "Note added" in result
        assert state.step_notes["p1"] == "Found an issue, needs rework"

    def test_no_workflow_returns_error(self, mock_db):
        from modules.workflow import add_step_note_cmd

        with mock_db[0]:
            result = add_step_note_cmd("step_1", "Some note")

        assert "No active workflow" in result


class TestStopWorkflow:
    """Tests for stop_workflow_cmd()."""

    def test_stops_workflow_and_clears_state(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, stop_workflow_cmd, workflow_status_cmd,
        )

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Step"}])
            result = stop_workflow_cmd()
            status = workflow_status_cmd()

        assert "stopped" in result
        assert "No active workflow" in status


# ─── Context function tests ────────────────────────────────────────────────────

class TestWorkflowContext:
    """Tests for _workflow_context()."""

    def test_returns_empty_when_no_workflow(self, mock_db):
        from modules.workflow import _workflow_context

        with mock_db[0]:
            result = _workflow_context()

        assert result == ""

    def test_shows_current_stage_and_steps(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, _workflow_context,
        )

        with mock_db[0]:
            start_workflow_cmd("Test task", "Description")
            add_stage_cmd("understand", "Understand the codebase", [
                {"id": "u1", "description": "Explore auth module"},
            ])
            result = _workflow_context()

        assert "Test Task" in result
        assert "UNDERSTAND" in result
        assert "Explore auth module" in result
        assert "○ Explore auth module" in result  # pending step shows ○ + description

    def test_shows_notes_on_steps(self, mock_db):
        from modules.workflow import (
            start_workflow_cmd, add_stage_cmd, mark_step_done_cmd, _workflow_context,
        )

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Plan step"}])
            mark_step_done_cmd("p1", "Found the issue in auth.py")
            result = _workflow_context()

        assert "Found the issue" in result


# ─── Model tests ───────────────────────────────────────────────────────────────

class TestWorkflowStateModel:
    """Tests for WorkflowState model methods."""

    def test_is_stage_complete_true_when_all_done(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd
        from modules.workflow.storage import load_state

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [
                {"id": "p1", "description": "A"},
                {"id": "p2", "description": "B"},
            ])
            from modules.workflow import mark_step_done_cmd
            mark_step_done_cmd("p1", "A done")
            mark_step_done_cmd("p2", "B done")
            state = load_state()

        assert state.is_stage_complete() is True

    def test_is_stage_complete_false_with_pending(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd
        from modules.workflow.storage import load_state
        from modules.workflow.models import StepStatus

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [
                {"id": "p1", "description": "A"},
                {"id": "p2", "description": "B"},
            ])
            from modules.workflow import mark_step_done_cmd
            mark_step_done_cmd("p1", "A done")
            state = load_state()

        assert state.is_stage_complete() is False

    def test_is_stage_complete_true_when_skipped(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd, skip_step_cmd
        from modules.workflow.storage import load_state

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Skipped step"}])
            skip_step_cmd("p1", "Not applicable")
            state = load_state()

        assert state.is_stage_complete() is True

    def test_to_dict_and_from_dict_roundtrip(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd
        from modules.workflow.storage import load_state
        from modules.workflow.models import WorkflowState

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [
                {"id": "p1", "description": "Step one"},
            ])
            from modules.workflow import mark_step_done_cmd
            mark_step_done_cmd("p1", "Done")
            state = load_state()

        data = state.to_dict()
        restored = WorkflowState.from_dict(data)

        assert restored.workflow_id == state.workflow_id
        assert restored.current_stage_index == state.current_stage_index
        assert len(restored.dynamic_stages) == 1
        assert restored.dynamic_stages[0].name == "plan"
        assert restored.step_states["p1"].value == "✓"

    def test_advance_moves_to_next_stage(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd
        from modules.workflow.storage import load_state

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("understand", "Understand", [{"id": "u1", "description": "A"}])
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "B"}])
            from modules.workflow import mark_step_done_cmd, advance_stage_cmd
            mark_step_done_cmd("u1", "Done")
            advance_stage_cmd()
            state = load_state()

        assert state.current_stage_index == 1
        assert state.get_current_stage().name == "plan"

    def test_advance_returns_false_at_end(self, mock_db):
        from modules.workflow import start_workflow_cmd, add_stage_cmd, advance_stage_cmd

        with mock_db[0]:
            start_workflow_cmd("Test", "Desc")
            add_stage_cmd("plan", "Plan", [{"id": "p1", "description": "Only stage"}])
            from modules.workflow import mark_step_done_cmd
            mark_step_done_cmd("p1", "Done")
            result = advance_stage_cmd()

        assert "Workflow complete" in result


# ─── Module registration tests ────────────────────────────────────────────────

class TestModuleRegistration:
    """Tests for get_module() registration."""

    def test_module_has_correct_name(self):
        from modules.workflow import get_module

        m = get_module()
        assert m.name == "workflow"

    def test_module_has_all_expected_called_fns(self):
        from modules.workflow import get_module

        m = get_module()
        names = {fn.name for fn in m.called_fns}
        expected = {
            "start_workflow",
            "add_stage",
            "workflow_status",
            "advance_stage",
            "mark_step_done",
            "mark_step_in_progress",
            "skip_step",
            "add_step_note",
            "stop_workflow",
        }
        assert names == expected

    def test_module_has_two_context_fns(self):
        from modules.workflow import get_module

        m = get_module()
        assert len(m.context_fns) == 2
        tags = {fn.tag for fn in m.context_fns}
        assert tags == {"workflow_help", "workflow"}

    def test_workflow_help_contains_best_practices(self):
        from modules.workflow import get_module

        m = get_module()
        help_fn = next(fn for fn in m.context_fns if fn.tag == "workflow_help")
        help_text = help_fn.fn()

        assert "Understand" in help_text
        assert "Plan" in help_text
        assert "Implement" in help_text
        assert "Verify" in help_text
        assert "Commit" in help_text
        assert "Reproduce" in help_text  # bug fix best practice
