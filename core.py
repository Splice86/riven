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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, AsyncIterator

from openai import AsyncOpenAI
from context import MEMORY_API_URL, MemoryClient, ContextManager, _json_safe
from modules import registry, Module, CalledFn, ContextFn, _session_id

logger = logging.getLogger(__name__)


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
        memory_url = memory_api.get('url', MEMORY_API_URL)

        # Tool result truncation settings from shard
        tool_result_max_lines = shard.get('tool_result_max_lines', 200)
        tool_result_char_per_line = shard.get('tool_result_char_per_line', 150)

        # Debug settings
        debug_dir = shard.get('debug_dir')
        debug_snapshots = shard.get('debug_snapshots', False)

        # Context manager handles all memory API + message processing
        self._ctx = ContextManager(
            memory_url=memory_url,
            tool_result_max_lines=tool_result_max_lines,
            tool_result_char_per_line=tool_result_char_per_line,
            debug_dir=debug_dir,
            debug_snapshots=debug_snapshots,
        )

        # Register modules from shard config
        self._load_modules()

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
            # Suggest using run() for shell commands
            return FunctionResult(call_id=call.id, name=call.name, content="",
                                  error=f"Unknown function: '{call.name}'. For shell commands, use: run(command='{call.name}')")

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
        
        print(f"\n{'='*60}")
        print(f"[CORE] run_stream START: session={session_id}")
        print(f"[CORE] LLM URL: {self._llm_url}")
        print(f"[CORE] Memory URL: {self._ctx._memory_url}")
        print(f"{'='*60}")
        
        self._cancelled = False

        # Memory client for this session
        memory = self._ctx.memory_client

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

            # --- Get current context from Memory API ---
            context_error = None
            try:
                history = memory.get_context(limit=100, session=session_id)
            except requests.exceptions.ConnectionError as e:
                context_error = str(e)
                history = []
                if self._ctx._debug_snapshots:
                    self._ctx.save_context_snapshot([], "ERROR_memory_api", session_id)
                error_msg = f"Memory API connection failed: {context_error}. Ensure memory-api is running on port 8030."
                try:
                    memory.add_context("error", error_msg, session=session_id)
                except Exception:
                    pass  # If we can't store error, continue anyway
                yield {"error": error_msg}
                return
            except Exception as e:
                context_error = str(e)
                history = []
                if self._ctx._debug_snapshots:
                    self._ctx.save_context_snapshot([], "ERROR_memory_api", session_id)
                error_msg = f"Memory API error: {context_error}"
                try:
                    memory.add_context("error", error_msg, session=session_id)
                except Exception:
                    pass
                yield {"error": error_msg}
                return

            # Debug: save raw context snapshot BEFORE building messages
            if self._ctx._debug_snapshots:
                self._ctx.save_context_snapshot(history, "raw_loop", session_id)

            # Build messages for LLM (system prompt + processed history)
            api_messages, system = self._ctx.prepare_messages_for_llm(
                history, self._system_template, registry
            )

            # Debug: save context before LLM call
            context_data = self._ctx.build_context_from_modules(registry)
            self._ctx.debug_save(stage="loop", system_prompt=system,
                                 api_messages=api_messages, context_data=context_data)

            # Sanitize messages for LLM API
            api_messages = self._ctx.sanitize_messages_for_llm(api_messages)
            
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
                    "messages": api_messages,
                }, f, indent=2, default=str)
            
            # --- Call LLM ---
            print(f"[CORE] Calling LLM: model={self._llm_model}, message_count={len(api_messages)}")
            try:
                stream = await self._client.chat.completions.create(
                    model=self._llm_model,
                    messages=api_messages,
                    tools=tools or None,
                    stream=True,
                )
                print(f"[CORE] LLM call started successfully")
            except Exception as e:
                print(f"[CORE] LLM call FAILED: {type(e).__name__}: {e}")
                error_msg = f"LLM call failed: {type(e).__name__}: {e}. Session={session_id}"
                try:
                    memory.add_context("error", error_msg, session=session_id)
                except Exception:
                    pass
                yield {"error": error_msg}
                return

            # --- Collect the complete assistant message ---
            assistant_msg = {"tool_calls": []}
            full_response = ""

            async for chunk in stream:
                if self._cancelled:
                    error_msg = f"Execution was cancelled by user. Session={session_id}"
                    try:
                        memory.add_context("error", error_msg, session=session_id)
                    except Exception:
                        pass
                    print(f"[CORE] YIELD error (cancelled): {error_msg}")
                    yield {"error": error_msg}
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
                print(f"[CORE] No tool calls - completing")
                assistant_msg["role"] = "assistant"
                if assistant_msg.get("content", "").strip():
                    self._store_assistant(memory, assistant_msg, session_id)
                    if self._ctx._debug_snapshots:
                        try:
                            self._ctx.save_context_snapshot(
                                memory.get_context(limit=100, session=session_id),
                                "final_response", session_id
                            )
                        except Exception as e:
                            logger.warning(f"Failed to save context snapshot: {e}")
                    safe_msg = _json_safe(assistant_msg)
                    yield {"assistant": safe_msg}
                print(f"[CORE] YIELD done")
                yield {"done": True}
                return

            # --- Store assistant message BEFORE executing tools ---
            assistant_msg["role"] = "assistant"
            self._store_assistant(memory, assistant_msg, session_id)

            # --- Execute tool calls ---
            results: list[FunctionResult] = []
            for call in calls:
                if self._cancelled:
                    error_msg = f"Execution was cancelled by user. Session={session_id}"
                    try:
                        memory.add_context("error", error_msg, session=session_id)
                    except Exception:
                        pass
                    yield {"error": error_msg}
                    return

                if len(results) + 1 > self._max_function_calls:
                    error_msg = f"Max function calls reached ({self._max_function_calls}). Session={session_id}"
                    try:
                        memory.add_context("error", error_msg, session=session_id)
                    except Exception:
                        pass
                    print(f"[CORE] YIELD error (max calls): {error_msg}")
                    yield {"error": error_msg}
                    return

                print(f"[CORE] YIELD tool_call: id={call.id} name={call.name}")
                yield {"tool_call": {
                    "id": call.id, 
                    "name": call.name, 
                    "arguments": call.arguments
                }}
                
                result = await self._execute(call, func_index)
                results.append(result)

                result_content = result.content if not result.error else f"ERROR: {result.error}"
                print(f"[CORE] YIELD tool_result: id={result.call_id} name={result.name} error={result.error}")
                yield {"tool_result": {
                    "id": result.call_id, 
                    "name": result.name,
                    "content": result.content, 
                    "error": result.error,
                }}

                # Store tool result to memory API
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
                    if self._ctx._debug_snapshots:
                        self._ctx.save_context_snapshot([], "ERROR_store_tool", session_id)

                if self._ctx._debug_snapshots:
                    try:
                        self._ctx.save_context_snapshot(
                            memory.get_context(limit=100, session=session_id),
                            "after_tool_result", session_id
                        )
                    except Exception as e:
                        logger.warning(f"Failed to save context snapshot: {e}")

            # --- Yield assistant message ---
            safe_assistant_msg = _json_safe(assistant_msg)
            yield {"assistant": safe_assistant_msg}

            # Signal that context was rebuilt and control returns to harness
            yield {"context_rebuilt": True}

        finally:
            try:
                _session_id.reset(token)
            except ValueError:
                pass
