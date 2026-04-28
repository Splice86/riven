"""Planning module — goals and plans stored in .riven/plan.yaml.

This module provides the goal-oriented planning API (list_goals, create_goal,
add_file_to_goal, update_goal_status, close_goal) backed by .riven/plan.yaml.

Goals are stored in plan.yaml (the source of truth). The Memory API is
still used for context-based search indexing (via _sync_to_memory).
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import yaml

from modules import CalledFn, ContextFn, Module
from modules.project import get_project_root

logger = logging.getLogger("modules.planning")


# =============================================================================
# File I/O helpers
# =============================================================================

def _get_plan_path(project_root: str) -> str:
    """Return the path to .riven/plan.yaml inside project_root."""
    return os.path.join(project_root, ".riven", "plan.yaml")


def _read_plan(project_root: str) -> list[dict[str, Any]]:
    """Read goals from .riven/plan.yaml. Returns empty list if file missing."""
    plan_path = _get_plan_path(project_root)
    if not os.path.exists(plan_path):
        return []
    try:
        with open(plan_path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return []
        return data.get("goals", [])
    except (yaml.YAMLError, OSError):
        return []


def _write_plan(project_root: str, goals: list[dict[str, Any]]) -> None:
    """Write goals back to .riven/plan.yaml."""
    plan_path = _get_plan_path(project_root)
    riven_dir = os.path.join(project_root, ".riven")
    os.makedirs(riven_dir, exist_ok=True)
    with open(plan_path, "w") as f:
        yaml.safe_dump({"goals": goals}, f, default_flow_style=False)


def _next_goal_id(goals: list[dict[str, Any]]) -> int:
    """Return the next available goal ID (max existing + 1, or 1 if empty)."""
    if not goals:
        return 1
    return max(g.get("id", 0) for g in goals) + 1


def _sync_to_memory(goal_id: int, goal_data: dict[str, Any]) -> None:
    """Fire-and-forget background sync of goal to Memory API for search indexing."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_async_sync_to_memory(goal_id, goal_data))
    except RuntimeError:
        # Sync context (no running loop) — run synchronously
        try:
            asyncio.run(_async_sync_to_memory(goal_id, goal_data))
        except Exception as e:
            logger.warning(f"_sync_to_memory failed: {e}")


async def _async_sync_to_memory(goal_id: int, goal_data: dict[str, Any]) -> None:
    """Async worker that syncs a goal to the Memory API."""
    try:
        from modules.memory_utils import _set_memory

        now = datetime.now(timezone.utc).isoformat()
        content = json.dumps({
            "type": "goal",
            "id": goal_id,
            "title": goal_data.get("title", ""),
            "description": goal_data.get("description", ""),
            "status": goal_data.get("status", "open"),
            "priority": goal_data.get("priority", "medium"),
            "updated_at": now,
        })
        await _set_memory(
            key=f"goal:{goal_id}",
            content=content,
            content_type="application/json",
        )
    except Exception as e:
        logger.warning(f"_sync_to_memory failed: {e}")


# =============================================================================
# Public Goal API
# =============================================================================

async def create_goal(
    title: str,
    description: str = "",
    priority: str = "medium",
    files: list[str] | None = None,
) -> str:
    """Create a new goal and persist it to .riven/plan.yaml.

    Args:
        title: Goal title
        description: Optional description
        priority: One of 'low', 'medium', 'high' (defaults to 'medium')
        files: Optional list of file paths linked to this goal

    Returns:
        A formatted string confirming creation with the new goal ID.
    """
    from modules.project import get_project_root

    project_root = get_project_root()
    if not project_root:
        return "Error: No Riven project found. Run create_project() first."

    if priority not in ("low", "medium", "high"):
        priority = "medium"

    goals = _read_plan(project_root)
    goal_id = _next_goal_id(goals)

    now = datetime.now(timezone.utc).isoformat()
    new_goal = {
        "id": goal_id,
        "title": title,
        "description": description,
        "status": "open",
        "priority": priority,
        "created_at": now,
        "updated_at": now,
        "properties": {
            "files": json.dumps(files or []),
        },
    }

    goals.append(new_goal)
    _write_plan(project_root, goals)
    _sync_to_memory(goal_id, new_goal)

    return f"✓ Goal #{goal_id} '{title}' created (priority: {priority})."


