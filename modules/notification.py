"""
Notification module - handles incoming notifications.
"""

from queue import Queue, Empty
from typing import Callable, Any
from modules.base import Module


class NotificationModule(Module):
    """Notification module - handles incoming notifications."""
    
    TAG = "notifications"  # Tag for notifications info
    
    def __init__(self):
        self._queue: Queue = Queue()
    
    def send(self, notification: Any) -> None:
        """Send a notification to this module.
        
        Can be called from any thread.
        """
        self._queue.put(notification)
    
    def _get_notifications(self) -> list:
        """Get all pending notifications without removing them."""
        notifications = []
        while True:
            try:
                notifications.append(self._queue.get_nowait())
            except Empty:
                break
        # Put them back
        for n in notifications:
            self._queue.put(n)
        return notifications
    
    def info(self) -> str | None:
        """Return notification info."""
        notifications = self._get_notifications()
        if not notifications:
            return None
        
        return f"{len(notifications)} pending notification(s)"
    
    def definitions(self) -> list[dict]:
        return []  # No functions exposed - notifications come from external sources
    
    def get_functions(self) -> dict[str, Callable]:
        return {}  # No callable functions
