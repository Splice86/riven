"""
Agentic Loop - autonomous agent that runs in a background thread.

Uses ReAct pattern: Reason -> Act -> Observe -> loop

Simple API:
- Create loop
- Register modules  
- Call start() to begin the agent loop
- Call stop() to stop it
"""

import threading
import time
from typing import Callable, Dict, Any, List, Tuple, Optional

from module import Module
from registry import ModuleRegistry
from llm import LlamaCppClient, create_reasoner
from context import AgentContext


class AgenticLoop:
    """Autonomous agentic loop that runs in a background thread.
    
    Simple flow:
    1. Create the loop
    2. Register modules (add tools)
    3. Call start() to begin the ReAct loop
    4. Call stop() when done
    """
    
    def __init__(
        self,
        reasoner: Callable[[Dict[str, Any], Any], List[Tuple[str, Dict[str, Any]]]] | None = None,
        main_prompt: str = "",
        llm_client: LlamaCppClient | None = None,
        max_iterations: Optional[int] = None,
        loop_delay: float = 0.5
    ):
        """Initialize the agentic loop.
        
        Args:
            reasoner: Function that takes (context_dict, context_obj) and returns (function_name, args)
                      If None, uses LLM client to create a ReAct reasoner
            main_prompt: The base prompt with {{tag}} placeholders
            llm_client: LLM client to use for the reasoner (defaults to llama.cpp at 192.168.1.11:8010)
            max_iterations: Optional max iterations (None = unlimited)
            loop_delay: Delay between loop iterations (seconds)
        """
        # Create reasoner - either provided or from LLM client
        if reasoner is not None:
            self._reasoner = reasoner
        elif llm_client is not None:
            self._reasoner = create_reasoner(llm_client)
        else:
            # Default: use the default llama.cpp client
            self._reasoner = create_reasoner()
        
        self._main_prompt = main_prompt
        self._max_iterations = max_iterations
        self._loop_delay = loop_delay
        
        self._registry = ModuleRegistry()
        self._context = AgentContext()
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._exit_requested = False
    
    # --- Module registration ---
    
    def register_module(self, module: Module, name: str | None = None) -> None:
        """Register a module with the loop.
        
        Call this BEFORE start() to make tools available to the agent.
        """
        with self._lock:
            self._registry.register(module, name)
            # Update context with tool definitions
            self._context.set_tool_definitions(self._registry.get_all_definitions())
            # Add module for tag replacement
            self._context.add_module(module)
    
    # --- Control methods ---
    
    def start(self) -> None:
        """Start the agentic loop in a background thread.
        
        Call this AFTER registering all modules.
        """
        if self._running:
            return
        
        with self._lock:
            self._running = True
            self._exit_requested = False
        
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
    
    def stop(self, timeout: float = 5.0) -> None:
        """Stop the agentic loop gracefully."""
        with self._lock:
            self._running = False
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
    
    # --- Query methods ---
    
    def get_context(self) -> AgentContext:
        """Get the agent context."""
        with self._lock:
            return self._context
    
    def is_running(self) -> bool:
        """Check if the loop is running."""
        with self._lock:
            return self._running
    
    # --- Internal loop ---
    
    def _run_loop(self) -> None:
        """Main ReAct loop that runs in the background thread."""
        iteration = 0
        
        while self._running:
            # Check if exit requested
            if self._exit_requested:
                break
            
            # Check max iterations
            if self._max_iterations and iteration >= self._max_iterations:
                break
            
            try:
                # Refresh tags from modules
                self._context.refresh_tags()
                
                # Replace tags in main_prompt
                prompt = self._main_prompt
                tags = self._context.get_tags()
                for tag_name, tag_value in tags.items():
                    prompt = prompt.replace(f"{{{{{tag_name}}}}}", tag_value)
                
                # Build context for ReAct
                context_dict = self._context.build_reasoning_context()
                context_dict["prompt"] = prompt
                
                # Call reasoner - returns list of (function_name, args)
                calls = self._reasoner(context_dict, self._context)
                
                # Skip if no calls returned
                if not calls:
                    print("[AgenticLoop] No actions decided, pausing")
                    time.sleep(self._loop_delay)
                    continue
                
                # Execute each call in order
                with self._lock:
                    for function_name, args in calls:
                        # Handle exit specially
                        if function_name.lower() == "exit":
                            print("[AgenticLoop] Exit requested")
                            self._exit_requested = True
                            break
                        
                        result = self._execute_function(function_name, args)
                        print(f"[AgenticLoop] {function_name} -> {result}")
                        
                        # Add to context as observation
                        self._context.add_execution(function_name, args, result)
                
                # Check if exit was requested
                if self._exit_requested:
                    break
                
                iteration += 1
                
                # Small delay between iterations
                time.sleep(self._loop_delay)
                
            except Exception as e:
                print(f"[AgenticLoop] Error: {e}")
                with self._lock:
                    self._context.add_execution("error", {}, str(e))
    
    def _execute_function(self, function_name: str, args: Dict[str, Any]) -> Any:
        """Execute a function from the registry."""
        if not function_name:
            return None
        
        # Handle exit specially
        if function_name.lower() == "exit":
            self._exit_requested = True
            return "Exiting"
        
        func = self._registry.get_function(function_name)
        if func is None:
            return f"Function '{function_name}' not found"
        
        try:
            return func(**args)
        except TypeError as e:
            return f"Error calling {function_name}: {e}"

    # --- Legacy compatibility ---
    
    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Get conversation history (legacy compatibility)."""
        with self._lock:
            return [
                {"function": e.name, "args": e.args, "result": e.result}
                for e in self._context.get_execution_history()
            ]
