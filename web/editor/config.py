"""Web editor configuration.

Provides file tree and WebSocket settings for the live file editor.
Not to be confused with the main riven_core config (config.py).
"""

from __future__ import annotations

import os

# ─── Root directory ────────────────────────────────────────────────────────────

def get_root_dir() -> str:
    """Return the project root for the web editor file tree.

    Priority:
    1. RV_PROJECT_ROOT  — env var (absolute path override, set by the chat UI)
    2. Walk up from this file looking for .riven/  — this IS the project
    3. Git toplevel fallback

    Note: os.getcwd() is intentionally NOT in the chain — the server could be
    started from any directory (e.g. a parent workspace). The .riven/ marker
    is the authoritative project indicator, independent of where the server
    was started from.
    """
    # 1. Explicit env override
    env_root = os.environ.get("RV_PROJECT_ROOT", "")
    if env_root and os.path.isdir(env_root):
        return os.path.abspath(env_root)

    # 2. Walk up from this file looking for .riven/
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(16):
        if os.path.isdir(os.path.join(cur, ".riven")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    # 3. Git toplevel fallback
    import subprocess
    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        if git_root and os.path.isdir(git_root):
            return git_root
    except Exception:
        pass

    # 4. Fall back to riven_core root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─── File tree filtering ───────────────────────────────────────────────────────

# Names and patterns to exclude from the file tree
EXCLUDE_PATTERNS: list[str] = [
    # Git / VCS
    ".git", ".svn", ".hg",
    # Build artifacts
    "__pycache__", ".pytest_cache", ".mypy_cache",
    ".tox", ".nox", "node_modules", ".parcel-cache",
    ".next", ".nuxt", ".svelte-kit",
    # Python
    "*.pyc", "*.pyo", "*.pyd", ".Python",
    "*.egg-info", ".eggs",
    # Virtual envs
    ".venv", "venv", "env", ".env",
    # IDE / editor noise
    ".vscode", ".idea", "*.swp", "*.swo", "*~",
    # Distribution / packaging
    "dist", "build", "*.whl", "*.tar.gz",
    # Local / generated
    ".riven",  # riven project metadata (not the source itself)
    "*.log",
]

# File extensions to include. Empty = include all.
# Set to a small set for faster tree building in large repos.
INCLUDE_EXTENSIONS: set[str] = {
    # Source
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".htm", ".css", ".scss", ".sass",
    ".md", ".txt",
    ".yaml", ".yml", ".toml", ".json",
    ".sh", ".bash", ".zsh",
    ".sql",
    ".graphql", ".gql",
    # Config / project files
    ".env", ".env.example",
    ".gitignore", ".gitattributes",
    "Makefile", "CMakeLists.txt",
    # Shell-like
    ".fish",
    # Docs
    ".rst",
    # Data
    ".csv", ".xml",
}

# ─── Size limits ───────────────────────────────────────────────────────────────

MAX_FILE_SIZE: int = 256 * 1024  # 256 KB — don't load larger files into the editor


# ─── Timing ───────────────────────────────────────────────────────────────────

# How often to poll the filesystem when watchdog is unavailable (seconds)
POLL_INTERVAL: float = 1.0

# WebSocket heartbeat — send a ping if no message received in this interval (seconds)
WS_HEARTBEAT_INTERVAL: float = 30.0
