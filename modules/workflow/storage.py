"""Storage for workflow state — delegates to modules.workflow.db."""

from datetime import datetime, timezone
from typing import Optional

from modules import _session_id
from . import db
from .models import WorkflowState


def save_state(state: 'WorkflowState') -> None:
    """Save workflow state to the workflow DB.

    Args:
        state: WorkflowState to persist
    """
    session_id = _session_id.get()
    if not session_id:
        raise ValueError("No session ID available")

    data = state.to_dict()
    db.upsert(
        session_id=session_id,
        workflow_id=state.workflow_id,
        current_stage_index=state.current_stage_index,
        step_states=data.get("step_states"),
        step_notes=data.get("step_notes"),
        dynamic_stages=data.get("dynamic_stages"),
        dynamic_steps=data.get("dynamic_steps"),
        started_at=data.get("started_at", datetime.now(timezone.utc).isoformat()),
        saved_at=datetime.now(timezone.utc).isoformat(),
    )


def load_state() -> Optional['WorkflowState']:
    """Load the active workflow state for the current session.

    Returns:
        WorkflowState if found and fresh, None otherwise.
    """
    session_id = _session_id.get()
    if not session_id:
        return None

    row = db.load(session_id)
    if not row:
        return None

    state = WorkflowState.from_dict(row)
    return state

def clear_state() -> None:
    """Remove the workflow state for the current session."""
    session_id = _session_id.get()
    if session_id:
        db.delete(session_id)


def get_active_workflow_id() -> Optional[str]:
    """Get the ID of the currently active workflow, if any."""
    state = load_state()
    return state.workflow_id if state else None
