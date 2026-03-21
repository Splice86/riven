"""Time module for riven - provides current time context."""

from datetime import datetime


def get_current_time() -> str:
    """Get the current time.
    
    Returns:
        Current ISO format timestamp
    """
    return datetime.now().isoformat()


def get_time_module():
    """Get the time module.
    
    Returns:
        Time Module with context and tag
    """
    from modules import Module
    
    return Module(
        name="time",
        get_context=get_current_time,
        tag="time"
    )
