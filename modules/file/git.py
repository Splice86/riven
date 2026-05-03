"""Git integration helpers for the file module.

Provides utilities for:
- Checking if a path is inside a git repo
- Checking if a file is git-tracked
- Getting content-based git hashes for conflict detection
- Generating actionable git warnings

All git operations run from the git toplevel (found via _git_toplevel), not from
the file's parent directory. This ensures correct relative paths regardless
of how deeply a file is nested.

These functions are standalone (no class dependencies) so they can be used
by FileEditor and any other module that needs git checks.
"""

from __future__ import annotations

import os
import subprocess

from config import _git_toplevel


# =============================================================================
# Core Helpers
# =============================================================================

def _run_git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a git command, returning the result. Errors are silenced."""
    return subprocess.run(
        ['git'] + args,
        capture_output=True,
        text=True,
        cwd=cwd or os.getcwd(),
    )


def _is_git_repo(cwd: str | None = None) -> bool:
    """Check if cwd (or cwd=os.getcwd()) is inside a git working tree."""
    result = _run_git(['rev-parse', '--is-inside-work-tree'], cwd=cwd)
    return result.returncode == 0 and 'true' in result.stdout.lower()


def _is_git_tracked(path: str) -> bool:
    """Check if a file is tracked by git.

    Uses git rev-parse --show-toplevel from the file's directory to find the
    actual git repo root (not the riven project root). Then uses git ls-files
    --error-unmatch with the relative path. Works correctly at any nesting depth.
    """
    abs_path = os.path.abspath(path)

    # Find the actual git repo root (not the riven project root).
    # This handles the case where ~/.riven/ exists but the real git repo
    # is deeper, e.g. riven_core/.git.
    root = _git_toplevel(abs_path)
    if root is None:
        return False

    # git ls-files needs the relative path from repo root
    try:
        relative = os.path.relpath(abs_path, root)
    except ValueError:
        # Cross-device path — rare, treat as untracked
        return False

    result = _run_git(['ls-files', '--error-unmatch', '--', relative], cwd=root)
    return result.returncode == 0


def _git_add(path: str) -> bool:
    """Add a file to git tracking.

    Uses git toplevel from the file's directory to find the actual git repo.
    Runs `git add` on the relative path from repo root.

    Returns True if file was added successfully or already tracked.
    Returns False if git repo not found or add failed.
    """
    abs_path = os.path.abspath(path)

    # Find the actual git repo root
    root = _git_toplevel(abs_path)
    if root is None:
        return False

    # git add needs the relative path from repo root
    try:
        relative = os.path.relpath(abs_path, root)
    except ValueError:
        # Cross-device path
        return False

    result = _run_git(['add', '--', relative], cwd=root)
    return result.returncode == 0


def track_in_git(path: str) -> tuple[bool, str]:
    """Add a file to git and verify it's in the correct repository.

    This is the primary tool for enrolling files in git. It:
    1. Finds the git repo for the file
    2. Verifies the file is in the same repo as the riven project
    3. Adds the file to git if not already tracked

    Returns:
        (success, message) tuple where success is True if file is now tracked.

    The message explains any issues or confirms enrollment.
    """
    import os
    from config import find_project_root

    abs_path = os.path.abspath(path)
    filename = os.path.basename(path)

    # Find the git repo for this file
    file_git_root = _git_toplevel(abs_path)
    if file_git_root is None:
        return False, (
            f"Cannot track {filename} — no git repository found.\n\n"
            f"Initialize git first: git init && git add {filename} && git commit -m 'initial'"
        )

    # Find the project root (riven project)
    project_root = find_project_root(abs_path)
    if project_root is None:
        return False, (
            f"Cannot track {filename} — not inside a riven project.\n\n"
            f"File is in git repo at {file_git_root}, but no .riven/ directory found."
        )

    # Find the git repo for the project
    project_git_root = _git_toplevel(project_root)
    if project_git_root is None:
        return False, (
            f"Cannot track {filename} — project is not inside a git repository."
        )

    # Cross-repo check: file's repo must match project's repo
    if os.path.normpath(file_git_root) != os.path.normpath(project_git_root):
        return False, (
            f"Cannot track {filename} — cross-repo conflict.\n\n"
            f"File is in git repo: {file_git_root}\n"
            f"Project is in git repo: {project_git_root}\n\n"
            f"Move {filename} into the project directory, or use allow_untracked=True to open anyway."
        )

    # Check if already tracked
    if _is_git_tracked(abs_path):
        return True, f"{filename} is already tracked in git."

    # Try to add the file
    if _git_add(abs_path):
        return True, f"Added {filename} to git tracking."

    return False, f"Failed to add {filename} to git. Check git status for errors."


def _get_git_hash(path: str) -> str | None:
    """Get the content-based git hash (hash-object) of a file.

    Returns None if the file is not git-tracked or git is unavailable.
    This hash depends only on the file content (blob SHA), not working-tree state.
    """
    abs_path = os.path.abspath(path)
    root = _git_toplevel(abs_path)
    if root is None:
        return None

    try:
        relative = os.path.relpath(abs_path, root)
    except ValueError:
        return None

    result = _run_git(['hash-object', '--', relative], cwd=root)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _git_status(path: str) -> str:
    """Get the short git status code for a file (e.g. ' M', '??', 'A ')."""
    abs_path = os.path.abspath(path)
    root = _git_toplevel(abs_path)
    if root is None:
        return ''

    try:
        relative = os.path.relpath(abs_path, root)
    except ValueError:
        return ''

    result = _run_git(['status', '-s', '--', relative], cwd=root)
    if result.returncode == 0:
        lines = result.stdout.strip().split('\n')
        if lines and lines[0]:
            return lines[0].split()[0]
    return ''


def _git_status_summary(cwd: str | None = None) -> str:
    """Get a one-line summary of git status for the repo."""
    result = _run_git(['status', '-s'], cwd=cwd)
    if result.returncode == 0:
        count = len([l for l in result.stdout.strip().split('\n') if l])
        if count == 0:
            return 'clean'
        return f'{count} change(s)'
    return 'not a git repo'


# =============================================================================
# Warning / User-Facing Helpers
# =============================================================================

def _git_warning(path: str, abs_path: str) -> str:
    """Generate an actionable warning when a file is not git-tracked."""
    filename = os.path.basename(path)

    # _is_git_tracked already checked with _git_toplevel — if we got here,
    # a git repo exists but the file isn't tracked. Use _git_toplevel for
    # consistency in the warning.
    root = _git_toplevel(abs_path)

    if root is None:
        return (
            f"⚠️  Cannot safely open {filename} — no git repository found.\n\n"
            f"    Safe file editing (automatic rollback on validation failure) requires git.\n"
            f"    The current directory is not inside a git repository.\n\n"
            f"    To fix this, run:\n\n"
            f"      git init\n"
            f"      git add {filename}\n"
            f"      git commit -m 'initial'"
        )
    else:
        return (
            f"⚠️  Cannot safely open {filename} — file is not tracked by git.\n\n"
            f"    Safe file editing (automatic rollback on validation failure) requires git.\n"
            f"    {filename} exists but is not in the git index.\n\n"
            f"    To fix this, run:\n\n"
            f"      git add {path}\n"
            f"      git commit -m 'track {filename}'\n\n"
            f"    Then re-open the file."
        )
