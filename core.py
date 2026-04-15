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


from riven_secrets import get_llm_config, get_memory_api
from riven_secrets import get_secret  # LLM config only - memory API uses config.yaml

# Legacy env/import fallback
MEMORY_API_URL = os.environ.get("MEMORY_API_URL", get_memory_api())
LLM_URL = os.environ.get("LLM_URL", get_secret('llm', 'default', 'url', default="http://localhost:8000/v1/"))
LLM_API_KEY = os.environ.get("LLM_API_KEY", get_secret('llm', 'default', 'api_key', default="sk-dummy"))
LLM_MODEL = os.environ.get("LLM_MODEL", get_secret('llm', 'default', 'model', default="nvidia/MiniMax-M2.5-NVFP4"))
DEFAULT_DB = os.environ.get("MEMORY_DB", CONFIG.get('memory_api', {}).get('db_name', "riven"))
MAX_OUTPUT_LINES = 1000


def _resolve_core_config(core_config: dict) -> dict:
    """Resolve llm_config: name to actual LLM values from secrets."""
    from riven_secrets import get_llm_config
    
    resolved = core_config.copy()
    
    # Handle llm_config: primary/alternate
    if 'llm_config' in resolved:
        config_name = resolved.pop('llm_config')
        llm_cfg = get_llm_config(config_name)
        if not llm_cfg.get('url'):
            raise ValueError(f"llm_config '{config_name}' requires url in secrets.yaml")
        resolved['llm_url'] = llm_cfg['url']
        resolved['llm_model'] = llm_cfg['model']
        resolved['llm_api_key'] = llm_cfg['api_key']
    
    return resolved


