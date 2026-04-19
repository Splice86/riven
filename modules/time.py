"""Time module - provides current time as both context and called function."""

from datetime import datetime
from modules import CalledFn, ContextFn, Module


# --- Called function ---

async def get_time() -> str:
    """Get the current time as a formatted string.
    
    Returns:
        Current time in YYYY-MM-DD HH:MM:SS format.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --- Context function ---

def get_time_context() -> str:
    """Return current time for context injection."""
    return f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


# --- Module ---

def get_module() -> Module:
    from modules import Module, CalledFn, ContextFn
    
    return Module(
        name="time",
        called_fns=[
            CalledFn(
                name="get_time",
                description="Get the current time. Call this when the user asks for the time.",
                parameters={"type": "object", "properties": {}, "required": []},
                fn=get_time,
                # No timeout = pulls from shard config.yaml tool_timeout
            )
        ],
        context_fns=[
            ContextFn(
                tag="time",  # Will replace {time} in system prompt
                fn=get_time_context,
            )
        ],
    )
