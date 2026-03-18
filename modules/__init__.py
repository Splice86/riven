"""Module system for Agentic Loop.

A module is a class with:
- info() -> str | dict | None: returns data to inject into prompt
- definitions() -> list[dict]: returns tool definitions for LLM
- Your functions: actual callable methods

All available modules:
- ClockModule: current time
- PrintModule: print messages
- MessageModule: message queue
- ExitModule: exit signal
- SleepModule: sleep/wake
- NotificationModule: notifications
"""

# Re-export the base class
from modules.base import Module

# Import all modules
from modules.clock import ClockModule
from modules.print import PrintModule
from modules.message import MessageModule
from modules.exit import ExitModule
from modules.sleep import SleepModule
from modules.notification import NotificationModule

__all__ = [
    "Module",
    "ClockModule", 
    "PrintModule", 
    "MessageModule", 
    "ExitModule",
    "SleepModule", 
    "NotificationModule",
]
