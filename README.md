# Riven Codehammer

<!--
   __           
  / /  ___  ___ _(_)_ __   ___  ___ _ __
 / /__/ _ \/ _ | | '_ \ / _ \/ _ | '__|
 \____/\___/\__,_|_| .__ /\___/\__,_|_|   
                  |_|                    
   
   "It works on my machine." — Someone, probably
   "This code was written at 3am. No further questions."
   "Don't panic, but the AI is now sentient... just kidding. (maybe)"
   "Built with love, caffeine, and questionable decisions."
-->

A modular agentic coding system built around **shards** — configurable personas with specific tool sets and behaviors.

## Overview
hmmm
Riven Core provides an LLM-powered coding assistant that runs as an API server. It uses a **shard-based architecture** where each shard defines a personality, available tools, and system behavior. This makes it easy to compose different agent behaviors for different tasks.

### Web Interface

A complete web UI is included for interactive use:

| Interface | Purpose |
|-----------|---------|
| **Chat** | Real-time conversation with the agent (includes workflow tracking) |
| **Editor** | Code editing with syntax highlighting (tracks files, follows riven edits) |

Access via `GET /ui/` once the server is running.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     API Server                      │
│                    (FastAPI)                        │
├─────────────────────────────────────────────────────┤
│                   Core Loop                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │  Shards     │  │  Modules    │  │   Context   │ │
│  │  (persona)  │  │  (tools)    │  │   Manager   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘ │
├─────────────────────────────────────────────────────┤
│                Context DB (SQLite)                  │
│              ~/.riven/core.db                       │
└─────────────────────────────────────────────────────┘
```

## Shards

Shards are self-contained agent configurations:

| Shard | Purpose |
|-------|---------|
| **codehammer** | Coding-focused assistant — file editing, shell commands, web search |
| **testhammer** | TDD-first testing assistant — writes tests, delegates implementation |
| **scribe** | Documentation assistant — generates and maintains docs |

## Modules

Modules provide tools (called functions) and context injection:

| Module | Tools |
|--------|-------|
| **file** | open_file, edit, search, navigate |
| **shell** | run, run_background, kill, cd |
| **time** | Provides current timestamp in context |
| **web_tools** | fetch_page, web_search |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the API server
python -m riven_core

# Or directly
uvicorn api:app --reload --host 0.0.0.0 --port 8080
```

## API Endpoints

- `POST /api/v1/messages` — Send a message, get a response
- `GET /api/v1/history?session_id=<id>` — Get conversation history
- `GET /api/v1/chat/status?session_id=<id>` — Check active session
- `GET /api/v1/chat/abort?session_id=<id>` — Abort active inference
- `GET /ui/` — Web chat interface

## Configuration

Edit `config.yaml` to configure:
- Server host/port
- LLM provider URL and model
- Module loading
- Debug settings

## Project Structure

```
riven_core/
├── api.py              # FastAPI server and routes
├── core.py             # Core agent loop
├── context.py          # Message processing and truncation
├── config.py           # Configuration loading
├── events.py           # Event handling
├── db/                 # SQLite context storage
│   └── context_db.py   # Database operations
├── modules/            # Tool modules
│   ├── file/           # File operations (read, write, edit, search)
│   ├── shell/          # Shell command execution
│   ├── time/           # Time utilities
│   ├── web_tools/      # Web fetch and search
│   └── workflow/       # Task tracking
├── shards/             # Shard YAML configs
│   ├── codehammer.yaml
│   ├── scribe.yaml
│   └── testhammer.yaml
├── web/                # Web UI
│   ├── chat/           # Chat interface
│   ├── editor/         # Code editor
│   └── workflow/       # Workflow visualization
├── tests/              # Test suite
├── docs/               # Architecture documentation
└── requirements.txt    # Dependencies
```