class MemoryClient:
    """Simple client for memory API context endpoints."""
    
    def __init__(self, db_name: str = None, base_url: str = MEMORY_API_URL, session_id: str = None):
        self.db_name = db_name or DEFAULT_DB
        self.base_url = base_url
        self.session_id = session_id  # Set from caller
    
    def add_context(self, role: str, content: str, created_at: str = None, session: str = None) -> dict:
        """Add a context message."""
        # Use provided session or fall back to current
        session = session or self.session_id
        resp = requests.post(
            f"{self.base_url}/context",
            params={"db_name": self.db_name},
            json={"role": role, "content": content, "created_at": created_at, "session": session}
        )
        resp.raise_for_status()
        return resp.json()
    
    def get_context(self, limit: int = 100, session: str = None) -> list[dict]:
        """Get context for prompt."""
        # Use provided session or fall back to current
        session = session or self.session_id
        resp = requests.get(
            f"{self.base_url}/context",
            params={"db_name": self.db_name, "limit": limit, "session": session}
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
        strip_thinking: bool = False,
        store_tool_results: int = 0,  # 0=skip, N=store last N lines
        session_id: str = None  # Must be provided by caller
    ):
        # Load from config if provided
        if config:
            # Env vars take priority over config
            self.model = os.environ.get('LLM_MODEL', config.get('llm_model', LLM_MODEL))
            self.llm_url = os.environ.get('LLM_URL', config.get('llm_url', LLM_URL))
            self.llm_api_key = os.environ.get('LLM_API_KEY', config.get('llm_api_key', LLM_API_KEY))
            self.system_prompt = config.get('system_prompt', '')
            self.db_name = os.environ.get('MEMORY_DB', config.get('memory_api', {}).get('db_name', DEFAULT_DB))
            self._tool_filter = config.get('tools', None)
            self.tool_timeout = config.get('tool_timeout', 20)
            self.strip_thinking = config.get('strip_thinking', False)
            self.store_tool_results = config.get('store_tool_results', 0)  # 0=skip, N=store last N lines
            self._debug_system_prompt = config.get('debug_system_prompt', False)  # Save prompt to ~/.riven/sessions/
        else:
            self.model = model or LLM_MODEL
            self.llm_url = llm_url or LLM_URL
            self.llm_api_key = llm_api_key or LLM_API_KEY
            self.system_prompt = system_prompt or ""
            self.db_name = db_name or DEFAULT_DB
            self._tool_filter = tools
            self.tool_timeout = tool_timeout
            self.strip_thinking = strip_thinking
            self.store_tool_results = store_tool_results  # 0=skip, N=store last N lines
            self._debug_system_prompt = False  # Debug saving disabled by default
        
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._cancelled = False

        self._modules = ModuleRegistry()
        
        # Session ID must be provided by caller (from client)
        if not session_id:
            raise ValueError("session_id is required - must be provided by client")
        self._session_id = session_id
        self._memory = MemoryClient(db_name=self.db_name, base_url=MEMORY_API_URL, session_id=session_id)
        
        # Register modules based on tool filter
        self._register_modules()
    
    def _register_modules(self) -> None:
        """Register modules, optionally filtering by tool list."""
        all_modules = get_all_modules()
        
        for module in all_modules:
            # Handle "all" case
            if self._tool_filter is None or 'all' in self._tool_filter:
                self._modules.register(module, session_id=self._session_id)
            elif module.name in self._tool_filter:
                self._modules.register(module, session_id=self._session_id)

    
    def cancel(self) -> None:
        """Cancel any ongoing operation."""
        self._cancelled = True

    def _create_agent(self) -> Agent:
        """Create a pydantic_ai Agent."""
        client = AsyncOpenAI(base_url=self.llm_url, api_key=self.llm_api_key)
        provider = OpenAIProvider(openai_client=client)
        model = OpenAIChatModel(model_name=self.model, provider=provider)
        
        # Get functions from registered modules
        module_funcs = self._modules.get_functions()
        tools = create_tools(module_funcs, self.tool_timeout)
        
        agent = Agent(
            model=model,
            tools=tools
        )
        
        # Register dynamic system prompt - runs before EVERY model request
        # (including after every tool call), keeping context fresh
        @agent.system_prompt(dynamic=True)
        def build_dynamic_system_prompt() -> str:
            return self._build_system_prompt()
        
        return agent
    def _build_system_prompt(self) -> str:
        """Build system prompt with module context.
        
        Replaces {module.tag} placeholders with each module's context.
        """
        from datetime import datetime
        
        debug_header = None
        if getattr(self, '_debug_system_prompt', False):
            debug_header = [
                f"=== System Prompt Debug Info ===",
                f"Timestamp: {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                f"Session ID: {self._session_id}",
                f"Modules providing context:"
            ]
        
        prompt = self.system_prompt
        
        # Add module context replacements
        for module in self._modules.all().values():
            if module.get_context and module.tag:
                value = module.get_context()
                if value is not None:
                    prompt = prompt.replace(f"{{{module.tag}}}", value)
                    if debug_header is not None:
                        debug_header.append(f"  - {module.name} contributed {len(value)} chars")
        
        # Debug: save system prompt to disk if enabled
        if debug_header is not None:
            self._save_system_prompt(prompt, debug_header)
        
        return prompt
    
    def _save_system_prompt(self, prompt: str, debug_header: list = None) -> None:
        """Save system prompt to session debug file with timestamp and debug info."""
        import os
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_dir = os.path.expanduser(f"~/.riven/sessions/{self._session_id}")
        os.makedirs(debug_dir, exist_ok=True)
        
        debug_lines = (debug_header or []).copy()
        debug_lines.append(f"Total prompt size: {len(prompt)} chars")
        debug_lines.append(f"=================================")
        debug_lines.append("")
        debug_lines.append(prompt)
        
        filepath = os.path.join(debug_dir, f"system_prompt_{timestamp}.txt")
        with open(filepath, "w") as f:
            f.write("\n".join(debug_lines))
        
        with open(os.path.join(debug_dir, "system_prompt_latest.txt"), "w") as f:
            f.write("\n".join(debug_lines))


    def _build_prompt(self, user_input: str) -> tuple[str, list[ModelMessage]]:
        """Build prompt with memory context.
        
        Returns tuple of (user_prompt, message_history) where message_history
        contains the converted memory context.
        """
        # Get context from memory
        context = self._memory.get_context(session=self._session_id)
        
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
        """Run the agent with the given prompt - waits for complete response."""
        # Collect all tokens from stream
        output_text = ""
        async for event in self.run_stream(prompt):
            if "error" in event:
                raise Exception(event["error"])
            if "token" in event:
                output_text += event["token"]
        
        # Return mock result object
        class Result:
            def __init__(self, output):
                self.output = output
        
        # Strip thinking tags
        if self.strip_thinking:
            output_text = re.sub(r"<think>.*?</think>", "", output_text, flags=re.DOTALL).strip()
        else:
            output_text = output_text.replace("<think>", "").replace("</think>", "").strip()
        
        # Add to memory
        self._memory.add_context("user", prompt, session=self._session_id)
        self._memory.add_context("assistant", output_text, session=self._session_id)
        
        return Result(output_text)
    
    async def run_stream(self, prompt: str):
        """Run agent with streaming - yields tokens as they arrive.
        
        Yields dicts with 'token' key for SSE streaming.
        """
        # System prompt is now built dynamically via @agent.system_prompt(dynamic=True)
        # so it refreshes after every tool call
        user_prompt, message_history = self._build_prompt(prompt)
        
        from pydantic_ai.messages import (
            ModelMessage, ModelRequest, ModelResponse,
            UserPromptPart, TextPart
        )
        
        agent = self._create_agent()
        _streamed_text = ""
        _thinking_buffer = ""
        pending_tool = None
        tool_results = []
        
        try:
            async for event in agent.run_stream_events(user_prompt, message_history=message_history):
                if self._cancelled:
                    yield {"error": "cancelled"}
                    return
                
                # Handle text content
                if isinstance(event, PartStartEvent):
                    part = event.part
                    if isinstance(part, ThinkingPart):
                        _thinking_buffer = part.content
                        if part.content:
                            yield {"token": f"<think>{part.content}"}  # Opening tag only
                    elif hasattr(part, 'content') and part.content:
                        _streamed_text += part.content
                        yield {"token": part.content}
                        
                elif isinstance(event, PartDeltaEvent):
                    delta = event.delta
                    if isinstance(delta, ThinkingPartDelta):
                        if delta.content_delta:
                            _thinking_buffer += delta.content_delta
                            yield {"token": delta.content_delta}  # Content only, no tags
                    elif hasattr(delta, 'content_delta') and delta.content_delta:
                        _streamed_text += delta.content_delta
                        yield {"token": delta.content_delta}
                        
                elif isinstance(event, PartEndEvent) and isinstance(event.part, ThinkingPart):
                    yield {"token": "</think>"}  # Closing tag only
                    _thinking_buffer = ""
                    
                elif isinstance(event, FunctionToolCallEvent):
                    args = event.part.args
                    tool_name = event.part.tool_name
                    pending_tool = {"name": tool_name, "args": args}
                    # Yield tool call wrapped in tags
                    yield {"token": f"<tool>→ {tool_name}{args}</tool>"}
                    
                elif isinstance(event, FunctionToolResultEvent):
                    content = event.result.content
                    tool_name = event.result.tool_name
                    if hasattr(content, 'content'):
                        content = content.content
                    content_str = str(content) if content else ""
                    
                    if pending_tool:
                        tool_results.append({
                            "tool": pending_tool['name'],
                            "call": f"→ {pending_tool['name']}{pending_tool['args']}",
                            "result": content_str
                        })
                        pending_tool = None
                    else:
                        tool_results.append({"tool": tool_name, "result": content_str})
                    
                    # Yield tool result wrapped in tags (truncated)
                    truncated = content_str[:200] + "..." if len(content_str) > 200 else content_str
                    yield {"token": f"<tool>{truncated}</tool>"}
                        
                elif isinstance(event, AgentRunResultEvent):
                    # Store tool results in memory
                    if self.store_tool_results > 0:
                        for tr in tool_results:
                            result = tr.get('result', '')
                            if len(result) > self.store_tool_results * 100:
                                result = result[:self.store_tool_results * 100] + "..."
                            self._memory.add_context("tool", f"{tr['tool']}: {result}", session=self._session_id)
                    
                    # Strip thinking from final output
                    final_output = _streamed_text
                    if self.strip_thinking:
                        final_output = re.sub(r"<think>.*?</think>", "", final_output, flags=re.DOTALL).strip()
                    else:
                        final_output = final_output.replace("<think>", "").replace("</think>", "").strip()
                    
                    # Add to memory
                    self._memory.add_context("user", prompt, session=self._session_id)
                    self._memory.add_context("assistant", final_output, session=self._session_id)
                    
                    yield {"done": True}
                    return
                    
        except Exception as e:
            yield {"error": str(e)}


