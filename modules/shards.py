"""Shards module - delegate tasks to other shards and get the final output.

This module allows a shard to spawn another shard as a sub-agent. The sub-agent
runs in an isolated memory session so the parent's conversation history doesn't
pollute the sub-task's context.

Usage:
- run_shard(shard_name, task) -> runs the target shard and returns the final text output
- list_shards() -> shows available shards with their names and descriptions

Session ID is automatically available via get_session_id().
"""

import glob
import os

import requests
import yaml

from modules import CalledFn, ContextFn, Module, _session_id, get_session_id
from config import get, get_llm_config
from core import Core


def _shards_help() -> str:
    """Static tool documentation."""
    return """## Shards (Help)

### Available Commands
- **run_shard(shard_name, task, session_id?, timeout?, llm_config?)** - Delegate to another shard
- **list_shards()** - List all available shards

### Usage
Use `run_shard` when a task is better handled by a different shard's specialty
(e.g., delegating code implementation to codehammer, or test writing to testhammer).

The sub-shard runs in an isolated memory session derived from your session ID
so its context doesn't pollute yours.

### Tips
- Be specific in the task description - the sub-shard only sees your task text
- Use list_shards() to discover available shards first
- Sub-shard's output is returned as text - review it before using it as fact"""


def _shards_context() -> str:
    """Dynamic context - no persistent state for shard calls."""
    return "Shards module: use run_shard() to delegate tasks to other shards."


def _shard_files() -> list[str]:
    """Get absolute paths of all shard YAML files."""
    shards_dir = os.path.join(os.path.dirname(__file__), "..", "shards")
    if not os.path.exists(shards_dir):
        return []
    return glob.glob(os.path.join(shards_dir, "*.yaml"))


def _load_shard_config(shard_name: str) -> dict | None:
    """Load shard config by name from shard YAML files."""
    for filepath in _shard_files():
        with open(filepath) as f:
            data = yaml.safe_load(f)
            if data and data.get("name") == shard_name:
                return data
    return None


def _shard_names() -> list[str]:
    """Get names of all available shards."""
    names = []
    for filepath in _shard_files():
        with open(filepath) as f:
            data = yaml.safe_load(f)
            if data:
                names.append(data.get("name", os.path.basename(filepath)))
    return sorted(names)


async def run_shard(
    shard_name: str,
    task: str,
    session_id: str = None,
    timeout: float = None,
    llm_config: str = None,
) -> str:
    """Delegate a task to another shard and get the final text output.

    The sub-shard runs in an isolated memory session (derived from the parent
    session) so the parent's conversation history doesn't pollute the sub-task.

    Args:
        shard_name: Name of the shard to delegate to (e.g., 'codehammer', 'testhammer')
        task: What to ask the sub-shard to do - be specific, the sub-shard only sees this
        session_id: Override the memory session ID (auto-derived from parent session if omitted)
        timeout: Override the max execution time in seconds (default: from shard config)
        llm_config: Named LLM config to use (default: 'primary')

    Returns:
        The sub-shard's complete text output, or an error description
    """
    # Validate target shard exists
    shard = _load_shard_config(shard_name)
    if not shard:
        available = _shard_names()
        names = ", ".join(available) if available else "(none found)"
        return f"Shard '{shard_name}' not found. Available shards: {names}"

    # Derive sub-session from parent session so traces are grouped
    parent_session = session_id or get_session_id()
    sub_session = f"sub-{parent_session}-{shard_name}"

    # LLM config
    if llm_config:
        llm_cfg = get_llm_config(llm_config)
    else:
        llm_cfg = get_llm_config("primary")

    max_calls = shard.get("max_function_calls", 20)

    # Store the task to the sub-shard's memory session before running
    try:
        memory_url = shard.get("memory_api", {}).get("url") or get("memory_api.url")
        resp = requests.post(
            f"{memory_url}/context",
            json={
                "role": "user",
                "content": task,
                "session": sub_session,
            },
            timeout=5,
        )
        if resp.status_code not in (200, 201):
            return f"Failed to store task to sub-shard memory: HTTP {resp.status_code}"
    except requests.RequestException as e:
        return f"Failed to store task to sub-shard memory: {e}"
    except Exception as e:
        return f"Failed to store task to sub-shard memory: {e}"

    # Run the sub-shard's Core loop, accumulating output
    output_parts = []

    try:
        core = Core(
            shard=shard,
            llm=llm_cfg,
            max_function_calls=max_calls,
        )

        token = _session_id.set(sub_session)
        try:
            async for event in core.run_stream(sub_session):
                if "token" in event:
                    output_parts.append(event["token"])
                elif "error" in event:
                    output_parts.append(f"[ERROR: {event['error']}]")
                elif "done" in event:
                    break
        finally:
            _session_id.reset(token)

    except Exception as e:
        return f"Shard '{shard_name}' failed: {type(e).__name__}: {e}"

    output = "".join(output_parts)

    # If sub-shard returned nothing meaningful, echo the task as fallback
    if not output.strip():
        output = (
            f"[Sub-shard '{shard_name}' completed but returned no output]\n\n"
            f"Task was:\n{task}"
        )

    return output


