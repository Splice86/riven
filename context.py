"""Context system for agent conversations."""

from dataclasses import dataclass, field
from typing import Any
from datetime import datetime


@dataclass
class Message:
    """A single message in the conversation."""
    role: str  # "user", "assistant", "system", "tool"
    content: str
    tool_name: str | None = None  # For tool results
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            role=data["role"],
            content=data["content"],
            tool_name=data.get("tool_name"),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


@dataclass
class Context:
    """Conversation context that supplies the LLM with history."""
    
    system_prompt: str = ""
    _system_prompt_template: str = ""  # Original with {{tags}}
    messages: list[Message] = field(default_factory=list)
    max_messages: int = 100  # Limit to prevent unbounded growth
    
    def set_system_prompt(self, prompt: str) -> None:
        """Set or update the system prompt.
        
        Only updates template if not already set.
        """
        self.system_prompt = prompt
        # Store original template if it has tags and template not already set
        if "{{" in prompt and not self._system_prompt_template:
            self._system_prompt_template = prompt
    
    def get_system_prompt_template(self) -> str:
        """Get the original template with tags."""
        return self._system_prompt_template or self.system_prompt
    
    def apply_tag_replacements(self, replacements: list[tuple[str, str]]) -> str:
        """Apply tag replacements to the system prompt template.
        
        Args:
            replacements: List of (tag, data) tuples
            
        Returns:
            System prompt with tags replaced
        """
        prompt = self.get_system_prompt_template()
        for tag, data in replacements:
            placeholder = f"{{{{{tag}}}}}"
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, str(data))
        return prompt
    
    def add_user(self, content: str) -> None:
        """Add a user message."""
        self.messages.append(Message(role="user", content=content))
        self._trim()
    
    def add_assistant(self, content: str) -> None:
        """Add an assistant message."""
        self.messages.append(Message(role="assistant", content=content))
        self._trim()
    
    def add_tool_result(self, tool_name: str, content: str) -> None:
        """Add a tool result message."""
        self.messages.append(Message(role="tool", content=content, tool_name=tool_name))
        self._trim()
    
    def add_system(self, content: str) -> None:
        """Add a system message."""
        self.messages.append(Message(role="system", content=content))
        self._trim()
    
    def _trim(self) -> None:
        """Trim oldest messages if over limit."""
        if len(self.messages) > self.max_messages:
            excess = len(self.messages) - self.max_messages
            self.messages = self.messages[excess:]
    
    def get_messages_for_llm(self) -> list[dict]:
        """Get messages in format for LLM API."""
        return [{"role": m.role, "content": m.content} for m in self.messages]
    
    def get_message_count(self) -> int:
        """Get count of messages."""
        return len(self.messages)
    
    def build_prompt(self, current_prompt: str, system_prompt: str | None = None) -> str:
        """Build full prompt including conversation history.
        
        Args:
            current_prompt: The current user prompt to include.
            system_prompt: Optional system prompt to use (default: self.system_prompt)
            
        Returns:
            Full prompt with history prepended.
        """
        # Use provided system_prompt or default to self.system_prompt
        sys_prompt = system_prompt if system_prompt is not None else self.system_prompt
        
        messages = self.get_messages_for_llm()
        
        if not messages:
            return current_prompt
        
        history_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        return f"Previous conversation:\n{history_text}\n\nCurrent: {current_prompt}"
    
    def clear(self) -> None:
        """Clear all messages but keep system prompt."""
        self.messages.clear()
    
    def to_dict(self) -> dict:
        """Serialize to dict for storage."""
        return {
            "system_prompt": self.system_prompt,
            "messages": [m.to_dict() for m in self.messages],
            "max_messages": self.max_messages
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Context":
        """Deserialize from dict."""
        ctx = cls(
            system_prompt=data.get("system_prompt", ""),
            max_messages=data.get("max_messages", 100)
        )
        ctx.messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return ctx
    
    def summary(self) -> str:
        """Get a summary of the context."""
        roles = {}
        for m in self.messages:
            roles[m.role] = roles.get(m.role, 0) + 1
        return f"Context({len(self.messages)} msgs: {roles})"
