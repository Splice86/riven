# Riven

A modular agentic coding system built around **shards** — configurable personas with specific tool sets and behaviors.

## Overview

Riven Core provides an LLM-powered coding assistant that runs as an API server. It uses a **shard-based architecture** where each shard defines a personality, available tools, and system behavior. This makes it easy to compose different agent behaviors for different tasks.

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
├── api.py          # FastAPI server and routes
├── core.py         # Core agent loop
├── context.py      # Message processing and truncation
├── config.py       # Configuration loading
├── db.py           # SQLite context storage
├── modules/        # Tool modules (file, shell, time, web_tools)
├── shards/         # Shard YAML configs
├── web/            # Web UI (chat, editor)
└── docs/           # Architecture documentation
```
