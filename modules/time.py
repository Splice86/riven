"""Time module - provides current time as dynamic context only.

No callable functions - time is injected via {time} tag at bottom of prompt.
"""

from datetime import datetime
from modules import ContextFn, Module


# --- Context function ---

def _time_context() -> str:
    """Dynamic context - current time. Changes every call."""
    return f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


# --- Module ---

def get_module() -> Module:
    return Module(
        name="time",
        called_fns=[],  # No callable functions - time is context only
        context_fns=[
            ContextFn(tag="time", fn=_time_context),
        ],
    )
