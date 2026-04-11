"""Core agentic loop - pydantic_ai implementation."""

import asyncio
import logging
import os
import re
from typing import Any

import requests
import yaml
from pydantic_ai import Agent
from pydantic_ai import AgentStreamEvent, AgentRunResultEvent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
    TextPart,
    PartStartEvent,
    PartEndEvent,
    PartDeltaEvent,
    ThinkingPart,
    ThinkingPartDelta,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import Tool as PydanticTool
from openai import AsyncOpenAI

from modules import ModuleRegistry, get_all_modules
from tools import create_tools

logger = logging.getLogger(__name__)

# Load configuration
def _load_config() -> dict:
    """Load config from yaml files."""
    config = {}
    
    # Try config_local.yaml first (gitignored, for local overrides)
    for config_file in ['config_local.yaml', 'config.yaml']:
        if os.path.exists(config_file):
            with open(config_file) as f:
                loaded = yaml.safe_load(f)
                if loaded:
                    config.update(loaded)
    
    return config

CONFIG = _load_config()


# Legacy env/import fallback
MEMORY_API_URL = os.environ.get("MEMORY_API_URL", CONFIG.get('memory_api', {}).get('url', "http://127.0.0.1:8030"))

try:
    from config import LLM_URL, LLM_API_KEY, LLM_MODEL, DEFAULT_DB, MAX_OUTPUT_LINES
except ImportError:
    LLM_URL = CONFIG.get('llm', {}).get('url', "http://127.0.0.1:8000/v1/")
    LLM_API_KEY = CONFIG.get('llm', {}).get('api_key', "sk-dummy")
    LLM_MODEL = CONFIG.get('llm', {}).get('model', "nvidia/MiniMax-M2.5-NVFP4")
    DEFAULT_DB = CONFIG.get('memory_api', {}).get('db_name', "default")
    MAX_OUTPUT_LINES = 1000


class MemoryClient:
    """Simple client for memory API context endpoints."""
    
    def __init__(self, db_name: str = "default", base_url: str = MEMORY_API_URL):
        self.db_name = db_name or DEFAULT_DB
        self.base_url = base_url
    
    def add_context(self, role: str, content: str, created_at: str = None) -> dict:
        """Add a context message."""
        resp = requests.post(
            f"{self.base_url}/context",
            params={"db_name": self.db_name},
            json={"role": role, "content": content, "created_at": created_at}
        )
        resp.raise_for_status()
        return resp.json()
    
    def get_context(self, limit: int = 100) -> list[dict]:
        """Get context for prompt."""
        resp = requests.get(
            f"{self.base_url}/context",
            params={"db_name": self.db_name, "limit": limit}
        )
        resp.raise_for_status()
        return resp.json().get("context", [])


