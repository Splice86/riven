"""The core loop - simple, direct LLM calls with function execution.

Architecture:
- Memory API: stores conversation history (user, assistant, tool messages)
- Core: only takes session_id, gets history from Memory, runs loop, stores responses to Memory
- Harness: orchestrates - stores user message to Memory before calling Core

Flow:
  prompt -> memory api + activate core with session ID
  -> context built from memory API
  -> thinking
  -> add context
  -> tool call
  -> add context
  -> rebuild context in core
  -> think
  -> add context
  -> final output
  -> add to context
"""

import asyncio
import inspect
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, AsyncIterator

from openai import AsyncOpenAI
from modules import registry, Module, CalledFn, ContextFn, _session_id

logger = logging.getLogger(__name__)


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
    
    # Handle pydantic Undefined explicitly - it serializes as Undefined type
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

MEMORY_API_URL = os.environ.get('MEMORY_API_URL', 'http://127.0.0.1:8030') #USER: Make sure this pulls from the config system


class MemoryClient:
    """Client for remote memory API - stores conversation context by session.
    
    Note: Memory API must be running for Core to function. If not available,
    Core will fail gracefully with clear error.
    """
    
    def __init__(self, base_url: str = MEMORY_API_URL, session_id: str = None):
        self.base_url = base_url
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
        import requests
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
        import requests
        session = session or self.session_id
        resp = requests.get(
            f"{self.base_url}/context",
            params={"limit": limit, "session": session}
        )
        resp.raise_for_status()
        context = resp.json().get("context", [])
        
        # DEBUG: Log context to file with timestamp
        debug_dir = os.environ.get('DEBUG_CONTEXT_DIR', '/home/david/Projects/riven_projects/riven_core/context_logs')
        os.makedirs(debug_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"get_context_{ts}.json"
        filepath = os.path.join(debug_dir, filename)
        with open(filepath, 'w') as f:
            json.dump({
                "timestamp": ts,
                "session": session,
                "count": len(context),
                "messages": context,
            }, f, indent=2, default=str)
        
        return context


# =============================================================================
# Function - plain function descriptor
# =============================================================================

@dataclass
class Function:
    """A callable function exposed to the LLM."""
    name: str
    description: str
    parameters: dict  # JSON schema
    fn: Callable
    timeout: float = 20.0

    @classmethod
    def from_callable(cls, fn: Callable, timeout: float = 20.0) -> "Function":
        """Create a Function from a plain callable."""
        name = fn.__name__
        desc = (fn.__doc__ or "").strip()
        if desc:
            # Take first paragraph (not just first line)
            paragraphs = desc.split("\n\n")
            desc = paragraphs[0].replace("\n", " ")

        sig = inspect.signature(fn)
        props = {}
        required = []

        for pname, param in sig.parameters.items():
            if pname.startswith("_"):
                continue

            param_type = "string"
            if param.annotation is not inspect.Parameter.empty:
                if param.annotation in (int,):
                    param_type = "integer"
                elif param.annotation in (float,):
                    param_type = "number"
                elif param.annotation in (bool,):
                    param_type = "boolean"

            # Try to get param description from docstring
            param_desc = ""
            if fn.__doc__:
                doc_lines = fn.__doc__.split("\n")
                for line in doc_lines:
                    if pname in line and ":" in line:
                        param_desc = line.split(":", 1)[1].strip()
                        break

            props[pname] = {"type": param_type}
            if param_desc:
                props[pname]["description"] = param_desc
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        # Only include 'required' if there are actually required params
        schema = {"type": "object", "properties": props}
        if required:
            schema["required"] = required
        return cls(name=name, description=desc, parameters=schema, fn=fn, timeout=timeout)


# =============================================================================
# Result types
# =============================================================================

@dataclass
class FunctionCall:
    """A parsed function call from the LLM response."""
    id: str
    name: str
    arguments: dict


@dataclass
class FunctionResult:
    """Result of executing a function."""
    call_id: str
    name: str
    content: str
    error: str | None = None


# =============================================================================
# The Core Loop
# =============================================================================

class Core:
    """Pure agentic loop.

    Takes a shard config that describes:
    - System prompt template (with context tags like {time})
    - Modules to load
    - Memory settings

    And an LLM config dict:
    - url, model, api_key, timeout

    Session ID is passed per-call and automatically available to all
    module functions via context_var.
    
    IMPORTANT: Memory API must be running. User's prompt should be stored
    to Memory API BEFORE calling run_stream(). This method only takes session_id.
    """

    def __init__(
        self,
        shard: dict,  # Shard config dict (tools, system, memory)
        llm: dict = None,  # LLM config dict with url, model, api_key, timeout
        max_function_calls: int = 20,
        tool_timeout: float = None,  # Override from shard if not provided
    ):
        # LLM settings from explicit config (not from shard)
        self._llm_url = llm.get('url', 'http://127.0.0.1:8000/v1') if llm else 'http://127.0.0.1:8000/v1'
        self._llm_model = llm.get('model', 'MiniMax-M2.7') if llm else 'MiniMax-M2.7'
        self._llm_api_key = llm.get('api_key', 'sk-dummy') if llm else 'sk-dummy'
        
        # Shard settings
        self._system_template = shard.get('system', '')
        self._module_names = shard.get('modules', [])
        self._max_function_calls = max_function_calls
        self._tool_timeout = shard.get('tool_timeout', tool_timeout or 20.0)
        self._cancelled = False
        self._client = AsyncOpenAI(base_url=self._llm_url, api_key=self._llm_api_key)

        # Memory API settings from shard
        memory_api = shard.get('memory_api', {})
        self._memory_url = memory_api.get('url', MEMORY_API_URL)

        # Tool result truncation settings from shard
        self._tool_max_lines = shard.get('tool_result_max_lines', 200)
        self._tool_char_per_line = shard.get('tool_result_char_per_line', 150)

        # Debug settings
        self._debug_dir = shard.get('debug_dir')
        self._debug_snapshots = shard.get('debug_snapshots', False)
        self._debug_call_count = 0

        # Register modules from shard config
        self._load_modules()

    @staticmethod
    def _truncate_tool_result(content: str, max_lines: int, char_per_line: int) -> str:
        """Truncate tool result content to a max number of lines.
        
        If content has newlines, truncate at max_lines lines.
        If content has no newlines, treat every char_per_line chars as a "virtual line".
        
        Args:
            content: The tool result content
            max_lines: Maximum lines to keep (200 default)
            char_per_line: Chars per virtual line when no newlines (150 default)
        
        Returns:
            Truncated content with "[TRUNCATED]" marker if cut
        """
        if not content:
            return content
        
        # Check if content has actual newlines
        if '\n' in content:
            lines = content.split('\n')
            if len(lines) <= max_lines:
                return content
            # Truncate at max_lines
            truncated = '\n'.join(lines[:max_lines])
            return truncated + '\n[TRUNCATED: original had {0} lines]'.format(len(lines))
        else:
            # No newlines - treat char_per_line as a virtual line
            virtual_lines = (len(content) + char_per_line - 1) // char_per_line
            if virtual_lines <= max_lines:
                return content
            # Truncate at max_lines * char_per_line chars
            max_chars = max_lines * char_per_line
            truncated = content[:max_chars]
            return truncated + '[TRUNCATED: original had {0} chars]'.format(len(content))

    def _load_modules(self) -> None:
        """Load modules listed in shard."""
        registry._modules.clear()
        for name in self._module_names:
            try:
                mod = __import__(f'modules.{name}', fromlist=['get_module'])
                if hasattr(mod, 'get_module'):
                    module = mod.get_module()
                    registry.register(module)
            except Exception as e:
                print(f"Warning: Failed to load module {name}: {e}")

    def _get_functions(self) -> list[Function]:
        """Convert registry called_fns to Core Functions."""
        funcs = []
        for mod in registry.all_modules():
            for cf in mod.called_fns:
                effective_timeout = cf.timeout if cf.timeout is not None else self._tool_timeout
                funcs.append(Function(
                    name=cf.name,
                    description=cf.description,
                    parameters=cf.parameters,
                    fn=cf.fn,
                    timeout=effective_timeout,
                ))
        return funcs

    def _build_context(self) -> dict[str, str]:
        """Build context from context functions."""
        return registry.build_context()

    def _reorder_messages(self, messages: list[dict]) -> list[dict]:
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
                # Extract tool_calls JSON from content
                tc_match = re.search(r'\[tool_calls\](.+?)\[/tool_calls\]', content)
                if tc_match:
                    try:
                        tool_calls = json.loads(tc_match.group(1))
                        msg['tool_calls'] = tool_calls
                        # Remove the embedded part from content
                        msg['content'] = re.sub(r'\[tool_calls\].+?\[/tool_calls\]\s*', '', content).strip()
                        if not msg['content']:
                            del msg['content']
                    except json.JSONDecodeError:
                        pass  # Leave as-is if parsing fails
            
            # If this is a tool message, find its matching assistant and insert after it
            if msg.get('role') == 'tool':
                tool_call_id = msg.get('tool_call_id', '')
                if tool_call_id:
                    # Look backwards in result for matching assistant with tool_calls
                    inserted = False
                    for j, existing_msg in enumerate(result):
                        if existing_msg.get('role') == 'assistant':
                            tcs = existing_msg.get('tool_calls', [])
                            for tc in tcs:
                                if tc.get('id') == tool_call_id:
                                    # Insert this tool result right after this assistant
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

    def _build_system_prompt(self) -> str:
        """Build system prompt by replacing {tag} placeholders with context."""
        ctx = self._build_context()
        system = self._system_template
        for tag, content in ctx.items():
            placeholder = f"{{{tag}}}"
            system = system.replace(placeholder, content)
        return system

    def _debug_save(self, stage: str, system_prompt: str, api_messages: list[dict], 
                    context_data: dict = None) -> None:
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
            "session_id": _session_id.get(),
            "context_data": context_data or {},
            "system_prompt": system_prompt,
            "messages": api_messages,
        }
        
        with open(filepath, 'w') as f:
            json.dump(debug_data, f, indent=2, default=str)

    def _save_context_snapshot(self, raw_context: list[dict], label: str, session_id: str = None) -> None:
        """Save raw context snapshot to a file for debugging.
        
        Args:
            raw_context: The context as returned from memory.get_context()
            label: Descriptive label for this snapshot (e.g., 'initial', 'after_tool_call')
            session_id: Session ID if available
        """
        # Use shard's debug_dir if set, otherwise use context_debug in cwd
        debug_dir = self._debug_dir or 'context_debug'
        os.makedirs(debug_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{label}_{timestamp}.json"
        filepath = os.path.join(debug_dir, filename)
        
        snapshot = {
            "timestamp": timestamp,
            "label": label,
            "session_id": session_id or _session_id.get(),
            "message_count": len(raw_context),
            "messages": raw_context,
        }
        
        with open(filepath, 'w') as f:
            json.dump(snapshot, f, indent=2, default=str)
        
        print(f"[CONTEXT SNAPSHOT] Saved {len(raw_context)} messages to {filepath}")

    def cancel(self) -> None:
        """Cancel the current run."""
        self._cancelled = True

    def _parse_calls(self, msg: dict) -> list[FunctionCall]:
        """Extract function calls from an assistant message."""
        calls = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}") or "{}"
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            calls.append(FunctionCall(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=arguments or {},
            ))
        return calls

    async def _execute(self, call: FunctionCall, func_index: dict) -> FunctionResult:
        """Execute a single function call with timeout."""
        func = func_index.get(call.name)
        if not func:
            return FunctionResult(call_id=call.id, name=call.name, content="",
                                  error=f"Unknown function: {call.name}")

        timeout = call.arguments.pop("_timeout", None) or self._tool_timeout

        content, error = "", None
        try:
            result = await asyncio.wait_for(func.fn(**call.arguments), timeout=timeout)
            content = str(result) if result is not None else ""
        except asyncio.TimeoutError:
            error = f"Function timed out after {timeout}s"
        except Exception as e:
            error = str(e)

        return FunctionResult(call_id=call.id, name=call.name, content=content, error=error)

    def _store_assistant(self, memory, assistant_msg: dict, session_id: str) -> None:
        """Store assistant message to memory.
        
        Handles tool_calls embedding and logging of failures.
        Storage happens before yielding to ensure correct message ordering.
        """
        content = assistant_msg.get("content", "") or ""
        content = content.strip() if content else ""
        tool_calls = assistant_msg.get("tool_calls")
        role = assistant_msg.get("role", "assistant")
        
        # Build storage content - embed tool_calls if present
        if tool_calls:
            tool_calls_info = json.dumps(_json_safe(tool_calls))
            storage_content = f"[tool_calls]{tool_calls_info}[/tool_calls]"
            if content:
                storage_content = f"{storage_content}\n\n{content}"
        else:
            storage_content = content
        
        if storage_content or tool_calls:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            print(f"\n[STORE_ASSISTANT {ts}] role={role}")
            if tool_calls:
                for tc in tool_calls:
                    print(f"  tool_call: id={tc.get('id')} name={tc.get('function',{}).get('name')}")
            if storage_content:
                print(f"  content={storage_content[:80]}{'...' if len(storage_content) > 80 else ''}")
            try:
                memory.add_context(role, storage_content, session=session_id)
                print(f"[STORE_ASSISTANT] SUCCESS")
            except Exception as e:
                logger.warning(f"Failed to store assistant message to memory: {e}")
                print(f"[STORE_ASSISTANT] FAILED: {e}")

    async def run_stream(self, session_id: str) -> AsyncIterator[dict]:
        """Run the agent loop.

        Args:
            session_id: Session ID for this conversation. Memory API must contain
                        the user's prompt before this is called.
        
        Yields dicts:
            {"token": str}            - text chunk
            {"thinking": str}         - thinking/reasoning content
            {"tool_call": dict}       - function call detected
            {"tool_result": dict}     - function result  
            {"context_updated": dict} - context was rebuilt
            {"done": True}            - loop complete
            {"error": str}            - error
        """
        import requests
        
        self._cancelled = False
        function_call_count = 0

        # Memory client for this session
        memory = MemoryClient(base_url=self._memory_url, session_id=session_id)

        # Set session ID in context var for all module functions to access
        token = _session_id.set(session_id)
        try:
            functions = self._get_functions()
            func_index = {f.name: f for f in functions}
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": f.name,
                        "description": f.description,
                        "parameters": f.parameters,
                    },
                }
                for f in functions
            ]

            while True:
                if self._cancelled:
                    yield {"error": "cancelled"}
                    return

                # --- Get current context from Memory API ---
                context_error = None
                try:
                    history = memory.get_context(limit=100, session=session_id)
                except requests.exceptions.ConnectionError as e:
                    context_error = str(e)
                    history = []
                    # Save error snapshot even on connection failure
                    if self._debug_snapshots:
                        self._save_context_snapshot([], f"ERROR_memory_api_{function_call_count}", session_id)
                    yield {"error": f"Memory API not available: {context_error}. Ensure memory-api is running."}
                    return
                except Exception as e:
                    context_error = str(e)
                    history = []
                    if self._debug_snapshots:
                        self._save_context_snapshot([], f"ERROR_memory_api_{function_call_count}", session_id)
                    yield {"error": f"Memory API error: {context_error}"}
                    return

                # Debug: save raw context snapshot BEFORE building messages
                if self._debug_snapshots:
                    stage = "initial" if function_call_count == 0 else f"call_{function_call_count}"
                    self._save_context_snapshot(history, f"raw_{stage}", session_id)

                # Build api_messages from history (filter internal fields)
                api_messages = [
                    {k: v for k, v in msg.items() if k not in ('id', 'created_at')}
                    for msg in history
                ]

                # Reorder: ensure tool results follow their assistant message
                api_messages = self._reorder_messages(api_messages)

                # Truncate tool result content to prevent context overflow
                for msg in api_messages:
                    if msg.get('role') == 'tool' and msg.get('content'):
                        original_len = len(msg['content'])
                        msg['content'] = self._truncate_tool_result(
                            msg['content'],
                            self._tool_max_lines,
                            self._tool_char_per_line
                        )
                        if len(msg['content']) < original_len:
                            print(f"[TRUNCATE] tool result: {original_len} -> {len(msg['content'])} chars")

                # Add system prompt at the front
                system = self._build_system_prompt()
                if system:
                    api_messages.insert(0, {"role": "system", "content": system})

                # --- Debug: save context before LLM call ---
                context_data = self._build_context()
                stage = "initial" if function_call_count == 0 else f"call_{function_call_count}"
                self._debug_save(stage=stage, system_prompt=system, 
                               api_messages=api_messages, context_data=context_data)

                # --- Sanitize messages before sending to LLM ---
                api_messages = _json_safe(api_messages)
                
                # Convert tool role to function role for MiniMax API compatibility
                # The LLM needs to see tool_calls in assistant messages to know what was called!
                # We use _json_safe above to handle any Undefined serialization issues
                for msg in api_messages:
                    # MiniMax API expects 'function' role, not 'tool' for function results
                    if msg.get('role') == 'tool':
                        msg['role'] = 'function'
                        # Use 'function' property if available (cleaner than parsing content)
                        if msg.get('function'):
                            msg['name'] = msg['function']
                        else:
                            # Legacy: extract function name from content ("func_name: result")
                            content = msg.get('content', '')
                            if ':' in content:
                                func_name, _, rest = content.partition(':')
                                msg['name'] = func_name.strip()
                                msg['content'] = rest.strip()
                        # Preserve tool_call_id to link result to the original tool call
                        if msg.get('tool_call_id'):
                            msg['tool_call_id'] = msg['tool_call_id']

                # --- DEBUG: Log what goes to LLM ---
                debug_dir = os.environ.get('DEBUG_CONTEXT_DIR', '/home/david/Projects/riven_projects/riven_core/context_logs')
                os.makedirs(debug_dir, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                filename = f"to_llm_{ts}.json"
                filepath = os.path.join(debug_dir, filename)
                with open(filepath, 'w') as f:
                    json.dump({
                        "timestamp": ts,
                        "session": session_id,
                        "function_call_count": function_call_count,
                        "messages": api_messages,
                    }, f, indent=2, default=str)
                
                # --- Call LLM ---
                try:
                    stream = await self._client.chat.completions.create(
                        model=self._llm_model,
                        messages=api_messages,
                        tools=tools or None,
                        stream=True,
                    )
                except Exception as e:
                    yield {"error": f"LLM call failed: {type(e).__name__}: {e}"}
                    return

                # --- Collect the complete assistant message ---
                assistant_msg = {"tool_calls": []}  # Start without content
                full_response = ""

                async for chunk in stream: #streaming is for users benifit. When streaming is done, it should send the whole chunk to the context system than pull a new context in that will include the chunk. The stream only goes to the user.
                    if self._cancelled:
                        yield {"error": "cancelled"}
                        return

                    delta = chunk.choices[0].delta

                    # Handle thinking/reasoning
                    if delta.model_extra:
                        thinking = _json_safe(delta.model_extra.get('reasoning_content')) or _json_safe(delta.model_extra.get('reasoning'))
                        if thinking:
                            yield {"thinking": thinking}
                            full_response += f"[think]{thinking}[/think]"

                    if delta.content:
                        yield {"token": delta.content}
                        if "content" not in assistant_msg:
                            assistant_msg["content"] = ""
                        assistant_msg["content"] += delta.content
                        full_response += delta.content

                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index or 0
                            while len(assistant_msg["tool_calls"]) <= idx:
                                assistant_msg["tool_calls"].append({"id": "", "function": {"name": "", "arguments": ""}})
                            tc = assistant_msg["tool_calls"][idx]
                            if tc_delta.id:
                                tc["id"] = _json_safe(tc_delta.id)
                            if tc_delta.function:
                                func_data = _json_safe(tc_delta.function.model_dump())
                                if func_data.get('name'):
                                    tc["function"]["name"] = func_data['name']
                                if func_data.get('arguments'):
                                    tc["function"]["arguments"] += func_data['arguments']

                # --- Parse calls ---
                calls = self._parse_calls(assistant_msg)

                # --- No tool calls — done ---
                if not calls:
                    assistant_msg["role"] = "assistant"
                    if assistant_msg.get("content", "").strip():
                        # Store BEFORE yield for consistency with tool-call flow
                        self._store_assistant(memory, assistant_msg, session_id)
                        # Debug: snapshot final state
                        if self._debug_snapshots:
                            try:
                                self._save_context_snapshot(
                                    memory.get_context(limit=100, session=session_id),
                                    f"final_response",
                                    session_id
                                )
                            except Exception as e:
                                logger.warning(f"Failed to save context snapshot: {e}")
                        safe_msg = _json_safe(assistant_msg)
                        yield {"assistant": safe_msg}
                    yield {"done": True}
                    return

                # --- Store assistant message BEFORE executing tools ---
                # This ensures correct ordering: assistant -> tool result (not tool -> assistant)
                assistant_msg["role"] = "assistant"
                self._store_assistant(memory, assistant_msg, session_id)

                # --- Execute tool calls ---
                results: list[FunctionResult] = []
                for call in calls:
                    if self._cancelled:
                        yield {"error": "cancelled"}
                        return

                    function_call_count += 1
                    if function_call_count > self._max_function_calls:
                        yield {"error": f"Max function calls reached ({self._max_function_calls})"}
                        return

                    # Yield tool call event
                    yield {"tool_call": {
                        "id": call.id, 
                        "name": call.name, 
                        "arguments": call.arguments
                    }}
                    
                    # Execute
                    result = await self._execute(call, func_index)
                    results.append(result)

                    # Yield tool result event
                    result_content = result.content if not result.error else f"ERROR: {result.error}"
                    yield {"tool_result": {
                        "id": result.call_id, 
                        "name": result.name,
                        "content": result.content, 
                        "error": result.error,
                    }}

                    # Store tool result to memory API
                    # Include tool_call_id to link this result to the assistant's tool_calls
                    # Store function name as 'function' property (not embedded in content)
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                    print(f"\n[STORE_TOOL_RESULT {ts}] call_id={result.call_id} name={result.name}")
                    print(f"  content={result_content[:100]}{'...' if len(result_content) > 100 else ''}")
                    try:
                        memory.add_context(
                            "tool",
                            result_content,
                            session=session_id,
                            tool_call_id=result.call_id,
                            function=result.name
                        )
                        print(f"[STORE_TOOL_RESULT] SUCCESS")
                    except Exception as e:
                        logger.warning(f"Failed to store tool result to memory: {e}")
                        print(f"[STORE_TOOL_RESULT] FAILED: {e}")
                        if self._debug_snapshots:
                            self._save_context_snapshot([], f"ERROR_store_tool_{function_call_count}", session_id)
                    
                    # Debug: save context after storing tool result (verifies storage succeeded)
                    if self._debug_snapshots:
                        try:
                            self._save_context_snapshot(
                                memory.get_context(limit=100, session=session_id),
                                f"after_tool_result_{function_call_count}",
                                session_id
                            )
                        except Exception as e:
                            logger.warning(f"Failed to save context snapshot: {e}")

                # --- Yield assistant message ---
                # (Already stored to memory BEFORE tool execution for correct ordering)
                safe_assistant_msg = _json_safe(assistant_msg)
                yield {"assistant": safe_assistant_msg}

                # Emit that context was rebuilt (for harness to know)
                yield {"context_updated": {"call_count": function_call_count}}
                
        finally:
            try:
                _session_id.reset(token)
            except ValueError:
                pass
