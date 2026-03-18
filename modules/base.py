"""
Module base class for Agentic Loop.

A module is a class with:
- info() -> str | dict | None: returns data to inject into prompt
- definitions() -> list[dict]: returns tool definitions for LLM
- Your functions: actual callable methods
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, List


class Module(ABC):
    """Base class for all modules."""

    # Subclasses should override these
    TAG: str = ""  # Tag name for replacing {{tag}} in prompt (e.g., "time")

    
    @abstractmethod
    def info(self) -> str | dict | None:
        """Return data to inject into the main prompt as {{TAG}}.
        
        Return a string that will replace {{TAG}} in the prompt.
        Can return None if no info to inject.
        """
        pass

    @abstractmethod
    def definitions(self) -> list[dict]:
        """Return list of function definitions for the LLM.
        
        Each dict should have:
        - name: str - function name
        - description: str - what it does
        - parameters: dict (optional) - schema for args
        - tag: str (optional) - the prompt tag this module provides (e.g., "time")
        
        Return empty list [] if no functions to expose.
        """
        pass

    def get_functions(self) -> dict[str, Callable]:
        """Return dict mapping function names to callables.
        
        Override this to expose functions to the loop.
        Default returns all public methods (not info/definitions).
        """
        functions = {}
        
        for attr_name in dir(self):
            if attr_name.startswith('_'):
                continue
            if attr_name in ('info', 'definitions', 'get_functions'):
                continue
            
            attr = getattr(self, attr_name)
            if callable(attr):
                functions[attr_name] = attr
        
        return functions