class Core:
    """Agent core using pydantic_ai with vllm backend.
    
    Can be initialized with a config dict (from cores.yaml) or individual params.
    """

    def __init__(
        self,
        config: dict = None,
        model: str = None,
        system_prompt: str = None,
        llm_url: str = None,
        llm_api_key: str = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        db_name: str = None,
        tools: list = None,
        tool_timeout: int = 20,
        strip_thinking: bool = False
    ):
        # Load from config if provided
        if config:
            self.model = config.get('llm_model') or config.get('llm_model', LLM_MODEL)
            self.llm_url = config.get('llm_url', LLM_URL)
            self.llm_api_key = config.get('llm_api_key', LLM_API_KEY)
            self.system_prompt = config.get('system_prompt', '')
            self.db_name = config.get('memory_db', DEFAULT_DB)
            self._tool_filter = config.get('tools', None)
            self.tool_timeout = config.get('tool_timeout', 20)
            self.strip_thinking = config.get('strip_thinking', False)
        else:
            self.model = model or LLM_MODEL
            self.llm_url = llm_url or LLM_URL
            self.llm_api_key = llm_api_key or LLM_API_KEY
            self.system_prompt = system_prompt or ""
            self.db_name = db_name or DEFAULT_DB
            self._tool_filter = tools
            self.tool_timeout = tool_timeout
            self.strip_thinking = strip_thinking
        
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._cancelled = False

        self._modules = ModuleRegistry()
        self._memory = MemoryClient(db_name=self.db_name, base_url=MEMORY_API_URL)
        
        # Register modules based on tool filter
        self._register_modules()
    
    def _register_modules(self) -> None:
        """Register modules, optionally filtering by tool list."""
        all_modules = get_all_modules()
        
        for module in all_modules:
            # Handle "all" case
            if self._tool_filter is None or 'all' in self._tool_filter:
                self._modules.register(module)
            elif module.name in self._tool_filter:
                self._modules.register(module)
    
    def cancel(self) -> None:
        """Cancel any ongoing operation."""
        self._cancelled = True
    
    def _create_agent(self, system_prompt: str) -> Agent:
        """Create a pydantic_ai Agent."""
        client = AsyncOpenAI(base_url=self.llm_url, api_key=self.llm_api_key)
        provider = OpenAIProvider(openai_client=client)
        model = OpenAIChatModel(model_name=self.model, provider=provider)
        
        # Get functions from registered modules
        module_funcs = self._modules.get_functions()
        tools = create_tools(module_funcs, self.tool_timeout)
        
        return Agent(
            model=model,
            system_prompt=system_prompt,
            tools=tools
        )

    # Remove old _wrap_tool method - now in tools.py

    async def _run_with_retry(self, system_prompt: str, prompt: str, message_history: list[ModelMessage] = None) -> Any:
        """Run agent with streaming events for real-time tool output."""
        last_error = None
        tool_results = []  # Track tool results for memory
        pending_tool = None  # Buffer for tool call awaiting result
        message_history = message_history or []
        
        # Buffers for streaming content
        _thinking_buffer = ""
        _thinking_printed = False
        _streamed_text = ""  # Track text already streamed
        
        # Reset cancelled flag at start
        self._cancelled = False
        
        for attempt in range(self.max_retries):
            try:
                agent = self._create_agent(system_prompt)
                
                # Use run_stream_events() for real-time tool output
                # Pass message_history to inject our memory context
                async for event in agent.run_stream_events(prompt, message_history=message_history):
                    # Check for cancellation
                    if self._cancelled:
                        return None
                    
                    # Handle thinking/reasoning content
                    if isinstance(event, PartStartEvent):
                        part = event.part
                        if isinstance(part, ThinkingPart):
                            # Start of thinking - print thinking header
                            _thinking_buffer = part.content
                            if _thinking_buffer:
                                print("\n🤔 Thinking...", flush=True)
                                _thinking_printed = True
                        elif hasattr(part, 'content'):
                            # Stream text content, converting thinking tags for display
                            text = part.content.replace('<think>', '\nThinking: ').replace('</think>', '')
                            _streamed_text += part.content
                            print(text, end="", flush=True)
                            
                    elif isinstance(event, PartDeltaEvent):
                        delta = event.delta
                        if isinstance(delta, ThinkingPartDelta):
                            # Streaming thinking content
                            if delta.content_delta:
                                _thinking_buffer += delta.content_delta
                                if _thinking_printed:
                                    print(delta.content_delta, end="", flush=True)
                        elif hasattr(delta, 'content_delta') and delta.content_delta:
                            # Stream text delta, converting thinking tags for display
                            text = delta.content_delta.replace('<think>', '\nThinking: ').replace('</think>', '')
                            _streamed_text += delta.content_delta
                            print(text, end="", flush=True)
                            
                    elif isinstance(event, PartEndEvent) and isinstance(event.part, ThinkingPart):
                        # End of thinking - clear buffer
                        _thinking_buffer = ""
                        _thinking_printed = False
                        # Add newline after thinking output
                        print(flush=True)
                        
                    elif isinstance(event, FunctionToolCallEvent):
                        # Buffer tool call - will print with result
                        # Add newline before tool output for clean separation
                        print(flush=True)
                        args = event.part.args
                        tool_name = event.part.tool_name
                        pending_tool = {"name": tool_name, "args": args}
                        
                    elif isinstance(event, FunctionToolResultEvent):
                        # Tool returned - print call + result together
                        content = event.result.content
                        tool_name = event.result.tool_name
                        
                        # Handle both string and non-string content
                        if hasattr(content, 'content'):
                            content = content.content
                        content_str = str(content) if content else ""
                        
                        # Print call + result as one block
                        if pending_tool:
                            print(f"→ {pending_tool['name']}{pending_tool['args']}", flush=True)
                            pending_tool = None
                        
                        # Store FULL result in memory
                        tool_results.append({
                            "tool": tool_name,
                            "result": content_str
                        })
                        
                        # Truncate output for user display
                        lines = content_str.split('\n')
                        display_lines = lines[:10]  # Show first 10 lines
                        for line in display_lines:
                            print(f"  {line}", flush=True)
                        if len(lines) > 10:
                            print(f"  ... ({len(lines) - 10} more lines, {len(content_str)} total chars)", flush=True)
                        
                    elif isinstance(event, AgentRunResultEvent):
                        # Final result - store tool results in memory (don't print, already streamed)
                        for tr in tool_results:
                            self._memory.add_context(
                                "tool",
                                f"{tr['tool']}: {tr['result']}"
                            )
                        # Add newline at end of output
                        print(flush=True)
                        # Return result but don't print - already streamed above
                        return event.result
                        
            except asyncio.CancelledError:
                # Handle Ctrl+C interruption gracefully
                logger.info("Operation cancelled")
                return None
            except Exception as e:
                last_error = e
                
                logger.warning(f"Retry {attempt + 1}: {e}")
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
        
        raise last_error

    def _build_system_prompt(self) -> str:
        """Build system prompt with module context."""
        prompt = self.system_prompt
        
        # Add module context replacements
        for module in self._modules.all().values():
            if module.get_context and module.tag:
                value = module.get_context()
                prompt = prompt.replace(f"{{{module.tag}}}", value)
        
        return prompt

    def _build_prompt(self, user_input: str) -> tuple[str, list[ModelMessage]]:
        """Build prompt with memory context.
        
        Returns tuple of (user_prompt, message_history) where message_history
        contains the converted memory context.
        """
        # Get context from memory
        context = self._memory.get_context()
        
        if not context:
            return user_input, []
        
        # Convert memory context to pydantic_ai ModelMessage format
        message_history: list[ModelMessage] = []
        
        for msg in context:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if role == "user":
                message_history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
            elif role == "assistant":
                message_history.append(ModelResponse(parts=[TextPart(content=content)]))
            elif role == "tool":
                # Tools are inserted as assistant messages with tool result
                message_history.append(ModelResponse(parts=[TextPart(content=f"[Tool: {content}")]))
        
        return user_input, message_history

    async def run(self, prompt: str) -> Any:
        """Run the agent with the given prompt."""
        # Build prompts first (don't add to memory until success)
        system_prompt = self._build_system_prompt()
        user_prompt, message_history = self._build_prompt(prompt)
        
        # Run agent with message history injected
        result = await self._run_with_retry(system_prompt, user_prompt, message_history)
        
        # Strip thinking tags from output before storing in memory
        output_text = str(result.output)
        if self.strip_thinking:
            # Use regex to remove everything between thinking tags
            output_text = re.sub(r"<think>.*?</think>", "", output_text, flags=re.DOTALL).strip()
        else:
            output_text = output_text.replace("<think>", "").replace("</think>", "").strip()
        
        # Add user/assistant to memory after successful run
        self._memory.add_context("user", prompt)
        self._memory.add_context("assistant", output_text)
        
        return result


def get_core(name: str = "default") -> Core:
    """Factory function to create a core by name from config.
    
    Args:
        name: Name of the core in config (default: "default")
    
    Returns:
        Configured Core instance
    
    Raises:
        ValueError: If core name not found in config
    """
    cores = CONFIG.get('cores', {})
    
    if name not in cores:
        raise ValueError(f"Core '{name}' not found in config. Available: {list(cores.keys())}")
    
    return Core(config=cores[name])


def list_cores() -> list[str]:
    """List available core names from config."""
    return list(CONFIG.get('cores', {}).keys())


