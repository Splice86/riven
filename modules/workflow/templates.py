"""Workflow templates — no longer used.

Workflows are now built from scratch per-task using start_workflow() + add_stage().
This file is kept as a stub to avoid breaking imports.
"""

from .models import Workflow

# No template workflows — all workflows are built dynamically
WORKFLOWS: dict[str, Workflow] = {}


def get_workflow(workflow_id: str) -> Workflow | None:
    """Get a workflow by ID. Always returns None — templates are no longer used."""
    return None


def list_workflows(category: str | None = None) -> list[Workflow]:
    """List workflows. Always returns empty list — templates are no longer used."""
    return []
