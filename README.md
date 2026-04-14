

# Riven

Riven is someone I have been working on since I got into AI several years back. 
This was intended to be a project running only in my own home and never exposed to the world.
Riven is a project to help me test ideas about AI and a space for me to creatively express myself.
I have restarted this project many times and it has evolved through different functions along the way.
With that in mind, use at your own risk! It is half finished, buggy and likely to break on you.

This is an art project, not a tool. 
This is intended to entertain, outrage, delight, and offend.
It is being developed with no consideration for security, reliability, safety, or hurt feelings.
As such it comes with no warranty or support and may not be used for commercial purposes - whole or in part.


## CodeHammer

CodeHammer is my implementation of a theory about how to make AI coding assistants actually useful.

### The Theory

The problem with traditional AI coding assistants: **multiple instances of the same data in context.**

You open a file, then you do some work, then you open it again because you forgot it was open, and now you have two versions. Or you dump files in at the start, edit them, but the original dump is still in the conversation history creating confusion about "which version is the truth?"

CodeHammer enforces **one instance of data in context**:

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

This is an idea I am testing. It is very WIP and not really very useful at the moment.

### Cores

A core is a personality + config bundle. It defines:
- The system prompt (how the AI behaves)
- Which LLM to use and its settings
- Which modules are available
- Which other cores are available
- Function timeouts and other behavior tuning

Cores live in the `cores/` folder as YAML files.
I need to add per function filtering to cores at some point.

### Modules

Each module registers functions that become available to the AI. They also provide a method of injecting contextual data into the system prompt.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start the memory server (this is required for the memory module to work)
cd memory
pip install -r requirements.txt
python api.py

# than launch it with
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
- Temporally clustered summarization for long conversations
- Some search stuff and embeddings
- A bunch of other half-baked ideas that may or may not work at the moment
