"""Exit module for riven - allows LLM to exit the program."""

import threading
from modules import Module

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
    """Get the exit module."""
    
    def exit_session(message: str = "Goodbye!") -> str:
        """Exit the current session.
        
        Args:
            message: Optional goodbye message to display.
        
        Returns:
            Goodbye message.
        """
        _exit_requested.set()
        return message
    
    return Module(
        name="exit",
        enrollment=lambda: None,
        functions={
            "exit_session": exit_session,
        },
        get_context=lambda: None,
        tag="system"
    )