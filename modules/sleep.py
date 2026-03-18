"""
Sleep module - allows LLM to put the agent to sleep.
"""

import threading
from typing import Callable
from modules.base import Module


class SleepModule(Module):
    """Sleep module - allows LLM to put the agent to sleep."""
    
    def __init__(self, agentic_loop):
        self._loop = agentic_loop

    def info(self) -> str | None:
        return None  # No info to inject
    
    def definitions(self) -> list[dict]:
        return [
            {
                "name": "sleep",
                "description": "Put the agent to sleep for a specified duration in seconds. The agent will automatically wake up after the duration. Use this when there are no tasks to process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "seconds": {
                            "type": "number",
                            "description": "Number of seconds to sleep"
                        }
                    },
                    "required": ["seconds"]
                }
            }
        ]
    
    def get_functions(self) -> dict[str, Callable]:
        return {"sleep": self.sleep}
    
    def sleep(self, seconds: float) -> str:
        """Put the agent to sleep for a duration."""
        if seconds <= 0:
            return "Invalid sleep duration"
        
        # Schedule wake and start sleeping (non-blocking)
        timer = self._loop.schedule_wake(seconds)
        timer.start()
        self._loop.sleep(wait_for_wake=False)
        
        return f"Agent will sleep for {seconds} seconds and then wake up."
