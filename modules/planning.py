"""Planning module - goal tracking with file associations.

Uses Memory API to store goals and track which files are relevant to each goal.
No callable functions for time (just context) - integrates with file module to
know what files should be open.

Session ID automatically available via get_session_id().
"""

import json
import requests

from modules import CalledFn, ContextFn, Module, get_session_id
from config import get


MEMORY_API_URL = get('memory_api.url', 'http://127.0.0.1:8030')


def _search_planning(query: str, limit: int = 50) -> list[dict]:
    """Search memory DB for planning records."""
    session_id = get_session_id()
    full_query = f"k:{session_id} AND k:planning AND {query}"
    
    try:
        resp = requests.post(
            f"{MEMORY_API_URL}/memories/search",
            json={"query": full_query, "limit": limit},
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json().get("memories", [])
    except Exception:
        pass
    return []


def _search_goals(status: str = None, limit: int = 20) -> list[dict]:
    """Search for goals, optionally filtered by status."""
    query = "k:goal"
    if status:
        query += f" AND p:status={status}"
    return _search_planning(query, limit)


def _get_goal_files(goal: dict) -> list[str]:
    """Extract file list from goal properties."""
    props = goal.get("properties", {})
    files_str = props.get("files", "[]")
    try:
        return json.loads(files_str)
    except (json.JSONDecodeError, TypeError):
        return []


# --- Called Functions ---

async def create_goal(
    title: str,
    description: str = None,
    priority: str = "medium",
    files: list[str] = None
) -> str:
    """Create a new goal with optional files and description."""
    session_id = get_session_id()
    
    priority = priority.lower() if priority else "medium"
    if priority not in ("low", "medium", "high", "critical"):
        priority = "medium"
    
    content = f"Goal: {title}"
    if description:
        content += f"\n\n{description}"
    
    keywords = [
        session_id,
        "planning",
        "goal",
        f"priority:{priority}",
    ]
    
    properties = {
        "status": "active",
        "priority": priority,
        "title": title,
        "files": json.dumps(files or []),
    }
    
    try:
        resp = requests.post(
            f"{MEMORY_API_URL}/memories",
            json={
                "content": content,
                "keywords": keywords,
                "properties": properties,
            },
            timeout=5
        )
        resp.raise_for_status()
        result = resp.json()
        goal_id = result.get("id", "?")
        
        file_count = len(files) if files else 0
        files_info = f" ({file_count} file{'s' if file_count != 1 else ''})" if files else ""
        return f"Created goal #{goal_id}: {title}{files_info}"
    except requests.RequestException as e:
        return f"[ERROR] Failed to create goal: {e}"


async def add_file_to_goal(goal_id: int, file_path: str) -> str:
    """Add a file to an existing goal."""
    session_id = get_session_id()
    
    try:
        resp = requests.get(f"{MEMORY_API_URL}/memories/{goal_id}", timeout=5)
        resp.raise_for_status()
        goal = resp.json()
    except requests.RequestException:
        return f"[ERROR] Goal #{goal_id} not found"
    
    props = goal.get("properties", {})
    files = _get_goal_files(goal)
    
    # Normalize and deduplicate
    import os
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    
    if abs_path in files:
        return f"File already linked to goal #{goal_id}"
    
    files.append(abs_path)
    
    try:
        resp = requests.put(
            f"{MEMORY_API_URL}/memories/{goal_id}",
            json={
                "properties": {
                    **props,
                    "files": json.dumps(files),
                }
            },
            timeout=5
        )
        resp.raise_for_status()
        return f"Linked {os.path.basename(abs_path)} to goal #{goal_id} ({len(files)} files)"
    except requests.RequestException as e:
        return f"[ERROR] Failed to link file: {e}"


async def remove_file_from_goal(goal_id: int, file_path: str) -> str:
    """Remove a file from a goal."""
    session_id = get_session_id()
    
    try:
        resp = requests.get(f"{MEMORY_API_URL}/memories/{goal_id}", timeout=5)
        resp.raise_for_status()
        goal = resp.json()
    except requests.RequestException:
        return f"[ERROR] Goal #{goal_id} not found"
    
    props = goal.get("properties", {})
    files = _get_goal_files(goal)
    
    import os
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    
    if abs_path not in files:
        return f"File not linked to goal #{goal_id}"
    
    files.remove(abs_path)
    
    try:
        resp = requests.put(
            f"{MEMORY_API_URL}/memories/{goal_id}",
            json={
                "properties": {
                    **props,
                    "files": json.dumps(files),
                }
            },
            timeout=5
        )
        resp.raise_for_status()
        return f"Removed {os.path.basename(abs_path)} from goal #{goal_id}"
    except requests.RequestException as e:
        return f"[ERROR] Failed to remove file: {e}"


async def update_goal_status(goal_id: int, status: str) -> str:
    """Update goal status (active, paused, complete)."""
    status = status.lower()
    if status not in ("active", "paused", "complete"):
        return f"[ERROR] Invalid status. Use: active, paused, or complete"
    
    try:
        resp = requests.put(
            f"{MEMORY_API_URL}/memories/{goal_id}",
            json={"properties": {"status": status}},
            timeout=5
        )
        resp.raise_for_status()
        return f"Goal #{goal_id} status → {status}"
    except requests.RequestException:
        return f"[ERROR] Goal #{goal_id} not found"


async def list_goals(status: str = None) -> str:
    """List all goals, optionally filtered by status."""
    goals = _search_goals(status=status, limit=50)
    
    if not goals:
        status_msg = f" ({status})" if status else ""
        return f"No goals found{status_msg}."
    
    lines = [f"Goals:"]
    for goal in goals:
        props = goal.get("properties", {})
        title = props.get("title", "Untitled")
        priority = props.get("priority", "medium")
        goal_status = props.get("status", "active")
        files = _get_goal_files(goal)
        
        priority_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")
        status_marker = "✅" if goal_status == "complete" else "⏸" if goal_status == "paused" else "📌"
        
        file_count = len(files)
        files_str = f" [{file_count} file{'s' if file_count != 1 else ''}]" if files else ""
        
        lines.append(f"  #{goal['id']} {status_marker}{priority_emoji} {title}{files_str}")
    
    return "\n".join(lines)


async def get_goal(goal_id: int) -> str:
    """Get full details of a goal including linked files."""
    try:
        resp = requests.get(f"{MEMORY_API_URL}/memories/{goal_id}", timeout=5)
        resp.raise_for_status()
        goal = resp.json()
    except requests.RequestException:
        return f"[ERROR] Goal #{goal_id} not found"
    
    props = goal.get("properties", {})
    title = props.get("title", "Untitled")
    priority = props.get("priority", "medium")
    status = props.get("status", "active")
    files = _get_goal_files(goal)
    
    lines = [
        f"## Goal #{goal_id}: {title}",
        f"Status: {status} | Priority: {priority}",
    ]
    
    if files:
        lines.append(f"\nFiles ({len(files)}):")
        for f in files:
            import os
            lines.append(f"  - {f}")
    else:
        lines.append("\nNo files linked")
    
    content = goal.get("content", "")
    if content:
        # Skip the "Goal: title" prefix if present
        if content.startswith("Goal:"):
            content = content.split("\n\n", 1)[-1] if "\n\n" in content else ""
        if content:
            lines.append(f"\n{content}")
    
    return "\n".join(lines)


async def close_goal(goal_id: int) -> str:
    """Mark a goal as complete."""
    return await update_goal_status(goal_id, "complete")


def _planning_help() -> str:
    """Static tool documentation."""
    return """## Planning (Help)

Use goals to track what you're working on. Goals can have files linked so you know what to have open.

### Workflow
1. **create_goal(title, description?, priority?, files?)** - Create a new goal
2. **add_file_to_goal(goal_id, file_path)** - Link a file to a goal
3. **list_goals(status?)** - List all goals (active, paused, complete)
4. **get_goal(goal_id)** - See goal details and linked files
5. **update_goal_status(goal_id, status)** - Change status (active/paused/complete)
6. **close_goal(goal_id)** - Mark goal complete
7. **remove_file_from_goal(goal_id, file_path)** - Unlink a file

### Priority Levels
critical > high > medium > low

### Notes
- Goals are session-scoped (private to this session)
- Files are stored as absolute paths
- Use goals to decide which files should be open via {file}"""


def _planning_context() -> str:
    """Dynamic context - active goals with files. Changes when goals are created/updated."""
    session_id = get_session_id()
    goals = _search_goals(status="active", limit=10)
    
    if not goals:
        return "No active goals"
    
    lines = ["=== Active Goals ==="]
    for goal in goals:
        props = goal.get("properties", {})
        title = props.get("title", "Untitled")
        priority = props.get("priority", "medium")
        files = _get_goal_files(goal)
        
        priority_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")
        
        if files:
            lines.append(f"\n{priority_emoji} #{goal['id']} {title}")
            for f in files:
                import os
                lines.append(f"   - {os.path.basename(f)}")
        else:
            lines.append(f"\n{priority_emoji} #{goal['id']} {title} (no files)")
    
    return "\n".join(lines)


def get_module() -> Module:
    """Get the planning module."""
    return Module(
        name="planning",
        called_fns=[
            CalledFn(
                name="create_goal",
                description="Create a new goal with optional description, priority, and file list.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Goal title"},
                        "description": {"type": "string", "description": "Optional goal description"},
                        "priority": {"type": "string", "description": "Priority: critical, high, medium, low (default: medium)"},
                        "files": {"type": "array", "items": {"type": "string"}, "description": "Optional list of file paths to link"},
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
                        "goal_id": {"type": "integer", "description": "Goal ID to link file to"},
                        "file_path": {"type": "string", "description": "Path to the file (absolute or relative)"},
                    },
                    "required": ["goal_id", "file_path"],
                },
                fn=add_file_to_goal,
            ),
            CalledFn(
                name="remove_file_from_goal",
                description="Remove a file link from a goal.",
                parameters={
                    "type": "object",
                    "properties": {
                        "goal_id": {"type": "integer", "description": "Goal ID"},
                        "file_path": {"type": "string", "description": "Path to the file to unlink"},
                    },
                    "required": ["goal_id", "file_path"],
                },
                fn=remove_file_from_goal,
            ),
            CalledFn(
                name="update_goal_status",
                description="Update goal status.",
                parameters={
                    "type": "object",
                    "properties": {
                        "goal_id": {"type": "integer", "description": "Goal ID"},
                        "status": {"type": "string", "description": "New status: active, paused, or complete"},
                    },
                    "required": ["goal_id", "status"],
                },
                fn=update_goal_status,
            ),
            CalledFn(
                name="list_goals",
                description="List all goals, optionally filtered by status.",
                parameters={
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Optional filter: active, paused, or complete"},
                    },
                    "required": [],
                },
                fn=list_goals,
            ),
            CalledFn(
                name="get_goal",
                description="Get full details of a goal including linked files.",
                parameters={
                    "type": "object",
                    "properties": {
                        "goal_id": {"type": "integer", "description": "Goal ID to view"},
                    },
                    "required": ["goal_id"],
                },
                fn=get_goal,
            ),
            CalledFn(
                name="close_goal",
                description="Mark a goal as complete.",
                parameters={
                    "type": "object",
                    "properties": {
                        "goal_id": {"type": "integer", "description": "Goal ID to close"},
                    },
                    "required": ["goal_id"],
                },
                fn=close_goal,
            ),
        ],
        context_fns=[
            ContextFn(tag="planning_help", fn=_planning_help),
            ContextFn(tag="planning", fn=_planning_context),
        ],
    )