async def add_file_to_goal(goal_id: int, file_path: str) -> str:
    """Add a file path to an existing goal's files list.

    Returns:
        Success or error message string.
    """
    from modules.project import get_project_root

    project_root = get_project_root()
    if not project_root:
        return "Error: No Riven project found."

    goals = _read_plan(project_root)
    for goal in goals:
        if goal.get("id") == goal_id:
            files_list = _get_goal_files(goal)
            if file_path in files_list:
                return f"File '{file_path}' is already linked to goal #{goal_id}."
            files_list.append(file_path)
            goal["properties"]["files"] = json.dumps(files_list)
            goal["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_plan(project_root, goals)
            _sync_to_memory(goal_id, goal)
            return f"✓ File '{file_path}' added to goal #{goal_id}."

    return f"Error: Goal #{goal_id} not found."


async def update_goal_status(goal_id: int, status: str) -> str:
    """Update the status of an existing goal.

    Args:
        goal_id: The goal ID
        status: One of 'open', 'in_progress', 'done', 'closed'

    Returns:
        Goal data dict on success, or error message string.
    """
    from modules.project import get_project_root

    project_root = get_project_root()
    if not project_root:
        return "Error: No Riven project found."

    if status not in ("open", "in_progress", "done", "closed"):
        return f"Error: Invalid status '{status}'. Use: open, in_progress, done, closed."

    goals = _read_plan(project_root)
    for goal in goals:
        if goal.get("id") == goal_id:
            goal["status"] = status
            goal["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_plan(project_root, goals)
            _sync_to_memory(goal_id, goal)
            return (
                f"Goal #{goal_id} status updated to '{status}'.\n"
                + f"Title: {goal.get('title', '')}\n"
                + f"Priority: {goal.get('priority', 'medium')}\n"
                + f"Updated: {goal.get('updated_at', '')}"
            )

    return f"Error: Goal #{goal_id} not found."


async def close_goal(goal_id: int) -> str:
    """Close (mark as done) a goal. Delegates to update_goal_status."""
    return await update_goal_status(goal_id, "done")


# =============================================================================
# Utility
# =============================================================================

def _get_goal_files(goal: dict[str, Any]) -> list[str]:
    """Extract the files list from a goal's properties field.

    Handles both valid JSON and edge cases (missing field, invalid JSON).
    """
    files_str = goal.get("properties", {}).get("files", "[]")
    if not files_str:
        return []
    try:
        return json.loads(files_str)
    except (json.JSONDecodeError, TypeError):
        return []


async def list_goals(status: str = None) -> str:
    """List all goals, optionally filtered by status (open, in_progress, done, closed)."""
    project_root = get_project_root()
    if not project_root:
        return "Error: No Riven project found. Run create_project() first."

    goals = _read_plan(project_root)
    if not goals:
        return "No goals yet. Use create_goal() to add one."

    valid_statuses = {"open", "in_progress", "done", "closed"}
    lines = ["Goals:"]
    for goal in sorted(goals, key=lambda g: g.get("id", 0)):
        if status and goal.get("status") != status:
            continue
        goal_id = goal.get("id", "?")
        title = goal.get("title", "Untitled")
        goal_status = goal.get("status", "open")
        priority = goal.get("priority", "medium")
        files = _get_goal_files(goal)

        status_marker = {
            "open": "🟢",
            "in_progress": "🟡",
            "done": "✅",
            "closed": "⚪",
        }.get(goal_status, "")
        priority_marker = {"high": "🔥", "medium": "📌", "low": "🔽"}.get(priority, "")
        files_str = f" [{len(files)} file{'s' if len(files) != 1 else ''}]" if files else ""
        lines.append(f"  #{goal_id} {status_marker}{priority_marker} {title}{files_str}")

    result = "\n".join(lines)
    if status and status not in valid_statuses:
        result += f"\n(Unknown status filter '{status}' — showing all)"
    return result


# =============================================================================
# Module export
# =============================================================================

def get_module() -> Module:
    return Module(
        name="planning",
        called_fns=[
            CalledFn(
                name="list_goals",
                description="List all goals, optionally filtered by status (open, in_progress, done, closed).",
                parameters={
                    "type": "object",
                    "properties": {"status": {"type": "string", "description": "Filter: open, in_progress, done, or closed"}},
                    "required": [],
                },
                fn=list_goals,
            ),
            CalledFn(
                name="create_goal",
                description="Create a new goal. Goals are tracked in .riven/plan.yaml.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Goal title"},
                        "description": {"type": "string", "description": "Optional description"},
                        "priority": {"type": "string", "description": "Priority: low, medium, or high"},
                        "files": {"type": "array", "items": {"type": "string"}, "description": "Optional file paths to link"},
                    },
                    "required": ["title"],
                },
                fn=create_goal,
            ),
            CalledFn(
                name="add_file_to_goal",
                description="Link a file to an existing goal.",
                parameters={
                    "type": "object",
                    "properties": {
                        "goal_id": {"type": "integer", "description": "Goal ID"},
                        "file_path": {"type": "string", "description": "Path to the file"},
                    },
                    "required": ["goal_id", "file_path"],
                },
                fn=add_file_to_goal,
            ),
            CalledFn(
                name="update_goal_status",
                description="Update a goal's status.",
                parameters={
                    "type": "object",
                    "properties": {
                        "goal_id": {"type": "integer", "description": "Goal ID"},
                        "status": {"type": "string", "description": "Status: open, in_progress, done, or closed"},
                    },
                    "required": ["goal_id", "status"],
                },
                fn=update_goal_status,
            ),
            CalledFn(
                name="close_goal",
                description="Close (mark as done) a goal.",
                parameters={
                    "type": "object",
                    "properties": {"goal_id": {"type": "integer", "description": "Goal ID"}},
                    "required": ["goal_id"],
                },
                fn=close_goal,
            ),
        ],
        context_fns=[],
    )
