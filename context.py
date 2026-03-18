"""
Agent Context - stores all interactions for ReAct pattern.

Manages tool definitions, execution history, and builds context for the LLM.
"""

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from module import Module


class ToolExecution:
    """Records a single tool execution."""
    
    def __init__(self, name: str, args: Dict[str, Any], result: Any):
        self.name = name
        self.args = args
        self.result = result
    
    def __str__(self) -> str:
        return f"{self.name}({self.args}) -> {self.result}"


class AgentContext:
    """Context container for the agent loop.
    
    Stores:
    - Tool definitions (what functions are available)
    - Modules (for calling info() to replace tags)
    - Execution history (what was called and what happened)
    - Current observations
    """
    
    def __init__(self):
        self._tool_definitions: Dict[str, List[Dict]] = {}
        self._modules: List["Module"] = []  # Track modules for tag replacement
        self._executions: List[ToolExecution] = []
        self._max_history: int = 100  # Limit history size
        self._tags: Dict[str, str] = {}  # Cache of tag -> info replacements
    
    # --- Tool Definitions ---
    
    def set_tool_definitions(self, definitions: Dict[str, List[Dict]]) -> None:
        """Set all tool definitions at once."""
        self._tool_definitions = definitions
    
    def add_module(self, module: "Module") -> None:
        """Add a module for tag replacement."""
        self._modules.append(module)
        # Extract tag from module's TAG attribute
        if hasattr(module, 'TAG') and module.TAG:
            self._update_tag(module.TAG, module)
    
    def _update_tag(self, tag: str, module: "Module") -> None:
        """Update a tag with the module's info()."""
        info = module.info()
        if info is not None:
            self._tags[tag] = str(info)
        else:
            self._tags[tag] = ""
    
    def refresh_tags(self) -> None:
        """Refresh all tags from module info() calls."""
        for module in self._modules:
            if hasattr(module, 'TAG') and module.TAG:
                self._update_tag(module.TAG, module)
    
    def get_tags(self) -> Dict[str, str]:
        """Get all current tag replacements."""
        return self._tags.copy()
    
    def get_tool_definitions(self) -> Dict[str, List[Dict]]:
        """Get all tool definitions."""
        return self._tool_definitions.copy()
    
    def get_tools_description(self) -> str:
        """Get formatted description of available tools with usage info."""
        seen = set()
        lines = []
        for tool_name, defs in self._tool_definitions.items():
            for d in defs:
                name = d.get("name", "")
                # Skip if we've already seen this tool (dedupe)
                if name in seen:
                    continue
                seen.add(name)
                desc = d.get("description", "")
                
                # Add parameter info if available
                params = d.get("parameters", {})
                props = params.get("properties", {})
                required = params.get("required", [])
                
                param_info = []
                for param_name, param_def in props.items():
                    p_desc = param_def.get("description", "")
                    p_type = param_def.get("type", "any")
                    required_mark = "(required)" if param_name in required else "(optional)"
                    param_info.append(f"  - {param_name} ({p_type}) {required_mark}: {p_desc}")
                
                # Build the line
                line = f"- {name}: {desc}"
                if param_info:
                    line += "\n" + "\n".join(param_info)
                lines.append(line)
        
        return "\n".join(lines) if lines else "No tools available"
    
    # --- Execution History ---
    
    def add_execution(self, name: str, args: Dict[str, Any], result: Any) -> None:
        """Add a tool execution to history."""
        self._executions.append(ToolExecution(name, args, result))
        # Trim if too long
        if len(self._executions) > self._max_history:
            self._executions = self._executions[-self._max_history:]
    
    def get_execution_history(self) -> List[ToolExecution]:
        """Get all executions."""
        return self._executions.copy()
    
    def get_observations(self) -> str:
        """Get formatted observation history for the prompt."""
        if not self._executions:
            return "No observations yet."
        
        lines = []
        for exec in self._executions:
            lines.append(f"- {exec.name}({exec.args}) -> {exec.result}")
        return "\n".join(lines)
    
    def clear_history(self) -> None:
        """Clear execution history."""
        self._executions.clear()
    
    # --- Context Building for ReAct ---
    
    def build_reasoning_context(self) -> Dict[str, Any]:
        """Build context for the reasoning step (what to think about)."""
        return {
            "tools": self.get_tools_description(),
            "observations": self.get_observations(),
            "iteration": len(self._executions),
        }
    
    def build_action_context(self, reasoning: str) -> Dict[str, Any]:
        """Build context for the action step (given reasoning, what to do)."""
        return {
            "tools": self.get_tools_description(),
            "observations": self.get_observations(),
            "reasoning": reasoning,
            "iteration": len(self._executions),
        }
    
    def build_final_context(self) -> Dict[str, Any]:
        """Build full context for final step."""
        return {
            "tools": self.get_tools_description(),
            "observations": self.get_observations(),
            "iteration": len(self._executions),
        }
    
    def __len__(self) -> int:
        return len(self._executions)
