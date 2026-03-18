"""
Module system for Agentic Loop.

A module is a class with:
- info() -> str | dict | None: returns data to inject into prompt
- definitions() -> list[dict]: returns tool definitions for LLM
- Your functions: actual callable methods
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, List
from queue import Queue, Empty


class Module(ABC):
    """Base class for all modules."""

    # Subclasses should override these
    TAG: str = ""  # Tag name for replacing {{tag}} in prompt (e.g., "time")

    
    @abstractmethod
    def info(self) -> str | dict | None:
        """Return data to inject into the main prompt as {{TAG}}.
        
        Return a string that will replace {{TAG}} in the prompt.
        Can return None if no info to inject.
        """
        pass

    @abstractmethod
    def definitions(self) -> list[dict]:
        """Return list of function definitions for the LLM.
        
        Each dict should have:
        - name: str - function name
        - description: str - what it does
        - parameters: dict (optional) - schema for args
        - tag: str (optional) - the prompt tag this module provides (e.g., "time")
        
        Return empty list [] if no functions to expose.
        """
        pass

    def get_functions(self) -> dict[str, Callable]:
        """Return dict mapping function names to callables.
        
        Override this to expose functions to the loop.
        Default returns all public methods (not info/definitions).
        """
        functions = {}
        
        for attr_name in dir(self):
            if attr_name.startswith('_'):
                continue
            if attr_name in ('info', 'definitions', 'get_functions'):
                continue
            
            attr = getattr(self, attr_name)
            if callable(attr):
                functions[attr_name] = attr
        
        return functions


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


class PrintModule(Module):
    """Print module - allows LLM to print messages to terminal."""

    def info(self) -> None:
        """No info to inject."""
        return None

    def definitions(self) -> list[dict]:
        """Define the print function."""
        return [
            {
                "name": "print",
                "description": "Print a message to the terminal output",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message to print"
                        }
                    },
                    "required": ["message"]
                }
            }
        ]

    def get_functions(self) -> dict[str, Callable]:
        """Return the print function."""
        return {"print": self.print}

    def print(self, message: str) -> str:
        """Print a message to terminal."""
        print(f"[Agent] {message}")
        return f"Printed: {message}"


class MessageModule(Module):
    """Message queue module - allows external messages to be sent to the agent."""
    
    TAG = "messages"  # Tag for {{messages}} replacement
    
    def __init__(self):
        self._queue: list[str] = []
    
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
        """Add a message to the queue (called externally)."""
        self._queue.append(message)
    
    def get_message(self) -> str:
        """Get the next message from the queue."""
        if not self._queue:
            return "No messages in queue."
        return self._queue.pop(0)


class ExitModule(Module):
    """Exit module - allows LLM to signal shutdown."""
    
    def __init__(self, exit_callback=None):
        self._exit_callback = exit_callback
    
    def info(self) -> str | None:
        return "Use exit() when the task is complete."
    
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
                "description": "Put the agent to sleep for a specified duration in seconds. The agent will automatically wake up after the duration.",
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


class NotificationModule(Module):
    """Notification module - handles incoming notifications."""
    
    def __init__(self):
        self._queue: Queue = Queue()
    
    def send(self, notification: Any) -> None:
        """Send a notification to this module.
        
        Can be called from any thread.
        """
        self._queue.put(notification)
    
    def info(self) -> str | None:
        """Return notification info."""
        # Peek at notifications without removing them
        notifications = self._get_notifications()
        if not notifications:
            return None
        
        # Return actual notification count
        return f"{len(notifications)} pending notification(s)"
    
    def definitions(self) -> list[dict]:
        """Define function to get notifications."""
        return [
            {
                "name": "get_notifications",
                "description": "Get and clear all pending notifications",
            }
        ]
    
    def get_functions(self) -> dict[str, Callable]:
        return {"get_notifications": self.get_notifications}
    
    def _get_notifications(self) -> List[Any]:
        """Get all notifications from the queue without removing them."""
        notifications = []
        while True:
            try:
                notification = self._queue.get_nowait()
                notifications.append(notification)
                self._queue.put(notification)  # Put it back
            except Empty:
                break
        return notifications
    
    def get_notifications(self) -> str:
        """Get and clear all pending notifications."""
        notifications = []
        while True:
            try:
                notification = self._queue.get_nowait()
                notifications.append(notification)
            except Empty:
                break
        
        if not notifications:
            return "No notifications"
        
        # Format as string
        lines = [f"- {n}" for n in notifications]
        return "\n".join(lines)
