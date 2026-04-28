"""Project module - riven project lifecycle and planning.

A riven project is a directory with a .riven/ folder containing project metadata
and a plan. Git is initialised automatically on project creation.

All file operations are anchored to the project root. Planning tools (add_plan_item,
update_plan_item, etc.) read/write .riven/project.yaml as the source of truth.
"""

import os
import subprocess
from datetime import datetime, timezone

import yaml

from modules import CalledFn, ContextFn, Module
from config import RIVEN_DIR, clear_project_root_cache, find_project_root


# =============================================================================
# Git helpers (local, avoids circular dep with modules.file.git)
# =============================================================================

def _run_git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git'] + args,
        capture_output=True,
        text=True,
        cwd=cwd or os.getcwd(),
    )


# =============================================================================
# Project detection (also used by other modules)
# =============================================================================

def is_riven_project(from_path: str | None = None) -> bool:
    """True if from_path or any parent has a .riven/ directory."""
    root = find_project_root(from_path)
    return root is not None and os.path.isdir(os.path.join(root, RIVEN_DIR))


def get_project_root(from_path: str | None = None) -> str | None:
    """Return the project root, or None if not in a riven project."""
    return find_project_root(from_path)


def riven_dir(from_path: str | None = None) -> str | None:
    """Return the .riven/ path, or None if not in a riven project."""
    root = find_project_root(from_path)
    if root is None:
        return None
    return os.path.join(root, RIVEN_DIR)


def _project_path() -> str | None:
    """Path to .riven/project.yaml, or None if not in a project."""
    root = find_project_root()
    if root is None:
        return None
    return os.path.join(root, RIVEN_DIR, "project.yaml")


def _ensure_project_file() -> str | None:
    """Return error string if project.yaml can't be accessed, None on success."""
    path = _project_path()
    if path is None:
        return "⚠️  No riven project found. Run create_project() first."
    if not os.path.exists(path):
        return f"⚠️  {path} not found. Run create_project() to initialise the project."
    return None


def _read_project() -> tuple[dict, str]:
    """Read project.yaml. Returns (data, error_string)."""
    err = _ensure_project_file()
    if err:
        return {}, err
    try:
        with open(_project_path()) as f:
            return yaml.safe_load(f) or {}, ""
    except yaml.YAMLError as e:
        return {}, f"[ERROR] project.yaml is malformed: {e}"
    except OSError as e:
        return {}, f"[ERROR] Could not read project.yaml: {e}"


