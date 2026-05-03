"""Context management — message processing and context building.

This module is purely responsible for:
- Processing messages (reorder, truncate, sanitize for LLM)
- Building context from registered modules

Storage is handled by db.ContextDB. This module knows nothing about LLM calls,
tool execution, or the agent loop.
"""

import json
import re
import time
from datetime import datetime, timezone

# High-level debug flag
DEBUG_HANG = True  # Enable for lock-up debugging

def _debug(step: str, session_id: str = None) -> None:
    """Print timestamped debug messages to trace execution flow."""
    if not DEBUG_HANG:
        return
    ts = time.time()
    sid = f"[{session_id[:8]}]" if session_id else "[--------]"
    print(f"[DEBUG {ts:.3f}] {sid} {step}", flush=True)


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
# Context Manager
# =============================================================================

class ContextManager:
    """Handles message processing and context building for the agent loop.

    Encapsulates:
    - Building system prompt from context functions
    - Message processing (reorder, truncate, sanitize for LLM)

    Storage is handled by db.ContextDB — this class only processes messages.
    """

    def __init__(
        self,
        tool_result_max_lines: int = 200,
        tool_result_char_per_line: int = 150,
    ):
        self._tool_max_lines = tool_result_max_lines
        self._tool_char_per_line = tool_result_char_per_line
    
    # -------------------------------------------------------------------------
    # Context building (from modules)
    # -------------------------------------------------------------------------
    
    def build_context_from_modules(self, registry) -> dict[str, str]:
        """Build context dict by calling all registered context functions."""
        _debug("ContextManager.build_context_from_modules: START")
        ctx = registry.build_context()
        _debug(f"ContextManager.build_context_from_modules: DONE, {len(ctx)} tags")
        return ctx
    
    def build_system_prompt(
        self,
        template: str,
        registry,
    ) -> str:
        """Build system prompt by replacing {tag} placeholders with context."""
        _debug("ContextManager.build_system_prompt: START")
        ctx = self.build_context_from_modules(registry)
        system = template
        replacements = 0
        for tag, content in ctx.items():
            placeholder = f"{{{tag}}}"
            if placeholder in system:
                _debug(f"ContextManager.build_system_prompt: replaced {{{tag}}}")
                replacements += 1
            system = system.replace(placeholder, content)
        unreplaced = [m.group(1) for m in __import__('re').finditer(r'\{(\w+)\}', system)]
        if unreplaced:
            _debug(f"ContextManager.build_system_prompt: UNREPLACED placeholders: {unreplaced}")
        _debug(f"ContextManager.build_system_prompt: DONE ({replacements} replaced, system len={len(system)})")
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
            original_content = msg.get('content', '<KEY_MISSING>')
            
            # Parse embedded tool_calls from content if present
            if msg.get('role') == 'assistant' and msg.get('content') and '[tool_calls]' in msg.get('content', ''):
                content = msg['content']
                tc_match = re.search(r'\[tool_calls\](.+?)\[/tool_calls\]', content)
                if tc_match:
                    try:
                        tool_calls = json.loads(tc_match.group(1))
                        msg['tool_calls'] = tool_calls
                        msg['content'] = re.sub(r'\[tool_calls\].+?\[/tool_calls\]\s*', '', content).strip()
                        # CRITICAL: never send an assistant message to LLM with no content and no text.
                        # If content is empty after parsing (tool-call-only response), keep content as ''
                        # rather than deleting it — MiniMax rejects messages with no content field.
                        if not msg['content']:
                            msg['content'] = ''
                        _debug(f"reorder: parsed [tool_calls] from msg[{i}] content={repr(original_content[:80])} -> content_after={repr(msg['content'][:80])} tool_calls_count={len(tool_calls)}", None)
                    except json.JSONDecodeError as e:
                        _debug(f"reorder: FAILED to parse [tool_calls] from msg[{i}]: {e}", None)
                        pass
            
            # If this is a tool message, find its matching assistant and insert after it
            if msg.get('role') == 'tool':
                tool_call_id = msg.get('tool_call_id', '')
                content_after = msg.get('content', '<KEY_MISSING>')
                _debug(f"reorder: msg[{i}] is tool role tool_call_id={tool_call_id[:16] if tool_call_id else 'NONE'} content={repr(content_after[:80])}", None)
                if tool_call_id:
                    inserted = False
                    for j, existing_msg in enumerate(result):
                        if existing_msg.get('role') == 'assistant':
                            tcs = existing_msg.get('tool_calls', [])
                            for tc in tcs:
                                if tc.get('id') == tool_call_id:
                                    result.insert(j + 1, msg)
                                    inserted = True
                                    _debug(f"reorder: inserted msg[{i}] tool after assistant msg[{j}] (matched tc id)", None)
                                    break
                            if inserted:
                                break
                    if not inserted:
                        result.append(msg)
                        _debug(f"reorder: msg[{i}] tool NOT matched to any assistant, appended at end", None)
                else:
                    result.append(msg)
            else:
                result.append(msg)
            i += 1
        
        _debug(f"reorder: DONE {len(messages)} -> {len(result)} msgs, final roles={[m.get('role') for m in result]}", None)
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
        
        Args:
            history: Message history from db.ContextDB
            system_template: System prompt template with {tag} placeholders
            registry: Module registry for building context
        
        Returns (api_messages, system_prompt) where api_messages has system
        prompt prepended and messages are processed (reordered, truncated).
        """
        _debug("ContextManager.prepare_messages_for_llm: START")
        
        # Build api_messages from history (filter internal fields)
        api_messages = []
        for msg in history:
            msg_copy = {k: v for k, v in msg.items() if k not in ('id', 'created_at', 'token_count', 'session_id')}
            api_messages.append(msg_copy)
        
        _debug(f"ContextManager.prepare_messages_for_llm: {len(api_messages)} history messages:")
        for i, m in enumerate(api_messages):
            role = m.get('role', '?')
            content = m.get('content', '<KEY_MISSING>')
            has_tc = bool(m.get('tool_calls'))
            tc_id = m.get('tool_call_id', '')
            func_name = m.get('function', '')
            _debug(f"  raw[{i}] role={role} has_content_key={'content' in m} content_len={len(content) if isinstance(content, str) else 'N/A'} has_tc={has_tc} tool_call_id={tc_id[:16] if tc_id else 'NONE'} function={func_name}", None)
            _debug(f"    content: {repr(content[:150]) if isinstance(content, str) else '<NOT_STRING>'}", None)
        
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
        _debug("ContextManager.prepare_messages_for_llm: building system prompt")
        system = self.build_system_prompt(system_template, registry)
        _debug(f"ContextManager.prepare_messages_for_llm: system prompt length={len(system) if system else 0}", None)
        if system and system.strip():
            api_messages.insert(0, {"role": "system", "content": system})
        else:
            _debug("ContextManager.prepare_messages_for_llm: WARNING - system prompt is EMPTY, NOT inserting", None)
        
        _debug(f"ContextManager.prepare_messages_for_llm: DONE ({len(api_messages)} total messages, system len={len(system)})")
        return api_messages, system
    
    def sanitize_messages_for_llm(self, api_messages: list[dict]) -> list[dict]:
        """Sanitize messages for LLM API compatibility.

        Ensures tool result messages have the correct structure:
        - role: "tool" (NOT "function" - function role is for calling, not results)
        - tool_call_id: links result to the original tool call request
        - content: the result string
        - (optional) name: extracted from stored 'function' property if present

        Also guards against empty content on any message type (MiniMax rejects these
        with "Input is a zero-length, empty document").
        """
        api_messages = _json_safe(api_messages)

        for i, msg in enumerate(api_messages):
            role = msg.get('role', 'unknown')
            had_tool_calls = bool(msg.get('tool_calls'))
            original_content = msg.get('content', '<KEY_MISSING>')
            
            if msg.get('role') == 'tool':
                # Keep role as "tool" — standard OpenAI format for tool results
                # Extract function name from stored 'function' property into 'name' field
                if msg.get('function'):
                    msg['name'] = msg['function']
                    del msg['function']

            # Guard: ensure no message ever has empty/missing content
            # MiniMax returns 400 "zero-length document" if content is "" or absent for any role
            content = msg.get('content')
            if content is None:
                _debug(f"sanitize[{i}]: [{role}] content=None, fixing to '(no output)' (original: {repr(original_content)[:100]})", None)
                msg['content'] = '(no output)'
            elif content == '':
                _debug(f"sanitize[{i}]: [{role}] content='', fixing to '(no output)' (has_tc={had_tool_calls})", None)
                msg['content'] = '(no output)'
            elif not isinstance(content, str):
                # Handle non-string content (list, dict, etc.) by converting to string
                _debug(f"sanitize[{i}]: [{role}] content type={type(content).__name__}, converting to string", None)
                msg['content'] = str(content)
            else:
                _debug(f"sanitize[{i}]: [{role}] content OK ({len(content)} chars)", None)

        return api_messages
