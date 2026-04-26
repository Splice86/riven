"""Git integration helpers for the file module.

Provides utilities for:
- Checking if a path is inside a git repo
- Checking if a file is git-tracked
- Getting content-based git hashes for conflict detection
- Generating actionable git warnings
- Initialising git tracking for a file

All functions are standalone (no class dependencies) so they can be used
by both FileEditor and any other module that needs git checks.
"""

from __future__ import annotations

import os
import subprocess


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

    Uses git ls-files --error-unmatch which returns 0 only for tracked files,
    regardless of working-tree state. The canonical approach.
    """
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    basename = os.path.basename(abs_path)
    result = subprocess.run(
        ['git', 'ls-files', '--error-unmatch', '--', basename],
        cwd=parent,
        capture_output=True,
    )
    return result.returncode == 0


def _get_git_hash(path: str) -> str | None:
    """Get the content-based git hash (hash-object) of a file.

    Returns None if the file is not git-tracked or git is unavailable.
    This hash depends only on the file content (blob SHA), not working-tree state.
    """
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    result = _run_git(['hash-object', '--', os.path.basename(abs_path)], cwd=parent)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _git_status(path: str) -> str:
    """Get the short git status code for a file (e.g. ' M', '??', 'A ')."""
    result = _run_git(['status', '-s', '--', path])
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
    work_dir = os.path.dirname(abs_path) or '.'

    if not _is_git_repo(work_dir):
        return (
            f"⚠️  Cannot safely open {filename} — no git repository found.\n\n"
            f"    Safe file editing (automatic rollback on validation failure) requires git.\n\n"
            f"    To fix this, run:\n\n"
            f"      1. git init\n"
            f"      2. git add {filename}\n"
            f"      3. git commit -m 'initial'\n\n"
            f"    Or use the init_git_for_file(path) tool and I'll run these for you.\n\n"
            f"    Alternatively, open a file that IS inside an existing git repository."
        )
    else:
        return (
            f"⚠️  Cannot safely open {filename} — file is not tracked by git.\n\n"
            f"    Safe file editing (automatic rollback on validation failure) requires git.\n\n"
            f"    To fix this, run:\n\n"
            f"      1. git add {path}\n"
            f"      2. git commit -m 'track {filename}'\n\n"
            f"    Or use the init_git_for_file(path) tool and I'll run these for you.\n\n"
            f"    Alternatively, open a file that IS tracked by git."
        )


# =============================================================================
# init_git_for_file — the tool implementation
# =============================================================================

async def init_git_for_file(path: str) -> str:
    """Initialize git tracking for a file to enable safe rollback.

    If the workspace has no git repo, runs git init first.
    Then stages and commits the file so it can be safely edited.

    Call this when open_file fails with a git-tracking warning.
    """
    abs_path = os.path.abspath(os.path.expanduser(path))
    filename = os.path.basename(abs_path)
    work_dir = os.path.dirname(abs_path) or '.'

    if not os.path.exists(abs_path):
        return f"Error: File {abs_path} not found"

    # Step 1: git init if needed
    if not _is_git_repo(work_dir):
        result = _run_git(['init'], cwd=work_dir)
        if result.returncode != 0:
            return f"Failed to git init: {result.stderr}"

    # Step 2: git add
    result = _run_git(['add', '--', os.path.basename(abs_path)], cwd=work_dir)
    if result.returncode != 0:
        return f"Failed to git add {filename}: {result.stderr}"

    # Step 3: git commit
    result = _run_git(
        ['commit', '-m', f'Track {filename} for safe editing'],
        cwd=work_dir,
    )
    if result.returncode != 0:
        if 'nothing to commit' in result.stdout:
            return (
                f"⚠️  {filename} is already tracked by git (nothing new to commit).\n"
                f"    Try open_file('{path}') again."
            )
        return f"Failed to git commit: {result.stderr}"

    return (
        f"✅ Git tracking enabled for {filename}.\n\n"
        f"    You can now open the file with open_file('{path}') and edits\n"
        f"    will have automatic rollback protection on validation failure."
    )
