"""System module for riven - system operations like exit and reload."""

import os
import threading
import sys
from datetime import datetime
from modules import Module, check_modules_changed, update_module_mtimes

# Load config - same as core.py
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
try:
    import yaml
    with open(CONFIG_PATH) as f:
        CONFIG = yaml.safe_load(f)
except Exception:
    CONFIG = {}

MEMORY_API_URL = os.environ.get("MEMORY_API_URL", CONFIG.get('memory_api', {}).get('url', "http://127.0.0.1:8030"))
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
        return message
    
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
    
    def write_context(filename: str = None) -> str:
        """Write current session context to a file for debugging.
        
        Dumps: system info, all module contexts (file, memory, time, etc.),
        and all conversation turns from memory API.
        
        Args:
            filename: Optional filename. Defaults to debug_context_YYYYMMDD_HHMMSS.txt
            
        Returns:
            Path to the written file.
        """
        import requests
        import platform
        
        # Generate filename if not provided
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"debug_context_{timestamp}.txt"
        
        lines = []
        lines.append("=" * 60)
        lines.append("RIVEN DEBUG CONTEXT DUMP")
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append("=" * 60)
        
        # System info
        lines.append("\n### SYSTEM INFO ###")
        lines.append(f"Python: {platform.python_version()}")
        lines.append(f"Platform: {platform.platform()}")
        lines.append(f"Executable: {sys.executable}")
        
        # Get module contexts
        lines.append("\n### MODULE CONTEXTS ###")
        from modules import get_all_modules
        for module in get_all_modules():
            if module.get_context:
                context = module.get_context()
                lines.append(f"\n--- {module.name} ---")
                lines.append(str(context))
        
        # Get conversation history
        lines.append("\n### CONVERSATION HISTORY ###")
        try:
            resp = requests.get(
                f"{MEMORY_API_URL}/context",
                params={"db_name": DEFAULT_DB, "limit": 100}
            )
            context = resp.json().get("context", [])
            for msg in context:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                lines.append(f"\n[{role.upper()}]")
                lines.append(content[:500] if len(content) > 500 else content)
        except Exception as e:
            lines.append(f"Error fetching context: {e}")
        
        # Write to file
        with open(filename, "w") as f:
            f.write("\n".join(lines))
        
        return f"Context written to: {filename}"
    
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
            "write_context": write_context,
        },
        get_context=get_system_context,
        tag="system"
    )