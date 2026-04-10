"""Core agentic loop - pydantic_ai implementation."""

import asyncio
import logging
import os
from typing import Any

import requests
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import Tool as PydanticTool
from openai import AsyncOpenAI

from modules import ModuleRegistry, get_all_modules

logger = logging.getLogger(__name__)

MEMORY_API_URL = os.environ.get("MEMORY_API_URL", "http://127.0.0.1:8030")

# LLM config - try config.py first, fallback to defaults
try:
    from config import LLM_URL, LLM_API_KEY, LLM_MODEL, DEFAULT_DB
except ImportError:
    LLM_URL = "http://127.0.0.1:8000/v1/"
    LLM_API_KEY = "sk-dummy"
    LLM_MODEL = "nvidia/MiniMax-M2.5-NVFP4"
    DEFAULT_DB = "default"


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
    """Simple agent using pydantic_ai with llama.cpp backend."""

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
        self.db_name = db_name
        self.system_prompt = system_prompt or ""

        self._modules = ModuleRegistry()
        self._memory = MemoryClient(db_name=db_name)
        
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

    async def _run_with_retry(self, system_prompt: str, prompt: str) -> Any:
        """Run a single iteration with retry logic using agent.iter()."""
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                agent = self._create_agent(system_prompt)
                
                # Use agent.iter() for structured node access
                async with agent.iter(prompt) as agent_run:
                    async for node in agent_run:
                        self._process_node(node)
                    
                    # Get final result
                    result = agent_run.result
                    return result
                    
            except Exception as e:
                last_error = e
                
                logger.warning(f"Retry {attempt + 1}: {e}")
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
        
        raise last_error

    def _process_node(self, node) -> None:
        """Process a single node from agent.iter()."""
        node_name = type(node).__name__
        
        match node_name:
            case 'CallToolsNode':
                response = node.model_response
                if response and response.parts:
                    for part in response.parts:
                        if hasattr(part, 'tool_name'):
                            tool_results = node.tool_call_results or {}
                            tool_result = tool_results.get(part.tool_name)
                            result_str = str(tool_result) if tool_result else "Done"
                            
                            # Log full result to memory
                            self._memory.add_context("tool", f"{part.tool_name}: {result_str}")
                            
                            # Show command + truncated result to user
                            args_str = str(part.args) if part.args else ""
                            if len(result_str) > 500:
                                display_str = result_str[:500] + f"\n... ({len(result_str) - 500} more chars)"
                            else:
                                display_str = result_str
                            logger.info(f"→ {part.tool_name}{args_str}: {display_str}")

    def _build_system_prompt(self) -> str:
        """Build system prompt with module context."""
        prompt = self.system_prompt
        
        # Add module context replacements
        for module in self._modules.all().values():
            if module.get_context and module.tag:
                value = module.get_context()
                prompt = prompt.replace(f"{{{module.tag}}}", value)
        
        return prompt

    def _build_prompt(self, user_input: str) -> str:
        """Build prompt. Currently just returns user input.
        
        Context handling is done via memory API separately.
        """
        return user_input

    async def run(self, prompt: str) -> Any:
        """Run the agent with the given prompt."""
        # Build prompts first (don't add to memory until success)
        system_prompt = self._build_system_prompt()
        full_prompt = self._build_prompt(prompt)
        
        # Run agent
        result = await self._run_with_retry(system_prompt, full_prompt)
        
        # Only add to memory after successful run
        self._memory.add_context("user", prompt)
        self._memory.add_context("assistant", str(result.output))
        
        return result


async def main():
    """Interactive REPL for the agent."""
    system_prompt = """You are a helpful AI assistant."""

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