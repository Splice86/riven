"""
Module registry - stores and manages modules for the agentic loop.
"""

from typing import Callable, Dict, List, Any
from module import Module


class ModuleRegistry:
    """Registry for managing modules in the agentic loop."""
    
    def __init__(self):
        self._modules: Dict[str, Module] = {}
        self._functions: Dict[str, Callable] = {}
        self._definitions: Dict[str, List[Dict[str, Any]]] = {}
    
    def register(self, module: Module, name: str | None = None) -> None:
        """Register a module.
        
        Args:
            module: The module to register
            name: Optional name (defaults to class name)
        """
        if name is None:
            name = module.__class__.__name__
        
        self._modules[name] = module
        
        # Register its functions and definitions
        functions = module.get_functions()
        for func_name, func in functions.items():
            if func_name in self._functions:
                print(f"[ModuleRegistry] Warning: Function '{func_name}' from module '{name}' overwrites existing function")
            self._functions[func_name] = func
        
        # Get definitions
        defs = module.definitions()
        if defs:
            self._definitions[name] = defs
            # Also add individual function defs for lookup
            for d in defs:
                func_name_key = d.get('name', '')
                if func_name_key:
                    self._definitions[func_name_key] = [d]
    
    def get_module(self, name: str) -> Module | None:
        """Get a module by name."""
        return self._modules.get(name)
    
    def get_all_modules(self) -> Dict[str, Module]:
        """Get all registered modules."""
        return self._modules.copy()
    
    def get_function(self, name: str) -> Callable | None:
        """Get a function by name."""
        return self._functions.get(name)
    
    def get_all_functions(self) -> Dict[str, Callable]:
        """Get all registered functions."""
        return self._functions.copy()
    
    def get_definitions(self, module_name: str) -> List[Dict[str, Any]]:
        """Get definitions for a specific module."""
        return self._definitions.get(module_name, [])
    
    def get_all_definitions(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all definitions."""
        return self._definitions.copy()
    
    def collect_infos(self) -> Dict[str, str | Dict[str, Any] | None]:
        """Collect info() output from all modules."""
        infos = {}
        for name, module in self._modules.items():
            infos[name] = module.info()
        return infos
    
    def __len__(self) -> int:
        return len(self._modules)
    
    def __iter__(self):
        return iter(self._modules.values())
