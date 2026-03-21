"""Module system for riven."""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Module:
    """A riven module with optional enrollment and context functionality.
    
    Rules:
    - If functions present → enrollment MUST be present
    - If get_context present → tag MUST be present
    - Must have at least one set (functions+enrollment OR get_context+tag)
    - Can have both sets
    """
    name: str
    enrollment: Callable | None = None  # Required if functions present
    functions: dict[str, Callable] = field(default_factory=dict)  # Required if enrollment present
    get_context: Callable[[], Any] | None = None  # Required if tag present
    tag: str | None = None  # Required if get_context present
    
    def __post_init__(self):
        has_functions = bool(self.functions)
        has_enrollment = self.enrollment is not None
        has_context = self.get_context is not None
        has_tag = self.tag is not None
        
        # Validate rules
        if has_functions and not has_enrollment:
            raise ValueError(f"Module {self.name}: functions requires enrollment")
        if has_enrollment and not has_functions:
            raise ValueError(f"Module {self.name}: enrollment requires functions")
        if has_context and not has_tag:
            raise ValueError(f"Module {self.name}: get_context requires tag")
        if has_tag and not has_context:
            raise ValueError(f"Module {self.name}: tag requires get_context")
        
        # Must have at least one set
        if not (has_functions or has_context):
            raise ValueError(f"Module {self.name}: must have either functions or get_context")


class ModuleRegistry:
    """Registry for riven modules."""
    
    def __init__(self):
        self._modules: dict[str, Module] = {}
        self._enrolled: bool = False
    
    def register(self, module: Module) -> None:
        """Register a module.
        
        If module has enrollment, it will be called.
        """
        self._modules[module.name] = module
        
        # Run enrollment if present
        if module.enrollment:
            module.enrollment()
    
    def get(self, name: str) -> Module | None:
        """Get a module by name."""
        return self._modules.get(name)
    
    def all(self) -> dict[str, Module]:
        """Get all modules."""
        return self._modules.copy()
    
    def get_functions(self) -> list[tuple[str, Callable, str]]:
        """Get all functions from enrolled modules.
        
        Returns:
            List of (name, function, description) tuples
        """
        functions = []
        for module in self._modules.values():
            if module.functions:
                # Get functions with their descriptions
                for name, func in module.functions.items():
                    desc = getattr(func, '__doc__', '') or ''
                    functions.append((name, func, desc.strip().split('\n')[0]))
        return functions
    
    def build_context(self) -> dict[str, Any]:
        """Build context from all modules with get_context.
        
        Returns:
            Dict of tag -> context value
        """
        context = {}
        for module in self._modules.values():
            if module.get_context and module.tag:
                try:
                    context[module.tag] = module.get_context()
                except Exception:
                    context[module.tag] = None
        return context


# Global registry
registry = ModuleRegistry()
