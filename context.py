"""Context management - memory API client, message processing, and context building.

This module is purely responsible for:
- Talking to the Memory API (store/retrieve conversation context)
- Processing messages (reordering, truncation, sanitization)
- Building context from registered modules

It knows nothing about LLM calls, tool execution, or the agent loop.
"""

import json
import re
from datetime import datetime, timezone

import requests
from config import get


# =============================================================================
# Helpers
# =============================================================================

def _json_safe(obj):
    """Convert an object to JSON-safe Python types.
    
    Recursively converts pydantic models, dataclasses, etc. to plain dicts/lists.
    Handles Undefined and other non-serializable types.
    """
    if obj is None:
        return None
    
    # Handle pydantic Undefined explicitly
    try:
        from pydantic import Undefined
        if obj is Undefined:
            return None
    except ImportError:
        pass
    
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, list):
        return [_json_safe(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    # Handle pydantic models
    if hasattr(obj, 'model_dump'):
        return _json_safe(obj.model_dump())
    if hasattr(obj, '__dict__'):
        return _json_safe(obj.__dict__)
    # Fallback: convert to string
    return str(obj)


# =============================================================================
# Memory API Client
# =============================================================================

class MemoryClient:
    """Client for remote memory API - stores conversation context by session.
    
    Note: Memory API must be running for Core to function. If not available,
    Core will fail gracefully with clear error.
    """
    
    def __init__(self, base_url: str = None, session_id: str = None):
        self.base_url = base_url or get('memory_api.url')
        self.session_id = session_id
    
    def add_context(self, role: str, content: str, session: str = None,
                    tool_call_id: str = None, function: str = None) -> dict:
        """Add a context message to memory.
        
        Args:
            role: Message role (user, assistant, system, tool)
            content: Message content
            session: Session ID
            tool_call_id: Tool call ID for linking tool results to their request
            function: Function name (for tool results to store as proper property)
        """
        session = session or self.session_id
        payload = {
            "role": role,
            "content": content,
            "session": session,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if tool_call_id:
            payload["tool_call_id"] = tool_call_id
        if function:
            payload["function"] = function
        resp = requests.post(
            f"{self.base_url}/context",
            json=payload
        )
        resp.raise_for_status()
        return resp.json()
    
    def get_context(self, limit: int = 100, session: str = None) -> list[dict]:
        """Get conversation history from memory."""
        session = session or self.session_id
        resp = requests.get(
            f"{self.base_url}/context",
            params={"limit": limit, "session": session}
        )
        resp.raise_for_status()
        return resp.json().get("context", [])
    
    def delete_session(self, session: str = None) -> dict:
        """Delete all context for a session."""
        session = session or self.session_id
        resp = requests.delete(
            f"{self.base_url}/context",
            params={"session": session}
        )
        resp.raise_for_status()
        return resp.json()


# =============================================================================
# Context Manager
# =============================================================================

class ContextManager:
    """Handles all context/memory operations for the agent loop.

    Encapsulates:
    - Fetching history from Memory API
    - Building system prompt from context functions
    - Message processing (reorder, truncate, sanitize for LLM)
    - Storing messages to Memory API
    """

    def __init__(
        self,
        memory_url: str = None,
        tool_result_max_lines: int = 200,
        tool_result_char_per_line: int = 150,
    ):
        self._memory_url = memory_url or get('memory_api.url')
        self._tool_max_lines = tool_result_max_lines
        self._tool_char_per_line = tool_result_char_per_line

    @property
    def memory_client(self) -> MemoryClient:
        """Get or create a MemoryClient for this context manager."""
        return MemoryClient(base_url=self._memory_url)
    
    # -------------------------------------------------------------------------
    # Context building (from modules)
    # -------------------------------------------------------------------------
    
    def build_context_from_modules(self, registry) -> dict[str, str]:
        """Build context dict by calling all registered context functions."""
        return registry.build_context()
    
    def build_system_prompt(
        self,
        template: str,
        registry,
    ) -> str:
        """Build system prompt by replacing {tag} placeholders with context."""
        ctx = self.build_context_from_modules(registry)
        system = template
        for tag, content in ctx.items():
            placeholder = f"{{{tag}}}"
            system = system.replace(placeholder, content)
        return system
    
    # -------------------------------------------------------------------------
    # Message processing
    # -------------------------------------------------------------------------
    
    @staticmethod
    def reorder_messages(messages: list[dict]) -> list[dict]:
        """Reorder messages so tool results follow their assistant message.
        
        DEFENSIVE-ONLY: With proper storage ordering (assistant before tool result),
        this should rarely be needed. Kept as safety net for clock skew or edge cases.
        Also parses embedded [tool_calls]...[/tool_calls] in content back to proper field.
        """
        if not messages:
            return messages
        
        result = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            
            # Parse embedded tool_calls from content if present
            if msg.get('role') == 'assistant' and msg.get('content') and '[tool_calls]' in msg.get('content', ''):
                content = msg['content']
                tc_match = re.search(r'\[tool_calls\](.+?)\[/tool_calls\]', content)
                if tc_match:
                    try:
                        tool_calls = json.loads(tc_match.group(1))
                        msg['tool_calls'] = tool_calls
                        msg['content'] = re.sub(r'\[tool_calls\].+?\[/tool_calls\]\s*', '', content).strip()
                        if not msg['content']:
                            del msg['content']
                    except json.JSONDecodeError:
                        pass
            
            # If this is a tool message, find its matching assistant and insert after it
            if msg.get('role') == 'tool':
                tool_call_id = msg.get('tool_call_id', '')
                if tool_call_id:
                    inserted = False
                    for j, existing_msg in enumerate(result):
                        if existing_msg.get('role') == 'assistant':
                            tcs = existing_msg.get('tool_calls', [])
                            for tc in tcs:
                                if tc.get('id') == tool_call_id:
                                    result.insert(j + 1, msg)
                                    inserted = True
                                    break
                            if inserted:
                                break
                    if not inserted:
                        result.append(msg)
                else:
                    result.append(msg)
            else:
                result.append(msg)
            i += 1
        
        return result
    
    @staticmethod
    def truncate_tool_result(content: str, max_lines: int, char_per_line: int) -> str:
        """Truncate tool result content to a max number of lines.
        
        If content has newlines, truncate at max_lines lines.
        If content has no newlines, treat every char_per_line chars as a "virtual line".
        """
        if not content:
            return content
        
        if '\n' in content:
            lines = content.split('\n')
            if len(lines) <= max_lines:
                return content
            truncated = '\n'.join(lines[:max_lines])
            return truncated + f'\n[TRUNCATED: original had {len(lines)} lines]'
        else:
            virtual_lines = (len(content) + char_per_line - 1) // char_per_line
            if virtual_lines <= max_lines:
                return content
            max_chars = max_lines * char_per_line
            truncated = content[:max_chars]
            return truncated + f'[TRUNCATED: original had {len(content)} chars]'
    
    def prepare_messages_for_llm(
        self,
        history: list[dict],
        system_template: str,
        registry,
        include_timestamp: bool = None,
    ) -> tuple[list[dict], str]:
        """Build messages for LLM from history, including system prompt.
        
        Args:
            history: Message history from memory API
            system_template: System prompt template with {tag} placeholders
            registry: Module registry for building context
            include_timestamp: Override for timestamp prefix (default from config)
        
        Returns (api_messages, system_prompt) where api_messages has system
        prompt prepended and messages are processed (reordered, truncated).
        """
        # Check config for timestamp preference (default to False if not set)
        if include_timestamp is None:
            include_timestamp = get('memory_api.include_timestamp', False)
        
        # Build api_messages from history (filter internal fields, optionally add timestamp)
        api_messages = []
        for msg in history:
            msg_copy = {k: v for k, v in msg.items() if k not in ('id', 'created_at')}
            
            # Prepend timestamp to content if enabled and created_at is present
            if include_timestamp and msg.get('created_at') and msg_copy.get('content'):
                try:
                    ts = datetime.fromisoformat(msg['created_at'].replace('Z', '+00:00'))
                    timestamp_str = ts.strftime('%Y-%m-%d %H:%M')
                    msg_copy['content'] = f"[{timestamp_str}] {msg_copy['content']}"
                except (ValueError, TypeError):
                    pass  # Skip timestamp if parsing fails
            
            api_messages.append(msg_copy)
        
        # Reorder: ensure tool results follow their assistant message
        api_messages = self.reorder_messages(api_messages)
        
        # Truncate tool result content to prevent context overflow
        for msg in api_messages:
            if msg.get('role') == 'tool' and msg.get('content'):
                msg['content'] = self.truncate_tool_result(
                    msg['content'],
                    self._tool_max_lines,
                    self._tool_char_per_line
                )
        
        # Add system prompt at the front
        system = self.build_system_prompt(system_template, registry)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})
        
        return api_messages, system
    
    def sanitize_messages_for_llm(self, api_messages: list[dict]) -> list[dict]:
        """Sanitize messages for LLM API compatibility.

        Ensures tool result messages have the correct structure:
        - role: "tool" (NOT "function" - function role is for calling, not results)
        - tool_call_id: links result to the original tool call request
        - content: the result string
        - (optional) name: extracted from stored 'function' property if present
        """
        api_messages = _json_safe(api_messages)

        for msg in api_messages:
            if msg.get('role') == 'tool':
                # Keep role as "tool" — standard OpenAI format for tool results
                # Extract function name from stored 'function' property into 'name' field
                if msg.get('function'):
                    msg['name'] = msg['function']
                    del msg['function']

        return api_messages
