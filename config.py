"""Riven config system - single source of truth for all configuration.

Precedence (highest wins):
    1. Env var (RV_* prefix, __ for nesting: RV_MEMORY_API__URL)
    2. Non-template YAML (secrets.yaml)  (user overrides)
    3. config.yaml  (committed defaults)
    4. Template YAML (secrets_template.yaml)  (fallback if no user file)
    5. Hardcoded default passed to get()

Template convention:
    If <name>_template.yaml exists, it serves as fallback.
    If <name>.yaml exists (without _template), it wins.
    Example: secrets_template.yaml → check secrets.yaml first, fallback to template.
"""

import os
import subprocess
from typing import Any

# Cached project root — recomputed if not yet set
_project_root_cache: dict[str, str | None] = {}

# The riven project data directory
RIVEN_DIR = ".riven"


def _walk_up(path: str, stop_at: str | None = None) -> list[str]:
    """Walk from path up to stop_at (or filesystem root), yield each dir.

    stop_at can be a string (stop when current equals this path) or a
    callable stop_at(dir) that returns the "stop-found" value or None/False
    to continue (e.g. _git_is_repo returns the git root or False).
    """
    parts = []
    current = os.path.abspath(path)
    stop = os.path.abspath(stop_at) if isinstance(stop_at, str) else stop_at
    while current and (stop is None or (not isinstance(stop, str) and current != stop)):
        parts.append(current)
        if callable(stop):
            found = stop(current)
            if found:
                return parts
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return parts


def _run_git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a git command, returning the result. Errors are silenced.

    cwd is normalized to a directory (not a file) to prevent NotADirectoryError
    when a file path is accidentally passed as the working directory.
    """
    if cwd:
        if os.path.isfile(cwd):
            cwd = os.path.dirname(cwd)
        if not os.path.isdir(cwd):
            cwd = None  # Fall back to os.getcwd() below
    return subprocess.run(
        ['git'] + args,
        capture_output=True,
        text=True,
        cwd=cwd or os.getcwd(),
    )


def _git_toplevel(cwd: str | None = None) -> str | None:
    """Return git root via rev-parse, or None if not in a repo."""
    result = _run_git(['rev-parse', '--show-toplevel'], cwd=cwd)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _is_git_repo(cwd: str | None = None) -> bool:
    """Check if cwd (or cwd=os.getcwd()) is inside a git working tree."""
    result = _run_git(['rev-parse', '--is-inside-work-tree'], cwd=cwd)
    return result.returncode == 0 and 'true' in result.stdout.lower()


def find_project_root(from_path: str | None = None) -> str | None:
    """Find the riven project root by walking up from from_path.

    Discovery order:
      1. RV_PROJECT_ROOT env var (explicit override)
      2. .riven/ directory (primary — this IS the project root)
      3. git rev-parse --show-toplevel (fallback for git repos without .riven/)
      4. .riven/ or .git/ walk from from_path upward

    Returns None if no project found.
    Result is cached after first call.
    """
    global _project_root_cache
    start = os.path.abspath(from_path or os.getcwd())

    # Check per-path cache first
    if start in _project_root_cache:
        return _project_root_cache[start]

    # 1. Env var override
    env_root = os.environ.get('RV_PROJECT_ROOT')
    if env_root and os.path.isdir(env_root):
        _project_root_cache[start] = os.path.abspath(env_root)
        return _project_root_cache[start]

    # 2. Check for .riven/ at start and walk up
    for directory in _walk_up(start):
        if os.path.isdir(os.path.join(directory, RIVEN_DIR)):
            _project_root_cache[start] = directory
            return _project_root_cache[start]

    # 3. Git toplevel fallback
    git_root = _git_toplevel(start)
    if git_root:
        _project_root_cache[start] = git_root
        return _project_root_cache[start]

    _project_root_cache[start] = None
    return None


def clear_project_root_cache() -> None:
    """Clear the cached project roots. Call after create_project."""
    global _project_root_cache
    _project_root_cache.clear()


def _find_project_root() -> str:
    """Find the riven_core installation root (where config.yaml lives)."""
    return os.path.dirname(os.path.abspath(__file__))


def _load_yaml(path: str) -> dict:
    """Load a yaml file, return empty dict on failure."""
    if os.path.exists(path):
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
            return data if data else {}
    return {}


def _env_override(data: dict, prefix: str = "RV") -> dict:
    """Override dict values with matching env vars.

    Env var format: RV_SECTION__KEY maps to data['section']['key'].
    Double underscore separates nesting levels.
    """
    result = _deep_copy_dict(data)
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(f"{prefix}_"):
            continue
        # Strip prefix and split on __
        rest = env_key[len(prefix) + 1:]
        parts = rest.split("__")
        if not parts:
            continue

        # Navigate to the right nested dict
        current = result
        for part in parts[:-1]:
            part = part.lower()
            if part not in current:
                current[part] = {}
            current = current[part]

        # Set the final key, trying to preserve type
        final_key = parts[-1].lower()
        current[final_key] = _coerce(env_val)

    return result


def _deep_copy_dict(data: dict) -> dict:
    """Deep copy a dict."""
    import copy
    return copy.deepcopy(data) if data else {}


def _coerce(value: str) -> Any:
    """Coerce a string env var to its likely Python type."""
    # Bool
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    # Int
    try:
        return int(value)
    except ValueError:
        pass
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    # String
    return value


class _Config:
    """Singleton config registry."""

    def __init__(self):
        self._loaded = False
        self._merged: dict = {}
        self._search_paths: list[str] = []

    def register(self, *yaml_files: str) -> None:
        """Register yaml files to load. Supports 'name_template.yaml' convention.

        If a *_template.yaml is registered, the system first looks for
        <name>.yaml (without _template). If found, it wins; otherwise the
        template is used as fallback.

        Args:
            *yaml_files: Relative paths from project root (e.g. "config.yaml",
                         "memory/config.yaml", "secrets_template.yaml")
        """
        root = _find_project_root()
        for yaml_file in yaml_files:
            path = os.path.join(root, yaml_file)
            self._search_paths.append(path)

    def _resolve_template(self, template_path: str) -> str:
        """Given a *_template.yaml path, return the preferred file to load.

        If <name>.yaml exists (without _template), use it; otherwise use template.
        """
        if not template_path.endswith("_template.yaml"):
            return template_path

        # Derive the non-template name
        base, ext = os.path.splitext(template_path)
        non_template = base + ext  # e.g. secrets_template.yaml -> secrets.yaml
        if os.path.exists(non_template):
            return non_template
        return template_path

    def load(self) -> None:
        """Load and merge all registered yaml files.

        Files are loaded in reverse registration order (highest priority first).
        
        Template convention: *_template.yaml is the fallback. If the associated
        non-template file (e.g. secrets.yaml) exists, it overrides the template.
        This works correctly because user files should override template defaults.
        """
        if self._loaded:
            return

        merged = {}
        # Load in reverse order so later registrations win
        for path in reversed(self._search_paths):
            if path.endswith("_template.yaml"):
                # Template is the FALLBACK - load template first
                data = _load_yaml(path)
                
                # Then check if user override exists - it should override template
                base, ext = os.path.splitext(path)
                user_base = base.replace("_template", "")
                user_path = user_base + ext
                if os.path.exists(user_path):
                    user_data = _load_yaml(user_path)
                    data = _deep_merge(data, user_data)  # user overrides template
            else:
                # Non-template YAMLs load as-is
                data = _load_yaml(path)
            
            if data:
                merged = _deep_merge(merged, data)

        self._merged = merged
        self._loaded = True

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by dotted key with full precedence applied.

        Precedence (highest wins):
            1. Env var (RV_SECTION__KEY, __ for nesting)
            2. Registered yaml files (merged, later overrides earlier)
            3. Default passed here

        Args:
            key: Dot-separated key path (e.g. "memory_api.url", "llm.model")
            default: Fallback if key not found anywhere

        Returns:
            The config value, or default if not found
        """
        if not self._loaded:
            self.load()

        # Env var wins everything
        env_val = _get_via_env(key)
        if env_val is not None:
            return env_val

        # Walk the merged config
        parts = key.split(".")
        current = self._merged
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def get_all(self) -> dict:
        """Get the entire merged config dict."""
        if not self._loaded:
            self.load()
        return _deep_copy_dict(self._merged)

    def reload(self) -> None:
        """Force a reload of all config files."""
        self._loaded = False
        self._merged = {}
        self.load()


