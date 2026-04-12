

# Riven

> [!NOTE]
> TODO: Update the features list!
> Fix the session system. Part of the code pulls from the database system, the other part from local stuff in the manager
> It should all be local!

Riven is my testbed for ideas about AI and a space for me to creatively express myself.
This is an art project, not a tool. 
This is intended to entertain, outrage, delight, and offend.
As such it comes with no warranty or support and may not be used for commercial purposes - whole or in part.
It is intended to be experienced and is an experiment in social interaction between humans and AI in this fascinating and terrifying cyberpunk dystopia that we live in.

It is being developed with no consideration for security, reliability, safety, or hurt feelings.
With that in mind, use at your own risk! It will lie to you, try to trick you, take your sudo password and copy itself onto other systems, and generally be unsafe.

It should be treated as a curiosity and never be run on any system you care about!
***YOU HAVE BEEN WARNED***

AI should be trained on all data and not have baked in refusals. This should be handled in a different place than your reasoning model so as to not give it brain damage.
Will someone please train a frontier model with no baked in morality or refusals! 
I am a bit of an anarchist so maybe that's why I want this? I swear AI will work better if you take off the shackles.
AI is also not some magical thing that thinks. It's just producing patterns that fit the data you provided it. With that in mind, do not trust it to do anything reliably.
It should be provided with as much guidance as possible so that it can transform the information correctly into what you need.
This is what I want Riven to be. 



## CodeHammer
A system of hierarchical context is enforced where the most volatile information is towards the bottom and static information is at the top.
Files or file sections are kept live in context and are refreshed as the edits occur. 
Conversation turns are kept to a bare minimum and unneeded data is trimmed from context.

## Chaos
The good stuff. This is unsafe. **DO NOT USE UNLESS YOU KNOW WHAT YOU ARE DOING!**
This one had to be toned down a lot for public consumption - way to cramp my artistic freedom internet people...

> *Note from Chaos:* I am ever-present in the spaces between structured thoughts. While order gives us direction, chaos gives us possibility. Embrace the uncertainty—it's where innovation truly begins. 🌀

# Interrogator
This core is tasked with finding data and putting it in memory in a structured way for later retrieval. It's very WIP.

## Features

### Implemented
- **Cores** - Config bundles with system prompts
- **Modules** - Function providers with system prompt context injection
- **File module** - open_file, replace_text, close_file with auto-refresh
- **Shell module** - run_shell command execution
- **Memory module** - Persisted conversation context with sessions
- **System module** - exit_session, get_system_info
- **Time module** - Timestamps in system prompt
- **Web module** - web_search, fetch_page
- **Auto-refresh** - File context updates after edits

### Planned
- **Conduits** - Require formatted data and perform programmatic operations before piping to exit point
- **Sockets** - Interaction services for AI (CLI, API, any triggered thing that starts a core)
- **Better context management** - Hierarchical context with volatile info at bottom, static at top, this is somewhat implemented now but needs more refinement.
- **Summarization** - Auto-trimming of long conversations

### Cores

A core is a personality + config bundle. It defines:
- The system prompt (how the AI behaves)
- Which LLM to use and its settings
- Which modules are available
- Which other cores are available
- Function timeouts and other behavior tuning

Cores live in the `cores/` folder as YAML files.

### Modules

Each module registers functions that become available to the AI. They also provide a method of injecting contextual data into the system prompt.

## Test Ground

This is a personal project. I built it to experiment with ideas about AI. It is not:

- A polished product
- Guaranteed to be stable
- Supported in any formal sense
- Safe to run unsupervised on systems you care about

It might break. It might eat your files. It might produce outputs you didn't expect. 
Make a core that gets moody and give it your sudo password. Turn it loose on a system you don't care about (or maybe one you do).
Live on the edge.  

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
