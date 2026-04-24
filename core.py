"""The core agent loop - LLM calls with function execution.

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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, AsyncIterator

from openai import AsyncOpenAI
from context import MemoryClient, ContextManager, _json_safe
from config import get
from modules import registry, Module, CalledFn, ContextFn, _session_id

logger = logging.getLogger(__name__)

# High-level debug flag - set to True to enable trace prints
DEBUG_HANG = True

def _debug(step: str, session_id: str = None) -> None:
    """Print timestamped debug messages to trace execution flow."""
    if not DEBUG_HANG:
        return
    ts = time.time()
    sid = f"[{session_id[:8]}]" if session_id else "[--------]"
    print(f"[DEBUG {ts:.3f}] {sid} {step}", flush=True)


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
        self._llm_url = llm.get('url') if llm else None
        self._llm_model = llm.get('model') if llm else None
        self._llm_api_key = llm.get('api_key') if llm else None
        
        # Shard settings
        self._system_template = shard.get('system', '')
        self._module_names = shard.get('modules', [])
        self._max_function_calls = max_function_calls
        self._tool_timeout = shard.get('tool_timeout', tool_timeout or 20.0)
        self._cancelled = False
        self._client = AsyncOpenAI(base_url=self._llm_url, api_key=self._llm_api_key)

        # Memory API settings from shard
        memory_api = shard.get('memory_api', {})
        self._memory_url = memory_api.get('url')

        # Tool result truncation settings from shard
        tool_result_max_lines = shard.get('tool_result_max_lines', 200)
        tool_result_char_per_line = shard.get('tool_result_char_per_line', 150)

        # Context manager handles all memory API + message processing
        self._ctx = ContextManager(
            memory_url=self._memory_url,
            tool_result_max_lines=tool_result_max_lines,
            tool_result_char_per_line=tool_result_char_per_line,
        )

    def _load_modules(self, session_id: str = None) -> None:
        """Load modules listed in shard."""
        _debug(f"_load_modules: clearing registry, loading {self._module_names}", session_id)
        registry._modules.clear()
        for name in self._module_names:
            _debug(f"_load_modules: importing modules.{name}", session_id)
            try:
                mod = __import__(f'modules.{name}', fromlist=['get_module'])
                _debug(f"_load_modules: modules.{name} imported, checking get_module", session_id)
                if hasattr(mod, 'get_module'):
                    module = mod.get_module()
                    registry.register(module)
                    _debug(f"_load_modules: registered module '{name}'", session_id)
                else:
                    _debug(f"_load_modules: modules.{name} has no get_module, skipping", session_id)
            except Exception as e:
                _debug(f"_load_modules: FAILED to load {name}: {e}", session_id)
                logger.warning(f"Failed to load module {name}: {e}")
        _debug(f"_load_modules: done, registry has {list(registry._modules.keys())}", session_id)

    def _get_functions(self, session_id: str = None) -> list[Function]:
        """Convert registry called_fns to Core Functions."""
        _debug(f"_get_functions: building function list from {len(list(registry.all_modules()))} modules", session_id)
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
        _debug(f"_get_functions: done, {len(funcs)} functions: {[f.name for f in funcs]}", session_id)
        return funcs

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

    async def _execute(self, call: FunctionCall, func_index: dict, session_id: str = None) -> FunctionResult:
        """Execute a single function call with timeout."""
        _debug(f"_execute: looking up '{call.name}'", session_id)
        func = func_index.get(call.name)
        if not func:
            # Suggest using run() for shell commands
            _debug(f"_execute: '{call.name}' NOT FOUND in func_index", session_id)
            return FunctionResult(call_id=call.id, name=call.name, content="",
                                  error=f"Unknown function: '{call.name}'. For shell commands, use: run(command='{call.name}')")

        timeout = call.arguments.pop("_timeout", None) or self._tool_timeout
        _debug(f"_execute: calling {func.fn} with timeout={timeout}s args={list(call.arguments.keys())}", session_id)

        content, error = "", None
        try:
            result = await asyncio.wait_for(func.fn(**call.arguments), timeout=timeout)
            content = str(result) if result is not None else ""
            _debug(f"_execute: {call.name} completed OK (content len={len(content)})", session_id)
        except asyncio.TimeoutError:
            error = f"Function timed out after {timeout}s"
            _debug(f"_execute: {call.name} TIMED OUT after {timeout}s", session_id)
        except Exception as e:
            error = str(e)
            _debug(f"_execute: {call.name} EXCEPTION: {e}", session_id)

        return FunctionResult(call_id=call.id, name=call.name, content=content, error=error)

    def _store_assistant(self, memory: MemoryClient, assistant_msg: dict, session_id: str) -> None:
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
            try:
                memory.add_context(role, storage_content, session=session_id)
            except Exception as e:
                logger.warning(f"Failed to store assistant message to memory: {e}")
        
        # DEBUG: log assistant messages with empty or near-empty content
        if tool_calls and not content:
            _debug(f"_store_assistant: WARNING - tool-call-only message (no text), id={tool_calls[0].get('id','?')[:8]}", session_id)

    def _save_llm_context(self, api_messages: list[dict], session_id: str) -> None:
        """Save the full LLM request context to a timestamped file.
        
        Saves to debug_dir as JSON with metadata. Useful for tracing and debugging
        what was actually sent to the LLM.
        """
        debug_dir = get('debug_dir', 'context_logs')
        if not debug_dir:
            return
        
        # Create debug dir if it doesn't exist
        try:
            os.makedirs(debug_dir, exist_ok=True)
        except OSError:
            return
        
        # Build timestamped filename: YYYY-MM-DD_HH-MM-SS_<session>.json
        now = datetime.now(timezone.utc)
        ts = now.strftime('%Y-%m-%d_%H-%M-%S')
        # Truncate session_id for filename (first 16 chars)
        sid = session_id[:16] if session_id else 'nosession'
        filename = f"{ts}_{sid}.json"
        filepath = os.path.join(debug_dir, filename)
        
        # Build payload with metadata
        payload = {
            "saved_at": now.isoformat(),
            "session_id": session_id,
            "model": self._llm_model,
            "num_messages": len(api_messages),
            "messages": api_messages,
        }
        
        try:
            with open(filepath, 'w') as f:
                json.dump(payload, f, indent=2)
            _debug(f"LLM context saved to {filepath}", session_id)
        except OSError as e:
            logger.warning(f"Failed to save LLM context: {e}")

    async def run_stream(self, session_id: str) -> AsyncIterator[dict]:
        _debug("→ run_stream ENTRY", session_id)
        """Run the agent loop for ONE turn.
        
        This method processes a single LLM call and returns. After tool execution,
        it yields a "context_rebuilt" event and then returns, handing control back
        to the harness. The harness decides when to call run_stream() again.

        Args:
            session_id: Session ID for this conversation. Memory API must contain
                        the user's prompt before this is called.
        
        Yields dicts:
            {"token": str}            - text chunk
            {"thinking": str}         - thinking/reasoning content
            {"tool_call": dict}       - function call detected
            {"tool_result": dict}     - function result  
            {"context_rebuilt": True} - context rebuilt, loop continuing
            {"assistant": dict}       - complete assistant message
            {"done": True}            - loop complete
            {"error": str}            - error
        """
        import requests
        
        self._cancelled = False
        _debug("run_stream: starting turn", session_id)

        # Memory client for this session
        memory = self._ctx.memory_client

        # Set session ID in context var FIRST so all module operations can access it
        token = _session_id.set(session_id)
        try:
            # Load modules (only on first call per Core instance) and build function index
            # This must be inside the try block so _session_id is set for context functions
            if not registry._modules:
                self._load_modules(session_id)
            functions = self._get_functions(session_id)
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

            # --- Get current context from Memory API ---
            context_error = None
            _debug("run_stream: fetching history from memory API", session_id)
            try:
                history = memory.get_context(session=session_id)
                _debug(f"run_stream: history received ({len(history)} messages)", session_id)
            except requests.exceptions.ConnectionError as e:
                context_error = str(e)
                history = []
                _debug(f"run_stream: Memory API connection failed: {context_error}", session_id)
                error_msg = f"Memory API connection failed: {context_error}. Ensure memory-api is running at {self._memory_url or 'http://localhost:8030'}."
                try:
                    memory.add_context("tool", error_msg, session=session_id)
                except Exception:
                    pass
                yield {"error": error_msg}
                return
            except Exception as e:
                context_error = str(e)
                history = []
                _debug(f"run_stream: Memory API error: {context_error}", session_id)
                error_msg = f"Memory API error: {context_error}"
                try:
                    memory.add_context("tool", error_msg, session=session_id)
                except Exception:
                    pass
                yield {"error": error_msg}
                return

            _debug("run_stream: preparing messages for LLM", session_id)
            # Build messages for LLM (system prompt + processed history)
            api_messages, system = self._ctx.prepare_messages_for_llm(
                history, self._system_template, registry
            )

            # Sanitize messages for LLM API
            api_messages = self._ctx.sanitize_messages_for_llm(api_messages)
            
            # --- Save LLM request context snapshot ---
            self._save_llm_context(api_messages, session_id)
            
            # --- Pre-LLM debug audit: log message summary and catch empty-content bugs ---
            # Check for both '' content AND missing content key (the bug that caused MiniMax 400)
            issues = []
            for i, msg in enumerate(api_messages):
                role = msg.get('role', '?')
                if role in ('tool', 'system'):
                    continue
                content = msg.get('content')
                has_tc = bool(msg.get('tool_calls'))
                if content is None:
                    issues.append(f"msg[{i}][{role}] content=None")
                elif content == '':
                    issues.append(f"msg[{i}][{role}] content='' {'(tool-call-only)' if has_tc else ''}")
            if issues:
                _debug(f"run_stream: WARNING - empty content issues detected: {'; '.join(issues)}", session_id)
            else:
                _debug(f"run_stream: LLM call ready - {len(api_messages)} messages, roles={[m.get('role') for m in api_messages]}", session_id)
            
            # --- Call LLM ---
            _debug("run_stream: calling LLM (streaming)", session_id)
            try:
                stream = await self._client.chat.completions.create(
                    model=self._llm_model,
                    messages=api_messages,
                    tools=tools or None,
                    stream=True,
                )
            except Exception as e:
                error_msg = f"LLM call failed: {type(e).__name__}: {e}. Session={session_id}"
                _debug(f"run_stream: LLM call failed: {error_msg}", session_id)
                try:
                    memory.add_context("tool", error_msg, session=session_id)
                except Exception:
                    pass
                yield {"error": error_msg}
                return

            # --- Collect the complete assistant message ---
            assistant_msg = {"tool_calls": []}
            _debug("run_stream: waiting for LLM stream chunks", session_id)

            async for chunk in stream:
                if self._cancelled:
                    error_msg = f"Execution was cancelled by user. Session={session_id}"
                    try:
                        memory.add_context("tool", error_msg, session=session_id)
                    except Exception:
                        pass
                    yield {"error": error_msg}
                    return

                delta = chunk.choices[0].delta

                # Handle thinking/reasoning
                if delta.model_extra:
                    thinking = _json_safe(delta.model_extra.get('reasoning_content')) or _json_safe(delta.model_extra.get('reasoning'))
                    if thinking:
                        yield {"thinking": thinking}

                if delta.content:
                    yield {"token": delta.content}
                    if "content" not in assistant_msg:
                        assistant_msg["content"] = ""
                    assistant_msg["content"] += delta.content

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

            _debug("run_stream: LLM stream complete", session_id)
            # --- Parse calls ---
            calls = self._parse_calls(assistant_msg)

            # --- No tool calls — done ---
            if not calls:
                _debug("run_stream: no tool calls, done", session_id)
                assistant_msg["role"] = "assistant"
                if assistant_msg.get("content", "").strip():
                    self._store_assistant(memory, assistant_msg, session_id)
                    safe_msg = _json_safe(assistant_msg)
                    yield {"assistant": safe_msg}
                yield {"done": True}
                _debug("run_stream: ← EXIT (done)", session_id)
                return

            # --- Store assistant message BEFORE executing tools ---
            _debug(f"run_stream: executing {len(calls)} tool call(s): {[c.name for c in calls]}", session_id)
            assistant_msg["role"] = "assistant"
            self._store_assistant(memory, assistant_msg, session_id)

            # --- Execute tool calls ---
            results: list[FunctionResult] = []
            for call in calls:
                if self._cancelled:
                    error_msg = f"Execution was cancelled by user. Session={session_id}"
                    try:
                        memory.add_context("error", error_msg, session=session_id)
                    except Exception as store_err:
                        logger.warning(f"Failed to store cancel error to memory: {store_err}")
                    yield {"error": error_msg}
                    return

                if len(results) + 1 > self._max_function_calls:
                    error_msg = f"Max function calls reached ({self._max_function_calls}). Session={session_id}"
                    try:
                        memory.add_context("tool", error_msg, session=session_id)
                    except Exception as store_err:
                        logger.warning(f"Failed to store max-calls error to memory: {store_err}")
                    yield {"error": error_msg}
                    return

                yield {"tool_call": {
                    "id": call.id, 
                    "name": call.name, 
                    "arguments": call.arguments
                }}
                
                result = await self._execute(call, func_index, session_id)
                _debug(f"run_stream: tool '{call.name}' executed, error={result.error}", session_id)
                results.append(result)

                result_content = result.content if not result.error else f"ERROR: {result.error}"
                yield {"tool_result": {
                    "id": result.call_id, 
                    "name": result.name,
                    "content": result.content, 
                    "error": result.error,
                }}

                # Store tool result to memory API
                _debug(f"run_stream: storing tool result to memory API", session_id)
                try:
                    memory.add_context(
                        "tool",
                        result_content,
                        session=session_id,
                        tool_call_id=result.call_id,
                        function=result.name
                    )
                except Exception as e:
                    logger.warning(f"Failed to store tool result to memory: {e}")
                _debug("run_stream: tool result stored", session_id)

            # --- Yield assistant message ---
            safe_assistant_msg = _json_safe(assistant_msg)
            yield {"assistant": safe_assistant_msg}

            # Signal that context was rebuilt and control returns to harness
            yield {"context_rebuilt": True}
            _debug("run_stream: ← EXIT (context_rebuilt)", session_id)

        finally:
            try:
                _session_id.reset(token)
            except ValueError:
                pass