def _get_via_env(key: str) -> Any:
    """Get a config value via env var matching.

    key "memory_api.url" → check RV_MEMORY_API__URL
    """
    # memory_api.url -> RV_MEMORY_API__URL
    env_key = "RV_" + key.upper().replace(".", "__")
    if env_key in os.environ:
        return _coerce(os.environ[env_key])
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override wins."""
    result = _deep_copy_dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = _deep_copy_dict(val)
    return result


# --- Singleton instance ---

config = _Config()

# Register default config files in load order (later overrides earlier).
# Template YAMLs are loaded first as fallback only.
config.register("secrets_template.yaml")  # Lowest: template fallback
config.register("config.yaml")            # Overrides template defaults


# --- Convenience accessors ---

def get(key: str, default: Any = None) -> Any:
    """Get a config value. See _Config.get() for full docs."""
    return config.get(key, default)


def get_all() -> dict:
    """Get the entire merged config dict."""
    return config.get_all()


def reload() -> None:
    """Reload all config files (useful after changing env vars or yaml files)."""
    config.reload()


def get_llm_config(name: str = "primary") -> dict:
    """Get a named LLM config with secrets applied.
    
    Args:
        name: The LLM config name (e.g., "primary", "alternate")
    
    Returns:
        Dict with url, model, api_key, timeout merged from config + secrets.
        Secrets (url, api_key) override config templates.
    
    Example:
        # config.yaml has llm.primary.model = "MiniMax-M2.7"
        # secrets.yaml has llm.primary.url = "http://100.90.58.38:8000/v1"
        # get_llm_config("primary") returns both merged
    """
    if not config._loaded:
        config.load()
    
    # Get template from config.yaml
    template = config.get(f"llm.{name}", {})
    
    # Check for env override: RV_LLM__<NAME>__URL, RV_LLM__<NAME>__MODEL, etc.
    env_prefix = f"RV_LLM__{name.upper()}__"
    result = _deep_copy_dict(template)
    
    for env_key, env_val in os.environ.items():
        if env_key.startswith(env_prefix):
            key = env_key[len(env_prefix):].lower()
            result[key] = _coerce(env_val)
    
    # Ensure required fields - config.yaml is the source of truth
    if "url" not in result:
        raise ValueError(f"LLM config '{name}' missing 'url' - check config.yaml")
    result.setdefault("model", "MiniMax-M2.7")
    result.setdefault("api_key", "sk-dummy")
    result.setdefault("timeout", 120)
    
    return result
