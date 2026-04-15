"""System module for riven - system operations like exit, reload, and core management."""

import os
import threading
import sys
from modules import Module, check_modules_changed, update_module_mtimes

# Load config - same as core.py
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
try:
    import yaml
    with open(CONFIG_PATH) as f:
        CONFIG = yaml.safe_load(f)
except Exception:
    CONFIG = {}

from riven_secrets import get_memory_api
MEMORY_API_URL = os.environ.get("MEMORY_API_URL", get_memory_api())
DEFAULT_DB = os.environ.get("MEMORY_DB", CONFIG.get('memory_api', {}).get('db_name', "riven"))

# Global flag to signal exit (thread-safe)
# This must be at module level so all imports share the same instance
_exit_requested = threading.Event()


def is_exit_requested() -> bool:
    """Check if exit was requested."""
    return _exit_requested.is_set()


def clear_exit() -> None:
    """Clear the exit flag."""
    _exit_requested.clear()


# Core management functions - import from core_manager
def _get_manager():
    """Lazy import to avoid circular deps."""
    from core_manager import get_manager
    return get_manager()


def list_cores() -> list[dict]:
    """List available cores with names and descriptions."""
    return _get_manager().list()


def get_core_description(core_name: str) -> str:
    """Get description for a specific core."""
    config = _get_manager().get(core_name)
    if config:
        return config.get('description', 'No description')
    return f"Core '{core_name}' not found"


def core_exists(core_name: str) -> bool:
    """Check if a core exists."""
    return _get_manager().exists(core_name)


def switch_core(core_name: str) -> str:
    """Switch to a different core."""
    return _get_manager().set_current(core_name)


def get_current_core() -> str:
    """Get the current core name."""
    return _get_manager().get_current() or "None"


def get_module():
    """Get the system module."""
    
    def exit_session(message: str = "Goodbye!") -> str:
        """Exit the current session.
        
        Args:
            message: Optional goodbye message to display.
            
        Note:
            This will terminate the session after the current tool completes.
        """
        _exit_requested.set()
        # Print goodbye immediately so user sees it
        print(f"\n{message}\n")
        # Force exit after current tool completes
        import sys
        sys.exit(0)
    
    def check_reload_modules() -> str:
        """Check if any module files have changed and need reloading.
        
        Returns:
            Whether modules have changed and need reload.
        """
        if check_modules_changed():
            update_module_mtimes()
            return "Modules have changed. Call reload_modules to apply changes."
        return "No module changes detected."
    
    def get_system_info() -> str:
        """Get system information like Python version and platform.

        Returns:
            System information string.
        """
        import platform
        info = f"Python: {platform.python_version()}\n"
        info += f"Platform: {platform.platform()}\n"
        info += f"Executable: {sys.executable}"
        return info

    def get_system_context() -> str:
        """Get system context for prompt."""
        import platform
        return f"System: Python {platform.python_version()} on {platform.platform()}"

    return Module(
        name="system",
        enrollment=lambda: None,
        functions={
            "exit_session": exit_session,
            "check_reload_modules": check_reload_modules,
            "get_system_info": get_system_info,
            "list_cores": list_cores,
            "get_core_description": get_core_description,
            "core_exists": core_exists,
            "switch_core": switch_core,
            "get_current_core": get_current_core,
        },
        get_context=get_system_context,
        tag="system"
    )