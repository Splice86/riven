"""System module for riven - system operations like exit and reload."""

import threading
import sys
from modules import Module, check_modules_changed, update_module_mtimes

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
        
        Returns:
            Goodbye message.
        """
        _exit_requested.set()
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
        },
        get_context=get_system_context,
        tag="system"
    )