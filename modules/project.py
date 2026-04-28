"""Project module - riven project lifecycle.

A riven project is a directory with a .riven/ folder containing project metadata
and data files (e.g. plan.yaml). Git is initialised automatically on project creation
so that .riven/ can be tracked.

All other modules that need to know the project root should call
get_project_root() — it returns an error string if called outside a riven project,
never a silent fallback.
"""

import os
import subprocess
from datetime import datetime, timezone

from modules import CalledFn, ContextFn, Module
from config import (
    RIVEN_DIR,
    clear_project_root_cache,
    find_project_root,
)


# =============================================================================
# Git helpers (local, not shared with git.py to avoid circular dep)
# =============================================================================

def _run_git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git'] + args,
        capture_output=True,
        text=True,
        cwd=cwd or os.getcwd(),
    )


# =============================================================================
# Core helpers (exposed in __all__ but also used internally)
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


# =============================================================================
# Called functions
# =============================================================================

async def create_project(path: str | None = None) -> str:
    """Create a new riven project.

    Creates .riven/project.yaml and initialises git at the project root.
    Must be called before any other riven tools on a new project.
    """
    target = os.path.abspath(os.path.expanduser(path)) if path else os.getcwd()

    # Already a riven project?
    if is_riven_project(target):
        return (
            f"⚠️  Already a riven project: {target}\n"
            f"   Use get_project_root() to see the current project."
        )

    riven_path = os.path.join(target, RIVEN_DIR)

    # Create .riven/
    try:
        os.makedirs(riven_path, exist_ok=False)
    except FileExistsError:
        return f"⚠️  {riven_path} already exists but is not a riven project."
    except OSError as e:
        return f"[ERROR] Could not create {riven_path}: {e}"

    # Write project.yaml
    project_meta = {
        "meta": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": 1,
        }
    }
    try:
        import yaml
        with open(os.path.join(riven_path, "project.yaml"), "w") as f:
            yaml.dump(project_meta, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        return f"[ERROR] Could not write project.yaml: {e}"

    # Write plan.yaml (empty)
    plan = {"meta": {"project_root": target, "version": 1}, "goals": {}, "next_id": 1}
    try:
        with open(os.path.join(riven_path, "plan.yaml"), "w") as f:
            yaml.dump(plan, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        return f"[ERROR] Could not write plan.yaml: {e}"

    # Git init (if not already a git repo)
    is_git = _run_git(['rev-parse', '--is-inside-work-tree'], cwd=target).returncode == 0
    if not is_git:
        result = _run_git(['init'], cwd=target)
        if result.returncode != 0:
            return f"[ERROR] git init failed: {result.stderr}"

    # Commit .riven/ so it's tracked from the start
    _run_git(['add', '.riven/project.yaml', '.riven/plan.yaml'], cwd=target)
    commit_result = _run_git(
        ['commit', '-m', 'Initialize riven project'],
        cwd=target,
    )
    if commit_result.returncode != 0 and 'nothing to commit' not in commit_result.stdout.lower():
        # Non-fatal — .riven/ created, just not committed
        pass

    # Update config cache so subsequent calls see this project
    clear_project_root_cache()

    # Re-cache now
    from config import find_project_root as _fp
    _fp(target)  # fills cache

    return (
        f"✅ Riven project created at {target}\n\n"
        f"   .riven/ directory:\n"
        f"     project.yaml  — project metadata\n"
        f"     plan.yaml     — goal/planning file\n\n"
        f"   Next step: create_goal() to start planning."
    )


async def get_project_info() -> str:
    """Show info about the current riven project."""
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
        import yaml
        with open(os.path.join(riven, "project.yaml")) as f:
            meta = yaml.safe_load(f) or {}
    except Exception:
        pass

    created = meta.get("meta", {}).get("created_at", "unknown")
    is_git = _run_git(['rev-parse', '--is-inside-work-tree'], cwd=root).returncode == 0

    return (
        f"Project: {root}\n"
        f"Created: {created}\n"
        f"Git:     {'yes' if is_git else 'no (run: git init)'}\n"
        f"Riven:   {riven}"
    )


def _project_help() -> str:
    return """## Project (Help)

Riven uses a **project** concept to anchor all file operations to a consistent root.
Before using any file or planning tools, you must create a riven project.

### Creating a Project
- **create_project()** — create a riven project in the current directory
- **create_project('/path')** — create a riven project at a specific path

Creating a project:
1. Creates a `.riven/` folder with `project.yaml` and `plan.yaml`
2. Runs `git init` if the directory is not already a git repo
3. Commits the `.riven/` folder to git

### Checking the Project
- **get_project_info()** — show current project root, creation date, git status
- **is_riven_project()** — returns True/False for the current directory

### Workflow
1. `create_project()` first (one-time per project)
2. All subsequent tools (open_file, create_goal, etc.) operate relative to this root
3. The `.riven/` folder is versioned — commit it to share project config with your team

### Planning
After creating a project, use `create_goal()` to start planning. Goals are stored
in `.riven/plan.yaml` and are versioned alongside your code.

### Notes
- `.riven/` lives at the project root, not in subdirectories
- Git operations always run from the project root (one git repo per project)
- If you open a file outside the project root, riven will warn you
"""


def _project_context() -> str:
    """Dynamic context — show project info if available."""
    root = get_project_root()
    if root is None:
        return "[no riven project] — run create_project() first"
    return f"[project: {root}]"


def get_module() -> Module:
    return Module(
        name="project",
        called_fns=[
            CalledFn(
                name="create_project",
                description="Create a new riven project in the current directory or at a given path.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Optional path to create the project at. Defaults to current directory.",
                        },
                    },
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
        ],
        context_fns=[
            ContextFn(tag="project_help", fn=_project_help),
            ContextFn(tag="project", fn=_project_context),
        ],
    )