async def list_shards() -> str:
    """List all available shards by name and description.

    Returns:
        Formatted list of available shards
    """
    if not _shard_files():
        return "No shards directory found."

    lines = ["## Available Shards\n"]
    for filepath in sorted(_shard_files()):
        with open(filepath) as f:
            data = yaml.safe_load(f)
        if not data:
            continue

        name = data.get("name", os.path.basename(filepath))
        display_name = data.get("display_name", name)
        description = data.get("description", "")

        # First line of system prompt as a taste
        system = data.get("system", "")
        system_preview = system.strip().split("\n")[0] if system else ""

        lines.append(f"### {display_name} (`{name}`)")
        if system_preview:
            lines.append(f"  {system_preview}")
        if description:
            lines.append(f"  {description}")
        lines.append("")

    return "\n".join(lines).strip()


def get_module():
    """Get the shards module."""
    return Module(
        name="shards",
        called_fns=[
            CalledFn(
                name="run_shard",
                description="""Delegate a task to another shard and get the final text output.

The sub-shard runs in an isolated memory session so its context doesn't pollute yours.
Use this when a task is better handled by a different shard's specialty.

Args:
- shard_name: Which shard to use (e.g., 'codehammer', 'testhammer')
- task: What to ask the sub-shard to do — be specific, the sub-shard only sees this text
- session_id: Override memory session ID for the sub-shard (auto-derived if omitted)
- timeout: Max execution time in seconds for the sub-shard (default: from shard config)
- llm_config: Named LLM config to use for the sub-shard (default: 'primary')

Returns: The sub-shard's complete text output""",
                parameters={
                    "type": "object",
                    "properties": {
                        "shard_name": {
                            "type": "string",
                            "description": "Name of the shard to delegate to (e.g., 'codehammer', 'testhammer')"
                        },
                        "task": {
                            "type": "string",
                            "description": "Detailed description of what the sub-shard should do"
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Override memory session ID for the sub-shard (auto-derived if omitted)"
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Max execution time in seconds for the sub-shard (default: from shard config)"
                        },
                        "llm_config": {
                            "type": "string",
                            "description": "Named LLM config to use for the sub-shard (default: 'primary')"
                        },
                    },
                    "required": ["shard_name", "task"]
                },
                fn=run_shard,
            ),
            CalledFn(
                name="list_shards",
                description="List all available shards by name and description. Use to discover which shards exist before calling run_shard.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                fn=list_shards,
            ),
        ],
        context_fns=[
            ContextFn(tag="shards_help", fn=_shards_help, static=True),
            ContextFn(tag="shards_context", fn=_shards_context),
        ],
    )
