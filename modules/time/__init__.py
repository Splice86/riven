"""Time module - provides current time as dynamic context only.

No callable functions - time is injected via {time} tag at bottom of prompt.
"""

from datetime import datetime
from modules import ContextFn, Module


def _time_help() -> str:
    """Static tool documentation."""
    return """## Time (Help)

The time module provides current time automatically. No tool calls needed —
the current timestamp is injected into context on every response."""


def _time_context() -> str:
    """Dynamic context - current time. Changes every call."""
    return f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


def get_module() -> Module:
    return Module(
        name="time",
        called_fns=[],
        context_fns=[
            ContextFn(tag="time_help", fn=_time_help, static=True),
            ContextFn(tag="time", fn=_time_context),
        ],
    )
