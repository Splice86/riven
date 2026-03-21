"""Messaging module for riven - handles user messages."""

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Message:
    """A message in the queue."""
    content: str
    sender: str = "user"
    recipient: str = "user"
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class MessageQueue:
    """Async message queue for agent communication."""
    
    def __init__(self):
        self._inbox: deque[Message] = deque()
        self._outbox: deque[Message] = deque()
        self._lock = asyncio.Lock()
        self._outbox_callbacks = []
    
    async def put(self, content: str, sender: str = "user") -> None:
        """Add a message to the inbox."""
        async with self._lock:
            self._inbox.append(Message(content=content, sender=sender))
    
    async def get(self) -> Message | None:
        """Get the next message from inbox (non-blocking)."""
        async with self._lock:
            if self._inbox:
                return self._inbox.popleft()
            return None
    
    async def peek(self) -> Message | None:
        """Peek at next message without removing."""
        async with self._lock:
            if self._inbox:
                return self._inbox[0]
            return None
    
    async def send(self, content: str, recipient: str = "user") -> None:
        """Add a message to the outbox (LLM responding)."""
        async with self._lock:
            self._outbox.append(Message(content=content, sender="agent", recipient=recipient))
            # Notify callbacks
            for cb in self._outbox_callbacks:
                await cb(content)
    
    def on_outbox(self, callback):
        """Register callback for outbox messages."""
        self._outbox_callbacks.append(callback)
    
    async def get_outbox(self) -> list[Message]:
        """Get all outbox messages and clear."""
        async with self._lock:
            messages = list(self._outbox)
            self._outbox.clear()
            return messages
    
    async def outbox_count(self) -> int:
        """Get count of waiting outbox messages."""
        async with self._lock:
            return len(self._outbox)
    
    async def inbox_count(self) -> int:
        """Get count of waiting inbox messages."""
        async with self._lock:
            return len(self._inbox)


# Global message queue
queue = MessageQueue()


async def check_messages() -> str:
    """Check if there are waiting messages in the queue.
    
    Returns:
        Number of waiting messages or 'No messages waiting'
    """
    count = await queue.inbox_count()
    if count == 0:
        return "No messages waiting"
    return f"{count} message(s) waiting"


async def get_message() -> str:
    """Get the next message from the queue.
    
    Returns:
        The message content or 'No messages in queue'
    """
    msg = await queue.get()
    if msg is None:
        return "No messages in queue"
    return f"[{msg.sender}]: {msg.content}"


async def send_message(message: str) -> str:
    """Send a message to the user.
    
    Args:
        message: The message to send to the user.
        
    Returns:
        Confirmation that message was sent.
    """
    await queue.send(message)
    return f"Message sent to user: {message}"


def get_messaging_module():
    """Get the messaging module.
    
    Returns:
        Messaging Module with functions and enrollment
    """
    from modules import Module
    
    return Module(
        name="messaging",
        enrollment=lambda: None,  # Setup can be added here
        functions={
            "check_messages": check_messages,
            "get_message": get_message,
            "send_message": send_message
        }
    )
