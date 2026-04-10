"""Core agentic loop - pydantic_ai implementation."""

import asyncio
import logging
import os
from typing import Any

import requests
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
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import Tool as PydanticTool
from openai import AsyncOpenAI

from modules import ModuleRegistry, get_all_modules

logger = logging.getLogger(__name__)

MEMORY_API_URL = os.environ.get("MEMORY_API_URL", "http://127.0.0.1:8030")

# Config - try config.py first, fallback to defaults
try:
    from config import LLM_URL, LLM_API_KEY, LLM_MODEL, DEFAULT_DB, MAX_OUTPUT_LINES
except ImportError:
    LLM_URL = "http://127.0.0.1:8000/v1/"
    LLM_API_KEY = "sk-dummy"
    LLM_MODEL = "nvidia/MiniMax-M2.5-NVFP4"
    DEFAULT_DB = "default"
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
    """Simple agent using pydantic_ai with vllm backend."""

    def __init__(
        self,
        model: str = None,
        system_prompt: str = None,
        llm_url: str = None,
        llm_api_key: str = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        db_name: str = None
    ):
        self.model = model or LLM_MODEL
        self.llm_url = llm_url or LLM_URL
        self.llm_api_key = llm_api_key or LLM_API_KEY
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.db_name = db_name or DEFAULT_DB
        self.system_prompt = system_prompt or ""

        self._modules = ModuleRegistry()
        self._memory = MemoryClient(db_name=self.db_name)
        
        # Auto-register all discovered modules
        for module in get_all_modules():
            self._modules.register(module)

    def _create_agent(self, system_prompt: str) -> Agent:
        """Create a pydantic_ai Agent."""
        client = AsyncOpenAI(base_url=self.llm_url, api_key=self.llm_api_key)
        provider = OpenAIProvider(openai_client=client)
        model = OpenAIChatModel(model_name=self.model, provider=provider)
        
        # Get functions from registered modules
        module_funcs = self._modules.get_functions()
        tools = [PydanticTool(func) for _, func, _ in module_funcs] if module_funcs else []
        
        return Agent(
            model=model,
            system_prompt=system_prompt,
            tools=tools
        )

    async def _run_with_retry(self, system_prompt: str, prompt: str, message_history: list[ModelMessage] = None) -> Any:
        """Run agent with streaming events for real-time tool output."""
        last_error = None
        tool_results = []  # Track tool results for memory
        pending_tool = None  # Buffer for tool call awaiting result
        message_history = message_history or []
        
        for attempt in range(self.max_retries):
            try:
                agent = self._create_agent(system_prompt)
                
                # Use run_stream_events() for real-time tool output
                # Pass message_history to inject our memory context
                async for event in agent.run_stream_events(prompt, message_history=message_history):
                    if isinstance(event, FunctionToolCallEvent):
                        # Buffer tool call - will print with result
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
                        # Final result - store tool results in memory
                        for tr in tool_results:
                            self._memory.add_context(
                                "tool",
                                f"{tr['tool']}: {tr['result']}"
                            )
                        return event.result
                        
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
        
        # Add user/assistant to memory after successful run
        self._memory.add_context("user", prompt)
        self._memory.add_context("assistant", str(result.output))
        
        return result


async def main():
    """Interactive REPL for the agent."""
    system_prompt = """You are a helpful AI assistant.

When reading files, use the open_document tool instead of shell commands like cat, less, or head. 
The file open tool provides better formatting and line numbering. Only use shell commands for 
executing programs or when you specifically need shell features (pipes, redirects, etc.)."""

    core = Core()
    
    print("Riven agent ready. Type 'quit' or 'exit' to stop.\n")
    
    while True:
        try:
            prompt = input("> ").strip()
            
            if prompt.lower() in ('quit', 'exit'):
                print("Goodbye!")
                break
            
            if not prompt:
                continue
            
            result = await core.run(prompt)
            print(f"\n{result.output}\n")
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}\n")


if __name__ == "__main__":
    # Suppress HTTP request logging from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())