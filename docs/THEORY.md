# CodeHammer Theory & Context Architecture

## Overview

CodeHammer is a **coding-focused shard** — a configuration that defines a persona, system prompt, and set of capabilities for the Riven agent. This document explains the theory behind shards, modules, context management, and the deduplication strategy that keeps the agent's context window lean.

---

## What is a Shard?

A **shard** is a self-contained agent configuration. Think of it as a "personality preset" or "role definition."

```yaml
# shards/codehammer.yaml
name: codehammer
display_name: "CodeHammer"

system: |
  You are CodeHammer. No fluff. Just clean code.

modules:
  - file      # Provides {file} context
  - shell     # Provides {shell} context
  - memory    # Provides {memory} context
  - time      # Provides {time} context
  - web       # Provides {web} context

tool_timeout: 60
max_function_calls: 20
```

### Why Shards?

- **Separation of concerns**: A coding assistant shouldn't have the same tools as a data analyst
- **Composable**: Mix and match modules to build different agents
- **Declarative**: The YAML is human-readable and version-controllable
- **Stateless**: The Core doesn't know about shards — it just loads modules

---

## Modules: Tools + Context Providers

Each module provides two things:

| Component | Purpose | Example |
|-----------|---------|---------|
| **called_fns** | Tools the LLM can invoke | `open_file()`, `run()` |
| **context_fns** | Dynamic content injected into system prompt | `{file}` → list of open files |

### The Context Function Pattern

```python
def _open_files_context() -> str:
    """Context function that returns open files content."""
    session_id = get_session_id()
    memories = _search_memories(session_id, "k:file")
    # ... build context string
    return context_string
```

When the system prompt contains `{file}`, the Core calls `_open_files_context()` and substitutes the result.

---

## The File Module: Open Files in Context

### The Problem

The LLM needs to know about files the user has opened. But:
- Files can be large (thousands of lines)
- Only specific sections are relevant
- We can't dump everything into the context window

### The Solution: Persistent File Tracking

```
User opens file.py (lines 50-100)
         ↓
open_file() stores record to Memory API
         ↓
         {file} context injects the actual file content
         ↓
LLM sees: "=== file.py [lines 50-100] ===\n<actual content>"
```

### How It Works

1. **`open_file(path, line_start, line_end)`** stores to Memory API:
   ```python
   payload = {
       "content": f"open: {filename} [{line_range}]",
       "keywords": [session_id, "file", f"file:{filename}"],
       "properties": {"path": abs_path, "line_start": "50", "line_end": "100"}
   }
   requests.post(f"{MEMORY_API_URL}/memories", json=payload)
   ```

2. **`_open_files_context()`** reads from Memory API:
   ```python
   memories = _search_memories(session_id, "k:file")
   for mem in memories:
       path = mem["properties"]["path"]
       with open(path) as f:
           content = f.read()
       # Apply line range...
   ```

3. The context tag `{file}` is replaced with a list of all open files and their content.

---

## Context Deduplication: The Core Challenge

### The Problem: Duplicate Content

When the LLM processes a conversation, it sees:
- System prompt (with context tags resolved)
- Conversation history from Memory API
- Tool results

If we're not careful, the same information appears in multiple places:

```
System prompt: "...Your task is to fix the bug in api.py..."
Conversation: "User: can you fix the bug in api.py?"
              "Assistant: I'll look at api.py"
Tool result: "=== api.py ===\n# The actual code..."
```

The LLM sees "api.py" mentioned **three times**. Wasteful.

### Context Deduplication Strategies

#### Strategy 1: Explicit References Over Duplication

Instead of repeating information, use references:

```
System: "Fix the bug in the currently open file."
{files}: "=== api.py ===\n<actual code>"
Conversation: "User: fix the bug"
Tool: "Opened api.py"
```

The LLM learns to look at `{files}` rather than expecting file content to be repeated.

#### Strategy 2: Tool Results as Ground Truth

Tool results (`role: "tool"`) contain the authoritative information:

```json
{
  "role": "tool",
  "content": "Replaced lines 10-15 (fuzzy match 98%)",
  "tool_call_id": "abc123"
}
```

The LLM should trust this over re-reading the file.

#### Strategy 3: Summarization for Long Conversations

After many turns, the conversation gets long. The Memory API supports **temporal clustering** and **LLM summarization**:

```
Turn 1-10: User asked to add feature X
           LLM made several edits...
           (Summarized to: "Added feature X with 3 file changes")
           
Turn 11-50: (Full conversation preserved)

Turn 51+: (New active context)
```

This is handled by the Memory API's `/context` endpoint with the `summarize` parameter.

---

## The CodeHammer Workflow

```
1. User opens file
   └─ open_file() → Memory API

2. User asks question
   └─ Harness stores to Memory API
   └─ Core loads shard config (codehammer)
   └─ Core loads modules (file, shell, memory, time, web)
   
3. Core builds system prompt
   └─ {file} → _open_files_context() → actual file content
   └─ {shell} → current directory + available commands
   └─ {memory} → recent memories and search tips
   └─ {time} → current time
   └─ {web} → web tool documentation

4. Core calls LLM with:
   └─ System prompt (context tags resolved)
   └─ Conversation history (from Memory API)

5. LLM responds or calls tools
   
6. Tool results stored to Memory API
   └─ POST /context {role: "tool", content: "...", tool_call_id: "..."}

7. Repeat
```

---

## Why Not Just Dump Everything?

### Token Limits

LLMs have context windows (8K, 32K, 128K tokens). But:
- Longer context = higher cost
- Longer context = attention diffuses
- Longer context = slower inference

### Quality vs. Quantity

The LLM performs better with **relevant** information than **comprehensive** information:

```
BAD:    Dump 50 files, LLM can't find the relevant one
GOOD:   Open just the 3 files needed, LLM focuses on them
```

### Session Persistence

By storing to Memory API (not just local state):
- User can close and reopen the session
- LLM can access context from previous turns
- File tracking survives process restarts

---

## The Memory API Role

The Memory API is the **source of truth** for:

| Data | Storage | Access |
|------|---------|--------|
| Conversation history | `/context` POST | `/context` GET |
| Open files | `/memories` (keyword: "file") | `_search_memories()` |
| Tool results | `/context` POST | `/context` GET |
| Memories (long-term) | `/memories` POST | `/memories/search` |

The Core doesn't hold state — it reads from and writes to the Memory API each iteration.

---

## Summary

| Concept | Role |
|---------|------|
| **Shard** | Configuration (persona, modules, settings) |
| **Module** | Collection of tools + context providers |
| **Context Function** | Generates dynamic content for `{tag}` |
| **Memory API** | Persistent storage for all session data |
| **Deduplication** | References over repetition, summaries over raw history |

CodeHammer is the coding shard that combines:
- `{file}` — open files with actual content
- `{shell}` — run tests, git operations, etc.
- `{memory}` — store code decisions, search history
- `{time}` — timestamp awareness
- `{web}` — look up docs, search the web

Together, these provide a focused coding environment without drowning the LLM in context.
