# Riven

An AI coding agent for developers who want control.

## About

Riven is my attempt at building an AI assistant that actually works the way I think AI should work. Not as a magic oracle that somehow "just knows" - but as a tool that operates on clear inputs, produces verifiable outputs, and lets me see exactly what's happening at every step.

### My Philosophy on AI

I don't believe in the "just ask the AI" approach. Prompts are fragile. Subtle changes in wording produce wildly different results. Instead, I believe in:

- **Explicit tools over implicit reasoning** - When the AI needs to do something, give it a tool with a clear name and contract, not a natural language instruction it has to interpret
- **Visible state** - The AI should work with files I can read, not hidden contexts I can't inspect
- **Deterministic where possible** - File operations should save. Commands should run. The AI shouldn't hallucinate that it did something it didn't
- **Human in the loop** - I want to see what tools are being called and why, not just watch text appear

Riven is built around these ideas. It's not perfect. It's not trying to be the most capable assistant. It's trying to be the most controllable one.

## Architecture

Riven has two main concepts: **cores** and **modules**.

### Cores

A core is a personality + config bundle. It defines:
- The system prompt (how the AI behaves)
- Which LLM to use and its settings
- Which modules are available
- Tool timeouts and other behavior tuning

Cores live in the `cores/` folder as YAML files. Switch between them with:

```bash
python main.py --core code_hammer
```

### Modules

Modules provide tools. Each module registers functions that become available to the AI. The file module gives file operations. The shell module runs commands. The memory module persists conversation context.

Modules are Python files in `modules/` that export a `get_module()` function returning a `Module` object with:
- `name` - identifier
- `functions` - dict of async callables
- `get_context` - optional function to add info to system prompt
- `tag` - key for context substitution (e.g. `{file}`)

```python
from modules import Module

def get_module():
    async def my_tool(arg: str) -> str:
        """Does something."""
        return f"Result: {arg}"
    
    return Module(
        name="my_module",
        functions={"my_tool": my_tool},
        tag="my_module"  # available as {my_module} in system prompt
    )
```

## Test Ground

This is a personal project. I built it to experiment with ideas about how AI assistants should work. It is not:

- A polished product
- Guaranteed to be stable
- Supported in any formal sense
- Safe to run unsupervised on systems you care about

It might break. It might eat your files. It might produce outputs you didn't expect. Run it in a VM, test with disposable projects, and always verify what it's doing before you let it touch something important.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start the memory server (required for context)
cd memory
pip install -r requirements.txt
python api.py &
cd ..

# Run Riven (uses localhost defaults)
python main.py

# Or with a launch script for remote LLMs
./launch.sh
```

## Config

Edit `config.yaml` for memory server settings. Individual cores have their own configs in `cores/`.

## Commands

- `/exit` - Quit
- `Ctrl+C` - Interrupt current turn

## Memory Server

The `memory/` folder runs a separate FastAPI server that stores conversation context. It supports:
- Adding messages with session tracking
- Retrieving context for future turns
- Optional summarization for long conversations

MIT