def _load_cores() -> dict:
    """Load cores from the cores/ folder."""
    import glob
    
    cores = {}
    cores_dir = "cores"
    
    if not os.path.exists(cores_dir):
        return cores
    
    for filepath in glob.glob(os.path.join(cores_dir, "*.yaml")):
        with open(filepath) as f:
            core_config = yaml.safe_load(f)
            if core_config and 'name' in core_config:
                core_name = core_config.pop('name')
                # Resolve placeholders from secrets
                core_config = _resolve_core_config(core_config)
                cores[core_name] = core_config
    
    return cores


def get_core_display_name(core_name: str) -> str:
    """Get the display name for a core."""
    cores = _load_cores()
    if core_name in cores:
        return cores[core_name].get('display_name', core_name)
    return core_name


def get_core(name: str = "code_hammer", session_id: str = None) -> Core:
    """Factory function to create a core by name from config.
    
    Args:
        name: Name of the core in cores/ folder (default: "code_hammer")
        session_id: Session ID from client for memory persistence
    
    Returns:
        Configured Core instance
    
    Raises:
        ValueError: If core name not found or session_id not provided
    """
    cores = _load_cores()
    
    if name not in cores:
        raise ValueError(f"Core '{name}' not found. Available: {list(cores.keys())}")
    
    if not session_id:
        raise ValueError("session_id is required - must be provided by client")
    
    # Merge global config (from config.yaml) with core config
    # Core config takes priority
    merged_config = {**CONFIG, **cores[name]}
    
    return Core(config=merged_config, session_id=session_id)



def list_cores() -> list[str]:
    """List available core names from cores/ folder."""
    return list(_load_cores().keys())
