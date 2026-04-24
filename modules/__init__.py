"""Module system for temp_riven.

Two function types:
1. Context functions - run automatically, inject into system context
   - Has a tag that gets replaced in system prompt after each tool call
2. Called functions - exposed to LLM, LLM decides when to call
   - Has name, description, parameters

Session ID is automatically injected via context_var - no need to pass it.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable
import time as _stdlib_time  # noqa: E402 - alias to avoid collision with modules.time subpackage

# Session ID automatically available in all module functions
_session_id: ContextVar[str] = ContextVar('session_id', default='')

# High-level debug flag
DEBUG_HANG = True

def _debug(step: str, session_id: str = None) -> None:
    """Print timestamped debug messages to trace execution flow."""
    if not DEBUG_HANG:
        return
    ts = _stdlib_time.time()
    # Fall back to contextvar if not passed explicitly
    sid = f"[{session_id[:8]}]" if session_id else f"[{get_session_id()[:8]}]" if get_session_id() else "[--------]"
    print(f"[DEBUG {ts:.3f}] {sid} {step}", flush=True)


def get_session_id() -> str:
    """Get current session ID from context."""
    return _session_id.get()


@dataclass
class CalledFn:
    """A function the LLM can call."""
    name: str
    description: str
    parameters: dict  # JSON schema
    fn: Callable
    timeout: float | None = None  # None = use shard's tool_timeout

    def __post_init__(self):
        """Ensure _timeout parameter is in schema for per-call override."""
        props = self.parameters.get('properties', {})
        if '_timeout' not in props:
            props['_timeout'] = {
                'type': 'integer',
                'description': 'Optional timeout override in seconds for this tool call',
            }
            self.parameters['properties'] = props
        
        # Remove empty required array - some APIs don't like it
        if 'required' in self.parameters and not self.parameters['required']:
            del self.parameters['required']


@dataclass
class ContextFn:
    """A function that runs automatically and injects into context.
    
    The tag is replaced in the system prompt using {tag} syntax.
    Example: tag="time" → replaces {time} in system prompt
    
    Static vs Dynamic:
    - static=True: Returns unchanging data (tool docs, usage tips). Placed at top.
    - static=False (default): Returns session-dependent data (open files, cwd). Placed after statics.
    """
    tag: str  # e.g., "time" → replaces {time} in system prompt
    fn: Callable  # Returns content to inject
    static: bool = False  # True if content never changes between calls


@dataclass
class Module:
    """A module with optional called functions and/or context functions."""
    name: str
    called_fns: list[CalledFn] = field(default_factory=list)
    context_fns: list[ContextFn] = field(default_factory=list)


# =============================================================================
# Module Registry
# =============================================================================

class ModuleRegistry:
    """Registry for modules and their functions."""

    def __init__(self):
        self._modules: dict[str, Module] = {}

    def register(self, module: Module) -> None:
        """Register a module."""
        self._modules[module.name] = module

    def get_module(self, name: str) -> Module | None:
        """Get a module by name."""
        return self._modules.get(name)

    def all_modules(self) -> list[Module]:
        """Get all modules."""
        return list(self._modules.values())

    def get_called_fns(self) -> list[CalledFn]:
        """Get all called functions from all modules."""
        funcs = []
        for module in self._modules.values():
            funcs.extend(module.called_fns)
        return funcs

    def build_context(self) -> dict[str, str]:
        """Run all context functions and return {tag: content}."""
        _debug(f"ModuleRegistry.build_context: starting ({len(self._modules)} modules)")
        context = {}
        for module in self._modules.values():
            for ctx_fn in module.context_fns:
                try:
                    _debug(f"ModuleRegistry.build_context: calling {ctx_fn.tag}() from {module.name}")
                    result = ctx_fn.fn()
                    content_preview = repr(result[:80]) if result else repr(result)
                    _debug(f"ModuleRegistry.build_context: {ctx_fn.tag}() -> {content_preview}")
                    context[ctx_fn.tag] = result
                except Exception as e:
                    _debug(f"ModuleRegistry.build_context: {ctx_fn.tag}() FAILED: {e}")
                    context[ctx_fn.tag] = f"[Error: {e}]"
        _debug(f"ModuleRegistry.build_context: done, tags={list(context.keys())}")
        return context


# Global registry
registry = ModuleRegistry()

__all__ = ['Module', 'CalledFn', 'ContextFn', 'ModuleRegistry', 'registry', '_session_id', 'get_session_id']
