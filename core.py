"""The core agent loop - LLM calls with function execution.
Architecture:
- Context DB (db.ContextDB): stores conversation history (user, assistant, tool messages)
- Core: takes session_id, gets history from DB, runs loop, stores responses to DB
- Harness: orchestrates - stores user message to DB before calling Core

Flow:
  prompt -> db + activate core with session ID
  -> context built from db
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
from context import ContextManager, _json_safe
from config import get
from db import ContextDB
from modules import registry, Module, CalledFn, ContextFn, _session_id
from logging_config import get_logger

logger = get_logger(__name__)

# High-level debug flag - set to True to enable trace prints
DEBUG_HANG = True  # Enable for lock-up debugging

def _debug(step: str, session_id: str = None) -> None:
    """Timestamped debug messages — goes to log file via logger.debug."""
    if not DEBUG_HANG:
        return
    ts = time.time()
    sid = f"[{session_id[:8]}]" if session_id else "[--------]"
    logger.debug("[DEBUG %s] %s %s", ts, sid, step)

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
    
    IMPORTANT: Context DB must be available. User's prompt should be stored
    to the context DB BEFORE calling run_stream(). This method only takes session_id.
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
        self._cancel_requested = False
        self._client = AsyncOpenAI(base_url=self._llm_url, api_key=self._llm_api_key)

        # Tool result truncation settings from shard
        tool_result_max_lines = shard.get('tool_result_max_lines', 200)
        tool_result_char_per_line = shard.get('tool_result_char_per_line', 150)

        # Context manager handles message processing
        self._ctx = ContextManager(
            tool_result_max_lines=tool_result_max_lines,
            tool_result_char_per_line=tool_result_char_per_line,
        )

    def _discover_modules(self) -> list[str]:
        """Scan modules/ directory and return a resolved list of module names.
        
        Discovers all packages (directories with __init__.py) and sub-packages.
        Resolves name aliases so config names like 'web' map to folder names
        like 'web_tools'. Skips modules that don't exist.
        """
        import os
        import importlib.util

        # Name aliasing: config name -> actual folder name
        ALIASES = {
            'web': 'web_tools',
        }

        modules_dir = os.path.join(os.path.dirname(__file__), 'modules')
        discovered = []

        for entry in os.scandir(modules_dir):
            if not entry.is_dir():
                continue
            if entry.name == '__pycache__':
                continue
            if not os.path.isfile(os.path.join(entry.path, '__init__.py')):
                continue

            # Recurse into sub-packages (e.g., modules/file/ sub-folders with __init__.py)
            for sub_entry in os.scandir(entry.path):
                if not sub_entry.is_dir():
                    continue
                if not os.path.isfile(os.path.join(sub_entry.path, '__init__.py')):
                    continue
                folder_name = f"{entry.name}/{sub_entry.name}"
                # Only include if it has get_module
                if self._folder_has_get_module(os.path.join(modules_dir, folder_name)):
                    discovered.append(folder_name)

            # Top-level packages (e.g., modules/shell/, modules/file/)
            if self._folder_has_get_module(entry.path):
                discovered.append(entry.name)

        # Apply aliases from shard config, then resolve
        resolved = []
        requested = self._module_names.copy()
        for name in requested:
            if name in ALIASES:
                actual = ALIASES[name]
                _debug(f"_discover_modules: alias '{name}' -> '{actual}'", None)
                if actual not in resolved:
                    resolved.append(actual)
            elif name in resolved:
                pass  # Already added
            else:
                # Check if the requested name is a valid folder name
                if name in discovered:
                    resolved.append(name)
                else:
                    _debug(f"_discover_modules: '{name}' not found in modules/ — skipping", None)

        return resolved

    def _folder_has_get_module(self, folder_path: str) -> bool:
        """True if a package folder has a get_module callable in its __init__.py.

        Uses importlib.import_module so relative imports within the module
        (e.g. 'from .models import ...') resolve correctly.
        """
        import importlib
        init_path = os.path.join(folder_path, '__init__.py')
        if not os.path.isfile(init_path):
            return False
        # Derive the package-relative module name so imports resolve
        rel = os.path.relpath(folder_path, os.path.dirname(__file__))
        # e.g. modules/workflow -> modules.workflow
        if rel.startswith('modules'):
            mod_name = rel.replace(os.sep, '.')
            if not mod_name.startswith('modules.'):
                mod_name = 'modules.' + mod_name
        else:
            # e.g. modules/file/models -> modules.file.models
            mod_name = rel.replace(os.sep, '.')
        try:
            mod = importlib.import_module(mod_name)
            return hasattr(mod, 'get_module')
        except Exception:
            pass
        return False

    def _load_modules(self, session_id: str = None) -> None:
        """Load modules discovered from modules/ directory, filtered by shard config."""
        resolved_names = self._discover_modules()
        _debug(f"_load_modules: resolved modules = {resolved_names}", session_id)
        registry._modules.clear()
        loaded, failed = [], []
        for name in resolved_names:
            _debug(f"_load_modules: importing modules.{name}", session_id)
            try:
                mod = __import__(f'modules.{name}', fromlist=['get_module'])
                _debug(f"_load_modules: modules.{name} imported, checking get_module", session_id)
                if hasattr(mod, 'get_module'):
                    module = mod.get_module()
                    registry.register(module)
                    loaded.append(name)
                    _debug(f"_load_modules: registered module '{name}'", session_id)
                else:
                    _debug(f"_load_modules: modules.{name} has no get_module, skipping", session_id)
                    failed.append(f"{name} (no get_module)")
            except Exception as e:
                logger.error("[Module] FAILED to load '%s': %s", name, e, exc_info=True)
                failed.append(f"{name} ({e})")
        loaded_names = list(registry._modules.keys())
        _debug(f"_load_modules: done, registry has {loaded_names}", session_id)
        if failed:
            logger.warning("[Module] Load complete — %d OK, %d FAILED: %s", len(loaded), len(failed), failed)
        else:
            logger.info("[Module] All %d modules loaded: %s", len(loaded), loaded)

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
        """Cancel the current run.
        
        Sets _cancel_requested so any running tool execution (via _execute)
        will detect it on its next poll cycle and raise CancelledError.
        Sets _cancelled so the LLM stream loop and tool call loop exit.
        """
        self._cancel_requested = True
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
        """Execute a single function call with timeout and cancellation support.
        
        Uses a polling wait_for loop (poll every 0.1s) to detect _cancel_requested
        as soon as possible. When cancel() is called, _execute will raise
        CancelledError within 0.1s, which propagates up and breaks the loop.
        """
        _debug(f"_execute: looking up '{call.name}'", session_id)
        func = func_index.get(call.name)
        if not func:
            # Suggest using run() for shell commands
            _debug(f"_execute: '{call.name}' NOT FOUND in func_index", session_id)
            return FunctionResult(call_id=call.id, name=call.name, content="",
                                  error=f"Unknown function: '{call.name}'. For shell commands, use: run(command='{call.name}')")

        timeout = call.arguments.pop("_timeout", None) or self._tool_timeout
        _exec_start = time.time()
        _debug(f"_execute: calling {func.fn} with timeout={timeout}s args={list(call.arguments.keys())}", session_id)

        content, error = "", None
        is_async = inspect.iscoroutinefunction(func.fn)
        try:
            if not is_async:
                # Sync function — run in thread pool with full timeout (no polling)
                if self._cancel_requested:
                    raise asyncio.CancelledError()
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(func.fn, **call.arguments),
                        timeout=timeout,
                    )
                    content = str(result) if result is not None else ""
                    _debug(f"_execute: {call.name} completed OK ({time.time()-_exec_start:.3f}s, content len={len(content)})", session_id)
                except asyncio.TimeoutError:
                    error = f"Function timed out after {timeout}s"
                    logger.warning("[Tool] '%s' TIMED OUT after %ss", call.name, timeout)
            else:
                # Async function — polling loop for cancellation responsiveness
                remaining = timeout
                poll_interval = 0.1  # check _cancel_requested every 100ms
                while remaining > 0:
                    chunk = min(remaining, poll_interval)
                    if self._cancel_requested:
                        raise asyncio.CancelledError()
                    try:
                        result = await asyncio.wait_for(func.fn(**call.arguments), timeout=chunk)
                        content = str(result) if result is not None else ""
                        _debug(f"_execute: {call.name} completed OK ({time.time()-_exec_start:.3f}s, content len={len(content)})", session_id)
                        break  # success
                    except asyncio.TimeoutError:
                        remaining -= chunk
                        if self._cancel_requested:
                            raise asyncio.CancelledError()
                        if remaining <= 0:
                            # Natural timeout (not a user cancel) — let outer handler deal with it
                            raise asyncio.TimeoutError()
                        # else continue polling
        except asyncio.CancelledError:
            logger.info("[Tool] '%s' CANCELLED by user", call.name)
            raise  # propagate to run_stream tool loop
        except Exception as e:
            error = str(e)
            logger.error("[Tool] '%s' EXCEPTION after %.3fs: %s", call.name, time.time()-_exec_start, e, exc_info=True)

        return FunctionResult(call_id=call.id, name=call.name, content=content, error=error)

    def _store_assistant(self, db: ContextDB, assistant_msg: dict, session_id: str) -> None:
        """Store assistant message to context DB.
        
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
                db.add(role, storage_content, session=session_id)
            except Exception as e:
                logger.error("[DB] Failed to store assistant message: %s", e, exc_info=True)
        
        # DEBUG: log assistant messages with empty or near-empty content
        if tool_calls and not content:
            _debug(f"_store_assistant: WARNING - tool-call-only message (no text), id={tool_calls[0].get('id','?')[:8]}", session_id)

    def _get_db(self) -> ContextDB:
        """Lazily create a ContextDB instance."""
        if not hasattr(self, "_db"):
            self._db = ContextDB()
        return self._db

    def _save_llm_context(self, api_messages: list[dict], session_id: str) -> None:
        """Save the full LLM request context to a timestamped file.
        
        Saves to debug_dir as JSON with metadata. Useful for tracing and debugging
        what was actually sent to the LLM. Respects debug_snapshots flag.
        """
        # Check debug_snapshots flag first - if false, skip saving entirely
        debug_snapshots = get('debug_snapshots', False)
        if not debug_snapshots:
            return
        
        debug_dir = get('debug_dir', '~/.riven/logs')
        if not debug_dir:
            return
        
        # Expand ~ to home directory and create debug dir if it doesn't exist
        debug_dir = os.path.expanduser(debug_dir)
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
        _rs_start = time.time()
        _debug(f"→ run_stream ENTRY (total time tracking starts)", session_id)
        """Run the agent loop for ONE turn.
        
        This method processes a single LLM call and returns. After tool execution,
        it yields a "context_rebuilt" event and then returns, handing control back
        to the harness. The harness decides when to call run_stream() again.

        Args:
            session_id: Session ID for this conversation. Context DB must contain
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
        db = self._get_db()

        self._cancelled = False
        _debug("run_stream: starting turn", session_id)

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

            # --- Get current context from DB ---
            context_error = None
            _debug("run_stream: fetching history from context DB", session_id)
            _mem_fetch_start = time.time()
            try:
                history = db.get_history(session=session_id)
                _debug(f"run_stream: history received ({len(history)} msgs, took {time.time()-_mem_fetch_start:.3f}s)", session_id)
            except Exception as e:
                context_error = str(e)
                history = []
                _debug(f"run_stream: context DB error (took {time.time()-_mem_fetch_start:.3f}s): {context_error}", session_id)
                error_msg = f"Context database error: {context_error}"
                try:
                    db.add("tool", error_msg, session=session_id)
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
            
            # --- RAW PRINT: dump raw api_messages with repr (outside all try/except) ---
            # Using raw print() so it cannot be silenced by any exception handler
            import pprint as _pprint
            logger.debug("[RAW_PRINT %s] [%s] api_messages after sanitize (%d msgs):", time.time(), session_id[:8], len(api_messages))
            for i, msg in enumerate(api_messages):
                logger.debug("  [RAW_PRINT] msg[%d] type=%s repr_keys=%s full_repr=%s", i, type(msg).__name__, repr(list(msg.keys())), repr(msg)[:500])
            
            # --- Save LLM request context snapshot ---
            self._save_llm_context(api_messages, session_id)
            
            # --- Pre-LLM debug audit: log message summary and catch empty-content bugs ---
            # Check for both '' content AND missing content key (the bug that caused MiniMax 400)
            issues = []
            for i, msg in enumerate(api_messages):
                try:
                    role = msg.get('role', '?')
                    content = msg.get('content')
                    has_tc = bool(msg.get('tool_calls'))
                    has_content_key = 'content' in msg
                    content_repr = repr(content[:100]) if content else f"{'MISSING_KEY' if not has_content_key else 'EMPTY'}"
                    
                    # Detailed per-message debug
                    _debug(f"run_stream: msg[{i}] role={role} has_content_key={has_content_key} content={content_repr} has_tool_calls={has_tc}", session_id)
                    
                    if content is None:
                        issues.append(f"msg[{i}][{role}] content=None (key missing)")
                    elif content == '':
                        issues.append(f"msg[{i}][{role}] content='' {'(tool-call-only)' if has_tc else ''}")
                except Exception as e:
                    _debug(f"run_stream: msg[{i}] AUDIT CRASH: {type(e).__name__}: {e}", session_id)
            
            if issues:
                _debug(f"run_stream: WARNING - empty content issues detected: {'; '.join(issues)}", session_id)
            else:
                _debug(f"run_stream: LLM call ready - {len(api_messages)} messages, roles={[m.get('role') for m in api_messages]}", session_id)
            
            # Dump full message list for deep debugging (crash-proof)
            _debug(f"run_stream: FULL MESSAGE DUMP ({len(api_messages)} msgs):", session_id)
            for i, msg in enumerate(api_messages):
                try:
                    role = msg.get('role', '?')
                    content = msg.get('content')
                    has_content_key = 'content' in msg
                    tc_info = ''
                    if msg.get('tool_calls'):
                        tc_names = [tc.get('function', {}).get('name', '?') for tc in msg['tool_calls']]
                        tc_info = f' tool_calls={tc_names}'
                    
                    # Handle all content types safely
                    if content is None:
                        _debug(f"  msg[{i}] role={role} content=NONE has_key={has_content_key}{tc_info}", session_id)
                        _debug(f"    content_preview: <NONE>", session_id)
                    elif isinstance(content, str):
                        preview = content[:200] if content else '<EMPTY_STRING>'
                        _debug(f"  msg[{i}] role={role} content_len={len(content)} has_key={has_content_key}{tc_info}", session_id)
                        _debug(f"    content_preview: {repr(preview)}", session_id)
                    else:
                        _debug(f"  msg[{i}] role={role} content_type={type(content).__name__} has_key={has_content_key}{tc_info}", session_id)
                        _debug(f"    content_preview: {repr(str(content)[:200])}", session_id)
                except Exception as e:
                    _debug(f"  msg[{i}] DUMP ERROR: {type(e).__name__}: {e} msg_keys={list(msg.keys()) if isinstance(msg, dict) else type(msg)}", session_id)
            
            # --- Call LLM ---
            _debug("run_stream: calling LLM (streaming)", session_id)
            _llm_start = time.time()
            
            # FINAL GUARD: check all messages right before LLM call and fix any remaining issues
            for i, msg in enumerate(api_messages):
                role = msg.get('role', '?')
                content = msg.get('content')
                has_tc = bool(msg.get('tool_calls'))
                if content is None:
                    _debug(f"run_stream: URGENT FIX: msg[{i}][{role}] content=None, forcing to '(no output)'", session_id)
                    msg['content'] = '(no output)'
                elif content == '' and not has_tc:
                    _debug(f"run_stream: URGENT FIX: msg[{i}][{role}] content='' no-tool-calls, forcing to '(no output)'", session_id)
                    msg['content'] = '(no output)'
            
            # Dump the exact payload being sent
            import json as _json_mod
            _debug(f"run_stream: LLM REQUEST PAYLOAD:", session_id)
            for i, msg in enumerate(api_messages):
                role = msg.get('role', '?')
                content = msg.get('content', '<MISSING>')
                tcs = msg.get('tool_calls')
                tc_str = f" tool_calls[{len(tcs)}]" if tcs else ""
                _debug(f"  [{i}] role={role} content_len={len(content) if content else 0}{tc_str}: {repr(content[:300] if content else '<EMPTY>')}", session_id)
            
            # FINAL GUARD: validate every message before the LLM call.
            # MiniMax (and others) return 400 "zero-length document" for:
            #   - content = ''        (empty string)
            #   - content = None      (missing key)
            #   - content = '   '     (whitespace-only)
            # This also saves the full payload on failure so we can always reproduce it.
            bad_msgs = []
            for i, msg in enumerate(api_messages):
                role = msg.get('role', '?')
                content = msg.get('content')
                has_tc = bool(msg.get('tool_calls'))
                if content is None:
                    bad_msgs.append(f"msg[{i}][{role}] content=None")
                elif content == '':
                    bad_msgs.append(f"msg[{i}][{role}] content=''")
                elif isinstance(content, str) and not content.strip():
                    bad_msgs.append(f"msg[{i}][{role}] content='{content[:20]}' (whitespace-only)")
            if bad_msgs:
                # Save full payload for forensics
                import os as _os
                import pathlib as _pathlib
                debug_dir = _os.path.expanduser("~/.riven/logs/bad_payloads")
                _os.makedirs(debug_dir, exist_ok=True)
                ts_str = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')
                payload_path = _os.path.join(debug_dir, f"{ts_str}_{session_id[:16]}.json")
                try:
                    with open(payload_path, 'w') as _f:
                        _json_mod.dump({"session_id": session_id, "bad_msgs": bad_msgs, "messages": api_messages}, _f, indent=2, default=str)
                    logger.error("[LLM] Bad messages before LLM call — payload saved to %s. Issues: %s", payload_path, bad_msgs)
                except Exception as save_err:
                    logger.error("[LLM] Bad messages before LLM call (failed to save payload): %s. Issues: %s", save_err, bad_msgs)
                # Force-fix every bad message so the call has a chance
                for i, msg in enumerate(api_messages):
                    content = msg.get('content')
                    if content is None or (isinstance(content, str) and not content.strip()):
                        msg['content'] = '(no output)'
            
            try:
                stream = await self._client.chat.completions.create(
                    model=self._llm_model,
                    messages=api_messages,
                    tools=tools or None,
                    stream=True,
                )
            except Exception as e:
                # Save the EXACT payload on API errors so we can reproduce exactly
                import os as _os
                import pathlib as _pathlib
                debug_dir = _os.path.expanduser("~/.riven/logs/bad_payloads")
                _os.makedirs(debug_dir, exist_ok=True)
                ts_str = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')
                payload_path = _os.path.join(debug_dir, f"{ts_str}_{session_id[:16]}_llm_error.json")
                try:
                    with open(payload_path, 'w') as _f:
                        _json_mod.dump({"session_id": session_id, "error": str(e), "messages": api_messages}, _f, indent=2, default=str)
                    logger.error("[LLM] Call failed — full payload saved to %s. Error: %s", payload_path, e)
                except Exception:
                    logger.error("[LLM] Call failed for session=%s (payload save also failed): %s", session_id, e)
                error_msg = f"LLM call failed: {type(e).__name__}: {e}. Session={session_id}"
                try:
                    db.add("tool", error_msg, session=session_id)
                except Exception as store_err:
                    logger.error("[DB] Failed to store LLM error to context DB: %s", store_err)
                yield {"error": error_msg}
                return

            # --- Collect the complete assistant message ---
            assistant_msg = {"tool_calls": []}
            _debug("run_stream: waiting for LLM stream chunks", session_id)
            _chunk_count = 0

            async for chunk in stream:
                _chunk_count += 1
                if self._cancelled:
                    error_msg = f"Execution was cancelled by user. Session={session_id}"
                    logger.info("[Core] Session=%s cancelled by user", session_id)
                    try:
                        db.add("tool", error_msg, session=session_id)
                    except Exception as store_err:
                        logger.warning("[DB] Failed to store cancel error: %s", store_err)
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

            _debug(f"run_stream: LLM stream complete ({_chunk_count} chunks, took {time.time()-_llm_start:.3f}s)", session_id)
            # --- Parse calls ---
            calls = self._parse_calls(assistant_msg)

            # --- No tool calls — done ---
            if not calls:
                _debug("run_stream: no tool calls, done", session_id)
                assistant_msg["role"] = "assistant"
                if assistant_msg.get("content", "").strip():
                    self._store_assistant(db, assistant_msg, session_id)
                    safe_msg = _json_safe(assistant_msg)
                    yield {"assistant": safe_msg}
                yield {"done": True}
                _debug(f"run_stream: ← EXIT (done) total={time.time()-_rs_start:.3f}s", session_id)
                return

            # --- Store assistant message BEFORE executing tools ---
            _debug(f"run_stream: executing {len(calls)} tool call(s): {[c.name for c in calls]}", session_id)
            assistant_msg["role"] = "assistant"
            self._store_assistant(db, assistant_msg, session_id)

            # --- Execute tool calls ---
            results: list[FunctionResult] = []
            for call in calls:
                if self._cancelled:
                    error_msg = f"Execution was cancelled by user. Session={session_id}"
                    try:
                        db.add("error", error_msg, session=session_id)
                    except Exception as store_err:
                        logger.warning(f"Failed to store cancel error: {store_err}")
                    yield {"error": error_msg}
                    return

                if len(results) + 1 > self._max_function_calls:
                    error_msg = f"Max function calls reached ({self._max_function_calls}). Session={session_id}"
                    logger.warning("[Core] Session=%s hit max function calls (%d)", session_id, self._max_function_calls)
                    try:
                        db.add("tool", error_msg, session=session_id)
                    except Exception as store_err:
                        logger.warning("[DB] Failed to store max-calls error: %s", store_err)
                    yield {"error": error_msg}
                    return

                yield {"tool_call": {
                    "id": call.id, 
                    "name": call.name, 
                    "arguments": call.arguments
                }}
                
                _tool_exec_start = time.time()
                result = await self._execute(call, func_index, session_id)
                _debug(f"run_stream: tool '{call.name}' executed ({time.time()-_tool_exec_start:.3f}s), error={result.error}", session_id)
                results.append(result)

                result_content = result.content if not result.error else f"ERROR: {result.error}"
                yield {"tool_result": {
                    "id": result.call_id, 
                    "name": result.name,
                    "content": result.content, 
                    "error": result.error,
                }}

                # Store tool result to memory API
                # Guard against empty content - MiniMax rejects messages with no content
                if not result_content:
                    result_content = "(no output)"
                    _debug(f"run_stream: tool result was empty, using '(no output)' instead", session_id)
                
                _debug(f"run_stream: storing tool result to context DB", session_id)
                _mem_store_start = time.time()
                try:
                    db.add(
                        "tool",
                        result_content,
                        session=session_id,
                        tool_call_id=result.call_id,
                        function=result.name
                    )
                    _debug(f"run_stream: tool result stored ({time.time()-_mem_store_start:.3f}s)", session_id)
                except Exception as e:
                    logger.error("[DB] Failed to store tool result for '%s': %s", result.name, e, exc_info=True)

            # --- Yield assistant message ---
            safe_assistant_msg = _json_safe(assistant_msg)
            yield {"assistant": safe_assistant_msg}

            # Signal that context was rebuilt and control returns to harness
            yield {"context_rebuilt": True}
            _debug(f"run_stream: ← EXIT (context_rebuilt) total={time.time()-_rs_start:.3f}s", session_id)

        finally:
            try:
                _session_id.reset(token)
            except ValueError:
                pass
