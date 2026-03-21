"""Core agentic loop - pydantic_ai implementation."""

import asyncio
import logging
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import Tool as PydanticTool
from openai import AsyncOpenAI

from context import Context
from modules import ModuleRegistry, Module

logger = logging.getLogger(__name__)


class Core:
    """Simple agent using pydantic_ai with llama.cpp backend."""

    def __init__(
        self,
        model: str = "llama3",
        max_iterations: int | None = None,
        llm_url: str = "http://192.168.1.11:8010",
        llm_api_key: str = "sk-dummy",
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.model = model
        self.max_iterations = max_iterations
        self.llm_url = llm_url
        self.llm_api_key = llm_api_key
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._modules = ModuleRegistry()
        self._context = Context()
        self._result: Any = None
        self._iteration: int = 0

    @property
    def context(self) -> Context:
        """Access the conversation context."""
        return self._context

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt (stores original with tags for later replacement)."""
        self._context.set_system_prompt(prompt)

    def register_module(self, module: Module) -> None:
        """Register a module."""
        self._modules.register(module)

    def register_shell(self, timeout: int = 60) -> None:
        """Register the shell module."""
        from modules.shell import get_shell_module
        self.register_module(get_shell_module(timeout))

    def _create_agent(self, system_prompt: str) -> Agent:
        """Create a pydantic_ai Agent."""
        client = AsyncOpenAI(base_url=f"{self.llm_url}/v1", api_key=self.llm_api_key)
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

    async def _run_with_retry(self, prompt: str, system_prompt: str) -> Any:
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
        node_type = type(node).__name__
        
        # UserPromptNode - initial input
        if node_type == 'UserPromptNode':
            prompt = getattr(node, 'user_prompt', '')
            if prompt:
                logger.info(f"User: {str(prompt)[:50]}...")
        
        # ModelRequestNode - what was sent to LLM
        elif node_type == 'ModelRequestNode':
            request = getattr(node, 'request', None)
            if request and hasattr(request, 'parts') and request.parts:
                first_part = request.parts[0]
                content = getattr(first_part, 'content', str(first_part))
                logger.info(f"LLM: {str(content)[:50]}...")
        
        # CallToolsNode - tool execution
        elif node_type == 'CallToolsNode':
            model_response = getattr(node, 'model_response', None)
            
            thinking = ""
            if model_response and hasattr(model_response, 'parts'):
                for part in model_response.parts:
                    part_type = type(part).__name__
                    if part_type == 'ThinkingPart':
                        thinking = getattr(part, 'content', '')
                    elif part_type in ('ToolCallPart', 'BuiltinToolCallPart'):
                        tool_name = getattr(part, 'tool_name', 'unknown')
                        tool_args = getattr(part, 'args', {})
                        
                        tool_results = getattr(node, 'tool_call_results', {})
                        tool_result = tool_results.get(tool_name) if tool_results else None
                        
                        if thinking:
                            logger.info(f"Think: {thinking[:100]}...")
                            thinking = ""
                        
                        result_str = str(tool_result)[:80] if tool_result else "Done"
                        logger.info(f"Tool {tool_name}({tool_args}): {result_str}...")
            
            if not model_response or not getattr(model_response, 'parts', None):
                if thinking:
                    logger.info(f"Think: {thinking[:100]}...")
        
        # End node - final result
        elif node_type == 'End':
            data = getattr(node, 'data', None)
            if data and hasattr(data, 'output'):
                logger.info(f"Done: {str(data.output)[:60]}...")

    async def run(self, prompt: str) -> Any:
        """Run the agent loop until done or max iterations."""
        self._context.add_user(prompt)
        
        for iteration in range(self.max_iterations or float('inf')):
            self._iteration = iteration
            
            logger.info(f"Iteration {iteration}")
            
            try:
                # Get tag replacements from modules
                replacements = []
                for module in self._modules.all().values():
                    if module.get_context and module.tag:
                        value = module.get_context()
                        replacements.append((module.tag, value))
                
                # Get updated system prompt
                system_prompt = self._context.apply_tag_replacements(replacements)
                full_prompt = self._context.build_prompt(prompt)
                
                result = await self._run_with_retry(full_prompt, system_prompt)
                self._result = result.output
                
                self._context.add_assistant(str(result.output))
                
                return result
                
            except Exception as e:
                logger.error(f"Iteration {iteration} error: {e}")
                raise
        
        raise RuntimeError("Max iterations reached")


async def main():
    """Test the agent."""
    core = Core(
        model="llama3",
        max_iterations=10,
        llm_url="http://192.168.1.11:8010",
    )
    
    # Register modules
    from modules.time import get_time_module
    from modules.documents import get_documents_module
    core.register_module(get_time_module())
    core.register_module(get_documents_module())
    core.register_shell(timeout=30)
    
    # Set system prompt
    core.set_system_prompt("""You are riven, a helpful AI assistant.

Current time: {{time}}

Open documents:
{{documents}}
""")
    
    # Run a simple test
    result = await core.run("What time is it?")
    print(f"\nResult: {result.output}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())
