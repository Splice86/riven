"""Git integration helpers for the file module.

Provides utilities for:
- Checking if a path is inside a git repo
- Checking if a file is git-tracked
- Getting content-based git hashes for conflict detection
- Generating actionable git warnings

All git operations run from the project root (find_project_root), not from
the file's parent directory. This ensures correct relative paths regardless
of how deeply a file is nested.

These functions are standalone (no class dependencies) so they can be used
by FileEditor and any other module that needs git checks.
"""

from __future__ import annotations

import os
import subprocess

from config import find_project_root


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

    Runs git ls-files --error-unmatch from the project root using the
    relative path from project root. This works correctly at any nesting depth.
    """
    abs_path = os.path.abspath(path)
    root = find_project_root(abs_path)
    if root is None or not os.path.isdir(root):
        return False

    # git ls-files needs the relative path from repo root
    try:
        relative = os.path.relpath(abs_path, root)
    except ValueError:
        # Cross-device path — rare, treat as untracked
        return False

    result = _run_git(['ls-files', '--error-unmatch', '--', relative], cwd=root)
    return result.returncode == 0


def _get_git_hash(path: str) -> str | None:
    """Get the content-based git hash (hash-object) of a file.

    Returns None if the file is not git-tracked or git is unavailable.
    This hash depends only on the file content (blob SHA), not working-tree state.
    """
    abs_path = os.path.abspath(path)
    root = find_project_root(abs_path)
    if root is None or not os.path.isdir(root):
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
    root = find_project_root(abs_path)
    if root is None or not os.path.isdir(root):
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
    root = find_project_root(abs_path)

    if root is None or not os.path.isdir(root) or not _is_git_repo(root):
        return (
            f"⚠️  Cannot safely open {filename} — no git repository found.\n\n"
            f"    Safe file editing (automatic rollback on validation failure) requires git.\n"
            f"    The current directory is not inside a git repository.\n\n"
            f"    To fix this, run:\n\n"
            f"      1. cd to your project root\n"
            f"      2. git init\n"
            f"      3. git add {filename}\n"
            f"      4. git commit -m 'initial'\n\n"
            f"    Or use create_project() which handles this automatically."
        )
    else:
        return (
            f"⚠️  Cannot safely open {filename} — file is not tracked by git.\n\n"
            f"    Safe file editing (automatic rollback on validation failure) requires git.\n"
            f"    {filename} exists but is not in the git index.\n\n"
            f"    To fix this, run:\n\n"
            f"      git add {path}\n"
            f"      git commit -m 'track {filename}'\n\n"
            f"    Or use create_project() which handles this automatically."
        )
