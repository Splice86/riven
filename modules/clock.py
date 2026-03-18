"""
Clock module - injects current date/time into prompt.
"""

from datetime import datetime
from typing import Callable
from modules.base import Module


class ClockModule(Module):
    """Clock module - injects current date/time into prompt."""
    
    TAG = "time"  # Tag for {{time}} replacement

    def info(self) -> str:
        """Return current datetime."""
        return f"Current time: {datetime.now().isoformat()}"

    def definitions(self) -> list[dict] | None:
        """Return None - time is only available as a tag, not a callable tool."""
        return None  # Don't expose time as a tool to the LLM
    
    def get_functions(self) -> dict[str, Callable]:
        """Return empty - time is only a tag, not a callable function."""
        return {}
