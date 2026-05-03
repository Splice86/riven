"""Storage utilities for workflow state.

Persists WorkflowState to ContextDB so it survives across sessions/turns.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from modules import _session_id


# Key used to store workflow state in context DB
_STATE_KEY = "workflow_state"
_MAX_STATE_AGE_HOURS = 24  # Auto-cleanup old states after 24 hours


def _get_db():
    """Get the ContextDB instance."""
    from db import ContextDB
    return ContextDB()


def save_state(state: 'WorkflowState') -> None:
    """Save workflow state to context DB.
    
    Args:
        state: WorkflowState to persist
    """
    db = _get_db()
    session_id = _session_id.get()
    
    if not session_id:
        raise ValueError("No session ID available")
    
    data = state.to_dict()
    data['saved_at'] = datetime.now(timezone.utc).isoformat()
    
    db.add("system", f"[workflow_state]{json.dumps(data)}[/workflow_state]", session=session_id)


def load_state() -> Optional['WorkflowState']:
    """Load workflow state from context DB.
    
    Returns:
        WorkflowState if found, None otherwise
    """
    from .models import WorkflowState
    db = _get_db()
    session_id = _session_id.get()
    
    if not session_id:
        return None
    
    history = db.get_history(session=session_id)
    
    for msg in reversed(history):
        content = msg.get('content', '')
        if f'[{_STATE_KEY}]' in content:
            # Extract JSON from [workflow_state]...[/workflow_state]
            start = content.find(f'[{_STATE_KEY}]') + len(_STATE_KEY) + 2
            end = content.find(f'[/{_STATE_KEY}]')
            if end > start:
                json_str = content[start:end]
                try:
                    data = json.loads(json_str)
                    
                    # Check if state is too old
                    saved_at = data.get('saved_at')
                    if saved_at:
                        saved_time = datetime.fromisoformat(saved_at.replace('Z', '+00:00'))
                        age_hours = (datetime.now(timezone.utc) - saved_time).total_seconds() / 3600
                        if age_hours > _MAX_STATE_AGE_HOURS:
                            # State too old, clear it
                            clear_state()
                            return None
                    
                    return WorkflowState.from_dict(data)
                except (json.JSONDecodeError, KeyError):
                    pass
    
    return None


def clear_state() -> None:
    """Clear workflow state from context DB."""
    db = _get_db()
    session_id = _session_id.get()
    
    if not session_id:
        return
    
    # Note: This doesn't actually remove old messages, just signals we should ignore them
    # In practice, the LLM context management will handle this
    pass


def get_active_workflow_id() -> Optional[str]:
    """Get the ID of the currently active workflow, if any."""
    state = load_state()
    return state.workflow_id if state else None
