"""Context management - memory API client, message processing, and context building.

This module is purely responsible for:
- Talking to the Memory API (store/retrieve conversation context)
- Processing messages (reordering, truncation, sanitization)
- Building context from registered modules

It knows nothing about LLM calls, tool execution, or the agent loop.
"""

import json
import os
from datetime import datetime, timezone
from typing import Callable

import requests
from config import get


# =============================================================================
# Constants
# =============================================================================




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
        self.session_id = session_id
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
        memory_url: str = MEMORY_API_URL,
        tool_result_max_lines: int = 200,
        tool_result_char_per_line: int = 150,
        debug_dir: str = None,
        debug_snapshots: bool = False,
    ):
        self._memory_url = memory_url or get('memory_api.url')
        self._tool_max_lines = tool_result_max_lines
        self._tool_char_per_line = tool_result_char_per_line
        self._debug_dir = debug_dir
        self._debug_snapshots = debug_snapshots
        self._debug_call_count = 0
    
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
                import re
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
    ) -> tuple[list[dict], str]:
        """Build messages for LLM from history, including system prompt.
        
        Returns (api_messages, system_prompt) where api_messages has system
        prompt prepended and messages are processed (reordered, truncated).
        """
        # Build api_messages from history (filter internal fields)
        api_messages = [
            {k: v for k, v in msg.items() if k not in ('id', 'created_at')}
            for msg in history
        ]
        
        # Reorder: ensure tool results follow their assistant message
        api_messages = self.reorder_messages(api_messages)
        
        # Truncate tool result content to prevent context overflow
        for msg in api_messages:
            if msg.get('role') == 'tool' and msg.get('content'):
                original_len = len(msg['content'])
                msg['content'] = self.truncate_tool_result(
                    msg['content'],
                    self._tool_max_lines,
                    self._tool_char_per_line
                )
                if len(msg['content']) < original_len:
                    pass  # Truncation happened silently
        
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
                # Legacy: if content is "func_name: result" format, extract it
                # (new storage uses 'function' property instead)
                content = msg.get('content', '')
                if msg.get('name') is None and ':' in content:
                    func_name, _, rest = content.partition(':')
                    msg['name'] = func_name.strip()
                    msg['content'] = rest.strip()
        
        return api_messages
    
    # -------------------------------------------------------------------------
    # Debug helpers
    # -------------------------------------------------------------------------
    
    def debug_save(
        self,
        stage: str,
        system_prompt: str,
        api_messages: list[dict],
        context_data: dict = None,
    ) -> None:
        """Save debug dump of context before LLM call."""
        if not self._debug_dir:
            return
        
        self._debug_call_count += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"call_{self._debug_call_count:03d}_{stage}_{timestamp}.json"
        
        os.makedirs(self._debug_dir, exist_ok=True)
        filepath = os.path.join(self._debug_dir, filename)
        
        debug_data = {
            "timestamp": timestamp,
            "stage": stage,
            "call_number": self._debug_call_count,
            "context_data": context_data or {},
            "system_prompt": system_prompt,
            "messages": api_messages,
        }
        
        with open(filepath, 'w') as f:
            json.dump(debug_data, f, indent=2, default=str)
    
    def save_context_snapshot(
        self,
        raw_context: list[dict],
        label: str,
        session_id: str = None,
    ) -> None:
        """Save raw context snapshot to a file for debugging."""
        debug_dir = self._debug_dir or 'context_debug'
        os.makedirs(debug_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{label}_{timestamp}.json"
        filepath = os.path.join(debug_dir, filename)
        
        snapshot = {
            "timestamp": timestamp,
            "label": label,
            "session_id": session_id,
            "message_count": len(raw_context),
            "messages": raw_context,
        }
        
        with open(filepath, 'w') as f:
            json.dump(snapshot, f, indent=2, default=str)
