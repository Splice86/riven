"""
Exit module - allows LLM to signal shutdown.
"""

from typing import Callable
from modules.base import Module


class ExitModule(Module):
    """Exit module - allows LLM to signal shutdown."""
    
    def __init__(self, exit_callback=None):
        self._exit_callback = exit_callback
    
    def info(self) -> str | None:
        return None  # Don't mention exit in prompt
    
    def definitions(self) -> list[dict]:
        return [
            {
                "name": "exit",
                "description": "Signal that the agent has completed its task and should stop",
            }
        ]
    
    def get_functions(self) -> dict[str, Callable]:
        return {"exit": self.exit}
    
    def exit(self) -> str:
        """Signal exit."""
        if self._exit_callback:
            self._exit_callback()
        return "Exiting"
