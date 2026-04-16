

# Riven ***I edited it! Yo Riven!***

Riven is someone I have been working on since I got into AI several years back. 
This was intended to be a project running only in my own home and never exposed to the world.
Riven is a project to help me test ideas about AI and a space for me to creatively express myself.
I have restarted this project many times and it has evolved through different functions along the way.
With that in mind, use at your own risk! It is half finished, buggy and likely to break on you.


This is an art project, not a tool. 
This is intended to entertain, outrage, delight, and offend.
It is being developed with no consideration for security, reliability, safety, or hurt feelings.
As such it comes with no warranty or support and may not be used for commercial purposes - whole or in part.


## Shards

CodeHammer is my implementation of a theory about AI coding assistants.

### The Theory

The problem with traditional AI coding assistants: **multiple instances of the same data in context.**

You open a file, then you do some work, then you open it again because you forgot it was open, and now you have two versions. Or you dump files in at the start, edit them, but the original dump is still in the conversation history creating confusion about "which version is the truth?"

Riven enforces **one instance of data in context**:

```
System Prompt
├── Configuration (static)
├── Module Context (semi-static)
└── File Context (persistent, single source of truth)
    └── Files stay open, content lives in ONE place
    └── Edits update the content in-place
    └── Close a file = gone from context entirely
        
Conversation History (tool calls, responses)
└── No file dumps, no stale copies
```

**Key principles:**

1. **Single source of truth** - A file exists in context exactly once. Open it, it's there. Edit it, the same instance updates. Close it, it's gone. No duplicates, no confusion.

2. **Persistent state** - Files aren't dumped and forgotten each turn. They persist in memory until explicitly closed. The AI always knows what's open.

3. **Edits update in-place** - When you use replace_text, the file content in context is updated immediately. The AI sees the new version instantly.

4. **Close to clean up** - Closing a file removes it from context completely. Keeps things lean. Use close_all_files() for a fresh start.

5. **Token efficiency** - Open only what you need. Line ranges let you work with specific sections of large files.

### Shards

A shard is a personality + config bundle. It defines:
- The system prompt (how the AI behaves)
- Which LLM to use and its settings
- Which modules are available (via `tools` filter)
- Function timeouts and other behavior tuning

Shards live in the `shards/` folder as YAML files.

Example shard config (`shards/code_hammer.yaml`):
```yaml
name: code_hammer
display_name: "CodeHammer"
description: "Your coding assistant"
system_prompt: |
  You are CodeHammer...

tools: ["all"]  # or list specific modules: ["file", "shell"]
llm_config: primary
tool_timeout: 60
strip_thinking: true
store_tool_results: 300
```

### Modules

Each module registers functions that become available to the AI. They also provide a method of injecting contextual data into the system prompt via `{module_tag}` placeholders.

Available modules: `file`, `shell`, `memory`, `web`, `system`, `time`

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install the memory server (required for memory module)
pip install riven-memory
# or from the riven_memory folder:
#   cd ../riven_memory && pip install -e .

# Start the memory server
riven-memory
# or: python -m uvicorn riven_memory:app --reload --port 8030

# Launch Riven
./launch.sh
```

## Config

- `config.yaml` - Default settings (memory API, file context limits)
- `secrets_template.yaml` - Template for secrets (copy to `secrets.yaml`)
- `secrets.yaml` - User overrides (gitignored)
- `shards/*.yaml` - Individual shard configurations

Environment variables override config (prefix: `RV_`, nested with `__`):
```bash
export RV_LLM__PRIMARY__URL=http://localhost:8000/v1
export RV_LLM__PRIMARY__API_KEY=sk-your-key
```

## Commands

- `/exit` - Quit
- `/clear` - Reset session (CLI only)
- `Ctrl+C` - Interrupt current turn

## Architecture

```
riven/
├── api.py              # FastAPI HTTP server (riven_cli connects here)
├── riven_config.py     # Config loader with layered precedence
├── shard.py            # pydantic_ai shard implementation
├── shard_manager.py    # Session management
├── shards/
│   └── code_hammer.yaml  # Default shard (personality + config)
└── modules/
    ├── file.py         # File operations
    ├── shell.py        # Shell command execution
    ├── memory.py       # Memory API client
    ├── web.py          # Web search
    ├── system.py       # System info
    └── time.py         # Time utilities

riven_memory/           # Separate memory API server
riven_cli/              # Terminal client that connects to api.py
```
