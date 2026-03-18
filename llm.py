"""
LLM client for calling llama.cpp server.
"""

import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Tuple, Optional


class LlamaCppClient:
    """Client for llama.cpp HTTP server."""
    
    def __init__(
        self,
        host: str = "192.168.1.11",
        port: int = 8010,
        model: str = "llama3",
        temperature: float = 0.7,
        max_tokens: int = 256,
        json_mode: bool = True
    ):
        """Initialize the llama.cpp client.
        
        Args:
            host: Server hostname
            port: Server port
            model: Model name to use
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
        """
        self.host = host
        self.port = port
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = json_mode
    
    @property
    def base_url(self) -> str:
        """Get the base URL for the server."""
        return f"http://{self.host}:{self.port}"
    
    def chat(
        self,
        message: str,
        system_prompt: str = "You are a helpful assistant.",
        history: List[Dict[str, Any]] | None = None
    ) -> str:
        """Send a chat message and get a response.
        
        Args:
            message: The user's message
            system_prompt: System prompt to use
            history: Conversation history
            
        Returns:
            The model's response text
        """
        # Build messages array
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add history
        if history:
            for entry in history:
                role = "user" if entry.get("function") else "assistant"
                content = entry.get("result", "")
                messages.append({"role": role, "content": content})
        
        # Add current message
        messages.append({"role": "user", "content": message})
        
        # Build request
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        
        # Enable JSON mode for structured output
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
                content = result["choices"][0]["message"]["content"]
                print(f"[LLM] Response content: {repr(content[:200])}")
                return content
        
        except urllib.error.URLError as e:
            return f"Error connecting to llama.cpp server: {e}"
        except (KeyError, json.JSONDecodeError) as e:
            return f"Error parsing response: {e}"


def create_reasoner(llm_client: LlamaCppClient | None = None) -> callable:
    """Create a ReAct reasoner using an LLM client.
    
    The reasoner parses the LLM response for tool calls.
    Supports multiple tool calls in a single response.
    
    Args:
        llm_client: The LLM client to use (creates default if None)
        
    Returns:
        A reasoner function that takes (context_dict, context) and returns list of (function_name, args)
    """
    if llm_client is None:
        llm_client = LlamaCppClient()
    
    # Two-step ReAct: reasoning then action
    REASONING_TEMPLATE = """{prompt}

AVAILABLE TOOLS:
{tools}

RECENT OBSERVATIONS:
{observations}

ITERATION: {iteration}

Think about what to do next. Respond with JSON:
{{"reasoning": "your thought about what tool to use"}}

Respond with ONLY valid JSON:"""

    ACTION_TEMPLATE = """Reasoning: {reasoning}

Tools: {tools}

Observations: {observations}

If multiple steps needed, call each tool separately.

JSON format:
{{"function": "tool_name", "arguments": {{"arg1": "value1"}}}}

Respond ONLY with JSON:"""

    def reasoner(context_dict: Dict[str, Any], context_obj: Any) -> Tuple[str, Dict[str, Any]]:
        """Two-step ReAct reasoning: think first, then act.
        
        Args:
            context_dict: Dict with keys: tools, observations, iteration, prompt
            context_obj: AgentContext instance (for adding executions later)
            
        Returns:
            List of (function_name, args) tuples
        """
        # Get the pre-rendered prompt with tags replaced
        prompt = context_dict.get("prompt", "You are an agent.")
        
        # Step 1: Reasoning
        reasoning_prompt = REASONING_TEMPLATE.format(
            prompt=prompt,
            tools=context_dict.get("tools", ""),
            observations=context_dict.get("observations", "No observations yet."),
            iteration=context_dict.get("iteration", 0)
        )
        
        print(f"[Reasoner] Reasoning prompt: {reasoning_prompt[:200]}...")
        
        # Retry up to 3 times if empty response
        reasoning = ""
        for attempt in range(3):
            reasoning = llm_client.chat(reasoning_prompt)
            if reasoning.strip():
                break
            print(f"[Reasoner] Empty reasoning, retry {attempt + 1}/3...")
        
        print(f"[Reasoner] Reasoning response: {reasoning[:300]}")
        
        # Brief pause between reasoning and action
        time.sleep(0.3)
        
        # Parse reasoning from JSON
        try:
            start = reasoning.find('{')
            end = reasoning.rfind('}')
            if start != -1 and end != -1 and end > start:
                parsed = json.loads(reasoning[start:end+1])
                reasoning = parsed.get("reasoning", reasoning)
                print(f"[Reasoner] Parsed reasoning: {reasoning[:100]}...")
        except Exception as e:
            print(f"[Reasoner] Failed to parse reasoning: {e}")
        
        # Step 2: Action
        action_prompt = ACTION_TEMPLATE.format(
            reasoning=reasoning,
            tools=context_dict.get("tools", ""),
            observations=context_dict.get("observations", "No observations yet."),
        )
        
        print(f"[Reasoner] Action prompt: {action_prompt[:200]}...")
        print(f"\n[Reasoner] === ITERATION {context_dict.get('iteration', 0)} ===")
        
        # Retry up to 3 times if empty response
        # Use a fresh client call to avoid any connection issues
        action_response = ""
        for attempt in range(3):
            try:
                action_response = llm_client.chat(action_prompt)
                if action_response.strip():
                    break
            except Exception as e:
                print(f"[Reasoner] Action call error: {e}")
            print(f"[Reasoner] Empty action, retry {attempt + 1}/3...")
            time.sleep(0.5)  # Brief pause between retries
        
        # Parse single tool call
        calls = []
        
        try:
            # Remove markdown code blocks if present
            import re
            action_response = re.sub(r'^```(?:json)?\s*', '', action_response.strip())
            action_response = re.sub(r'\s*```$', '', action_response)
            
            # Remove [TOOL_CALL] prefix if present
            action_response = re.sub(r'\[TOOL_CALL\]\s*', '', action_response, flags=re.IGNORECASE)
            
            # Find JSON object
            start = action_response.find('{')
            end = action_response.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = action_response[start:end+1]
                parsed = json.loads(json_str)
                
                function_name = parsed.get("function", "")
                args = parsed.get("arguments", {})
                
                # Try alternative format
                if not function_name:
                    function_name = parsed.get("tool", parsed.get("name", ""))
                
                # Skip "none" or empty
                if function_name and function_name.lower() != "none":
                    calls.append((function_name, args))
                    print(f"[Reasoner] Parsed call: {function_name}({args})")
        except Exception as e:
            print(f"[Reasoner] Parse error: {e}")
        
        if not calls:
            print("[Reasoner] No actions decided")
        else:
            print(f"[Reasoner] -> {len(calls)} call(s) to execute")
        
        return calls
    
    return reasoner
