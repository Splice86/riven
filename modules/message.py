"""
Message module - allows external messages to be sent to the agent.

When a message is added, it will wake the agent if it's sleeping.
"""

from typing import Callable, Optional
from modules.base import Module


class MessageModule(Module):
    """Message queue module - allows external messages to be sent to the agent."""
    
    TAG = "messages"  # Tag for {{messages}} replacement
    
    def __init__(self, agentic_loop=None):
        self._queue: list[str] = []
        self._agentic_loop = agentic_loop  # Reference to wake the agent
    
    def set_agentic_loop(self, loop) -> None:
        """Set the agentic loop reference to enable wake on message."""
        self._agentic_loop = loop
    
    def info(self) -> str | None:
        """Return info about pending messages."""
        if self._queue:
            return f"You have {len(self._queue)} message(s) waiting. Use get_message to read them."
        return None  # Return None when no messages, so tag becomes empty
    
    def definitions(self) -> list[dict]:
        """Return get_message as a tool."""
        return [
            {
                "name": "get_message",
                "description": "Get the next message from the queue",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        ]
    
    def get_functions(self) -> dict[str, Callable]:
        """Return the get_message function."""
        return {"get_message": self.get_message}
    
    def add_message(self, message: str) -> None:
        """Add a message to the queue (called externally).
        
        If agent is sleeping, wake it up.
        """
        self._queue.append(message)
        
        # Wake the agent if sleeping
        if self._agentic_loop and self._agentic_loop.is_sleeping():
            print(f"[MessageModule] Waking agent due to new message: {message[:50]}...")
            self._agentic_loop.wake()
    
    def get_message(self) -> str:
        """Get the next message from the queue."""
        if not self._queue:
            return "No messages in queue."
        return self._queue.pop(0)