def _write_project(data: dict) -> str | None:
    """Write project.yaml. Returns error string on failure, None on success."""
    err = _ensure_project_file()
    if err:
        return err
    try:
        with open(_project_path(), "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return None
    except OSError as e:
        return f"[ERROR] Could not write project.yaml: {e}"


def _normalize_files(files: list[str] | None) -> list[str]:
    """Normalize file list to absolute paths, deduplicated."""
    seen = set()
    result = []
    for f in (files or []):
        abs_path = os.path.abspath(os.path.expanduser(f))
        if abs_path not in seen:
            seen.add(abs_path)
            result.append(abs_path)
    return result


# =============================================================================
# Called functions — project lifecycle
# =============================================================================

async def create_project(path: str | None = None) -> str:
    """Create a new riven project.

    Creates .riven/project.yaml and initialises git at the project root.
    Must be called before any other riven tools on a new project.
    """
    target = os.path.abspath(os.path.expanduser(path)) if path else os.getcwd()

    if is_riven_project(target):
        return (
            f"⚠️  Already a riven project: {target}\n"
            f"   Use get_project_info() to see the current project."
        )

    riven_path = os.path.join(target, RIVEN_DIR)

    # Detect preexisting .riven/ and check if it's already a riven project
    if os.path.isdir(riven_path):
        if os.path.isfile(os.path.join(riven_path, "project.yaml")):
            return (
                f"⚠️  Already a riven project: {target}\n"
                f"   Use get_project_info() to see the current project."
            )
        return f"⚠️  {riven_path}/ already exists but is not a riven project.\n   Remove it first: shutil.rmtree({riven_path!r})"

    try:
        os.makedirs(riven_path)
    except OSError as e:
        return f"[ERROR] Could not create {riven_path}: {e}"

    now = datetime.now(timezone.utc).isoformat()
    initial = {
        "meta": {
            "created_at": now,
            "updated_at": now,
            "version": 1,
        },
        "plan": {
            "title": "",
            "items": {},
            "next_item_id": 1,
        },
    }

    try:
        with open(os.path.join(riven_path, "project.yaml"), "w") as f:
            yaml.dump(initial, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        return f"[ERROR] Could not write project.yaml: {e}"

    # Git: init only if no repo exists yet
    is_git = _run_git(['rev-parse', '--is-inside-work-tree'], cwd=target).returncode == 0
    if not is_git:
        result = _run_git(['init'], cwd=target)
        if result.returncode != 0:
            return f"[ERROR] git init failed: {result.stderr}"
        # Commit .riven/ so it's tracked from the start (fresh repo only)
        _run_git(['add', '.riven/project.yaml'], cwd=target)
        commit_result = _run_git(['commit', '-m', 'Initialize riven project'], cwd=target)
        if commit_result.returncode != 0:
            pass  # Non-fatal for fresh repos too
        git_note = "\n   git initialised with initial commit."
    else:
        git_note = "\n   git already set up — existing repo preserved."

    # Re-cache so subsequent calls see this project
    clear_project_root_cache()
    find_project_root(target)

    return (
        f"✅ Riven project created at {target}{git_note}\n\n"
        f"   .riven/project.yaml — project metadata + plan\n\n"
        f"   Next step: use plan tools to build your project plan.\n"
        f"   Try: set_plan_title('My Project') then add_plan_item('First task')"
    )


async def get_project_info() -> str:
    """Show information about the current riven project."""
    root = get_project_root()
    if root is None:
        return (
            "⚠️  No riven project found.\n\n"
            "   Run create_project() to initialise one, or provide a path:\n"
            "     create_project('/path/to/your/project')\n"
        )

    riven = os.path.join(root, RIVEN_DIR)
    meta = {}
    try:
        with open(os.path.join(riven, "project.yaml")) as f:
            meta = yaml.safe_load(f) or {}
    except Exception:
        pass

    created = meta.get("meta", {}).get("created_at", "unknown")
    plan_title = meta.get("plan", {}).get("title", "(untitled)")
    plan_items = meta.get("plan", {}).get("items", {})
    active = [i for i in plan_items.values() if i.get("status") == "active"]
    is_git = _run_git(['rev-parse', '--is-inside-work-tree'], cwd=root).returncode == 0

    return (
        f"Project: {root}\n"
        f"Created: {created}\n"
        f"Git:     {'yes' if is_git else 'no (run: git init)'}\n"
        f"Plan:    {plan_title!r} ({len(active)} active items)"
    )


async def set_project_name(name: str) -> str:
    """Set the project name."""
    data, err = _read_project()
    if err:
        return err
    data.setdefault("meta", {})["name"] = name
    data["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    err = _write_project(data)
    if err:
        return err
    return f"Project name set to: {name}"


# =============================================================================
# Called functions — plan
# =============================================================================

async def set_plan_title(title: str) -> str:
    """Set the plan title."""
    data, err = _read_project()
    if err:
        return err
    data.setdefault("plan", {})["title"] = title
    data["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    err = _write_project(data)
    if err:
        return err
    return f"Plan title set to: {title}"


async def add_plan_item(title: str, content: str = "", files: list[str] = None) -> str:
    """Add a new plan item."""
    data, err = _read_project()
    if err:
        return err

    plan = data.setdefault("plan", {})
    items = plan.setdefault("items", {})
    next_id = plan.get("next_item_id", 1)
    item_id = next_id
    plan["next_item_id"] = next_id + 1

    now = datetime.now(timezone.utc).isoformat()
    items[str(item_id)] = {
        "title": title,
        "content": content,
        "status": "active",
        "files": _normalize_files(files),
        "created_at": now,
        "updated_at": now,
    }

    data["meta"]["updated_at"] = now
    err = _write_project(data)
    if err:
        return err

    count = len(items[str(item_id)]["files"])
    files_info = f" ({count} file{'s' if count != 1 else ''})" if count else ""
    return f"Added plan #{item_id}: {title}{files_info}"


async def update_plan_item(
    item_id: int,
    title: str = None,
    content: str = None,
    status: str = None,
    files: list[str] = None,
) -> str:
    """Update a plan item."""
    data, err = _read_project()
    if err:
        return err

    items = data.get("plan", {}).get("items", {})
    item = items.get(str(item_id))
    if not item:
        return f"[ERROR] Plan #{item_id} not found"

    if title is not None:
        item["title"] = title
    if content is not None:
        item["content"] = content
    if status is not None:
        status = status.lower()
        if status not in ("active", "complete"):
            return f"[ERROR] Invalid status. Use: active or complete"
        item["status"] = status
    if files is not None:
        item["files"] = _normalize_files(files)

    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["meta"]["updated_at"] = item["updated_at"]

    err = _write_project(data)
    if err:
        return err

    return f"Updated plan #{item_id}"


async def list_plan_items(status: str = None) -> str:
    """List all plan items, optionally filtered by status (active, complete)."""
    data, err = _read_project()
    if err:
        return err

    items = data.get("plan", {}).get("items", {})
    if not items:
        return "No plan items yet. Use add_plan_item() to start."

    lines = ["Plan items:"]
    for item_id_str, item in sorted(items.items(), key=lambda x: int(x[0])):
        if status and item.get("status") != status:
            continue
        title = item.get("title", "Untitled")
        item_status = item.get("status", "active")
        files = item.get("files", [])

        status_marker = {"complete": "✅", "active": "📌"}.get(item_status, "")
        file_count = len(files)
        files_str = f" [{file_count} file{'s' if file_count != 1 else ''}]" if files else ""
        lines.append(f"  #{item_id_str} {status_marker} {title}{files_str}")

    return "\n".join(lines)


async def get_plan_item(item_id: int) -> str:
    """Get full details of a plan item."""
    data, err = _read_project()
    if err:
        return err

    items = data.get("plan", {}).get("items", {})
    item = items.get(str(item_id))
    if not item:
        return f"[ERROR] Plan #{item_id} not found"

    title = item.get("title", "Untitled")
    item_status = item.get("status", "active")
    content = item.get("content", "")
    files = item.get("files", [])

    lines = [f"## Plan #{item_id}: {title}", f"Status: {item_status}"]

    if files:
        lines.append(f"\nFiles ({len(files)}):")
        for f in files:
            lines.append(f"  - {f}")
    else:
        lines.append("\nNo files linked")

    if content:
        lines.append(f"\n{content}")

    return "\n".join(lines)


async def close_plan_item(item_id: int) -> str:
    """Mark a plan item as complete."""
    return await update_plan_item(item_id, status="complete")


async def add_file_to_plan(item_id: int, file_path: str) -> str:
    """Link a file to a plan item."""
    data, err = _read_project()
    if err:
        return err

    items = data.get("plan", {}).get("items", {})
    item = items.get(str(item_id))
    if not item:
        return f"[ERROR] Plan #{item_id} not found"

    abs_path = os.path.abspath(os.path.expanduser(file_path))
    files = item.setdefault("files", [])

    if abs_path in files:
        return f"File already linked to plan #{item_id}"

    files.append(abs_path)
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["meta"]["updated_at"] = item["updated_at"]

    err = _write_project(data)
    if err:
        return err

    return f"Linked {os.path.basename(abs_path)} to plan #{item_id} ({len(files)} files)"


async def remove_file_from_plan(item_id: int, file_path: str) -> str:
    """Unlink a file from a plan item."""
    data, err = _read_project()
    if err:
        return err

    items = data.get("plan", {}).get("items", {})
    item = items.get(str(item_id))
    if not item:
        return f"[ERROR] Plan #{item_id} not found"

    abs_path = os.path.abspath(os.path.expanduser(file_path))
    files = item.get("files", [])

    if abs_path not in files:
        return f"File not linked to plan #{item_id}"

    files.remove(abs_path)
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["meta"]["updated_at"] = item["updated_at"]

    err = _write_project(data)
    if err:
        return err

    return f"Removed {os.path.basename(abs_path)} from plan #{item_id}"


# =============================================================================
# Context
# =============================================================================

def _project_help() -> str:
    return """## Project (Help)

Every riven project has a **plan** stored in `.riven/project.yaml`. The plan is the
guide for all programming work — it lives with the project and is versioned with git.

### Project Setup
- **create_project()** — create a riven project (one-time per project)
- **get_project_info()** — show project root, git status, plan title
- **set_project_name(name)** — name the project

### Planning
- **set_plan_title(title)** — name the plan
- **add_plan_item(title, content?, files?)** — add a plan item
- **update_plan_item(item_id, title?, content?, status?, files?)** — edit a plan item
- **list_plan_items(status?)** — list items (active/complete)
- **get_plan_item(item_id)** — full item details
- **close_plan_item(item_id)** — mark item complete
- **add_file_to_plan(item_id, file_path)** — link a file
- **remove_file_from_plan(item_id, file_path)** — unlink a file

### Workflow
1. `create_project()` first (one-time)
2. `set_plan_title()` to name your plan
3. `add_plan_item()` for each task or phase — link files as your roadmap
4. Open linked files before working, close them when done
5. `close_plan_item()` when finished

### Notes
- Plan is stored in `.riven/project.yaml` (versioned with git)
- Files are stored as absolute paths
- Active plan items and their files appear in context below ({project})
"""


def _project_context() -> str:
    """Dynamic context — project meta + active plan items."""
    err = _ensure_project_file()
    if err:
        return "[no riven project] — run create_project() first"

    data, _ = _read_project()
    meta = data.get("meta", {})
    plan = data.get("plan", {})
    items = plan.get("items", {})
    active = {sid: it for sid, it in items.items() if it.get("status") == "active"}

    name = meta.get("name", "") or meta.get("created_at", "").split("T")[0]
    title = plan.get("title", "(no title)")

    lines = [f"[project: {name}] plan: {title!r}"]

    if not active:
        lines.append("  No active plan items. Use add_plan_item() to start.")
        return "\n".join(lines)

    lines.append("  Active plan items:")
    for sid, item in sorted(active.items(), key=lambda x: int(x[0])):
        t = item.get("title", "Untitled")
        files = item.get("files", [])
        if files:
            names = ", ".join(os.path.basename(f) for f in files)
            lines.append(f"  #{sid} {t}  →  {names}")
        else:
            lines.append(f"  #{sid} {t}  →  no files linked")

    return "\n".join(lines)


# =============================================================================
# Module export
# =============================================================================

def get_module() -> Module:
    return Module(
        name="project",
        called_fns=[
            CalledFn(
                name="create_project",
                description="Create a new riven project in the current directory or at a given path.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Optional path. Defaults to current directory."}},
                    "required": [],
                },
                fn=create_project,
            ),
            CalledFn(
                name="get_project_info",
                description="Show information about the current riven project.",
                parameters={"type": "object", "properties": {}, "required": []},
                fn=get_project_info,
            ),
            CalledFn(
                name="set_project_name",
                description="Set the project name.",
                parameters={
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Project name"}},
                    "required": ["name"],
                },
                fn=set_project_name,
            ),
            CalledFn(
                name="set_plan_title",
                description="Set the plan title.",
                parameters={
                    "type": "object",
                    "properties": {"title": {"type": "string", "description": "Plan title"}},
                    "required": ["title"],
                },
                fn=set_plan_title,
            ),
            CalledFn(
                name="add_plan_item",
                description="Add a new plan item.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Item title"},
                        "content": {"type": "string", "description": "Optional description or notes"},
                        "files": {"type": "array", "items": {"type": "string"}, "description": "Optional list of file paths to link"},
                    },
                    "required": ["title"],
                },
                fn=add_plan_item,
            ),
            CalledFn(
                name="update_plan_item",
                description="Update a plan item. Omit fields to leave them unchanged.",
                parameters={
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "integer", "description": "Plan item ID"},
                        "title": {"type": "string", "description": "New title"},
                        "content": {"type": "string", "description": "New content"},
                        "status": {"type": "string", "description": "Status: active or complete"},
                        "files": {"type": "array", "items": {"type": "string"}, "description": "Replace file list"},
                    },
                    "required": ["item_id"],
                },
                fn=update_plan_item,
            ),
            CalledFn(
                name="list_plan_items",
                description="List all plan items, optionally filtered by status.",
                parameters={
                    "type": "object",
                    "properties": {"status": {"type": "string", "description": "Filter: active or complete"}},
                    "required": [],
                },
                fn=list_plan_items,
            ),
            CalledFn(
                name="get_plan_item",
                description="Get full details of a plan item.",
                parameters={
                    "type": "object",
                    "properties": {"item_id": {"type": "integer", "description": "Plan item ID"}},
                    "required": ["item_id"],
                },
                fn=get_plan_item,
            ),
            CalledFn(
                name="close_plan_item",
                description="Mark a plan item as complete.",
                parameters={
                    "type": "object",
                    "properties": {"item_id": {"type": "integer", "description": "Plan item ID"}},
                    "required": ["item_id"],
                },
                fn=close_plan_item,
            ),
            CalledFn(
                name="add_file_to_plan",
                description="Link a file to a plan item.",
                parameters={
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "integer", "description": "Plan item ID"},
                        "file_path": {"type": "string", "description": "Path to the file"},
                    },
                    "required": ["item_id", "file_path"],
                },
                fn=add_file_to_plan,
            ),
            CalledFn(
                name="remove_file_from_plan",
                description="Unlink a file from a plan item.",
                parameters={
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "integer", "description": "Plan item ID"},
                        "file_path": {"type": "string", "description": "Path to the file"},
                    },
                    "required": ["item_id", "file_path"],
                },
                fn=remove_file_from_plan,
            ),
        ],
        context_fns=[
            ContextFn(tag="project_help", fn=_project_help, static=True),
            ContextFn(tag="project", fn=_project_context),
        ],
    )
