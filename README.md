# Riven CodeHammer

A focused coding assistant that keeps working context **live in the system prompt** instead of relying on conversation history. This eliminates duplicate data, reduces token usage, and keeps the LLM focused.

---

## The Problem with Traditional Approaches

Most coding assistants work like this:

```
Turn 1: You: "open foo.py"
        Assistant: "Opened. Content: <entire file>"
        
Turn 2: You: "find the bug"
        Assistant: "Looking at foo.py..."
        System sends: Conversation history + foo.py again
        
Turn 3: You: "fix it"  
        System sends: Conversation + foo.py + previous responses...
        
Turn N: Same file sent over and over = massive token bloat
```

**Issues:**
- File content duplicated in every turn
- LLM gets confused about what's current
- Context window fills with stale data
- Token costs spiral

---

## How CodeHammer Works

### Live Context in System Prompt

CodeHammer doesn't rely on conversation history for file content. Instead, it keeps **live copies** in the system prompt that are refreshed each turn:

```
System Prompt (rebuilt every turn):
  
  ## Context (Static - cacheable)
  {file_help}      ← tool docs (never changes)
  {shell_help}     ← command docs (never changes)
  {planning_help}  ← planning docs (never changes)
  
  --- Dynamic ---
  {planning}       ← active goals with files (changes)
  {file}           ← open files with LIVE content (changes)
  {shell}          ← current directory (changes)
  
  {time}           ← current time (always changes, bottom)
```

The `{file}` tag injects the **current content from disk**, not a cached copy from history.

### Context = Ground Truth

| What | Traditional | CodeHammer |
|------|-------------|------------|
| Open files | Sent in conversation | Live in `{file}` |
| Goals/plans | In conversation history | Live in `{planning}` |
| Current directory | Mentioned in tools | Live in `{shell}` |
| Time | Implicit | Live in `{time}` |

The LLM **always looks at the system prompt** for state. It doesn't need to "remember" what's open — it's right there.

### No Duplicate Data

```
Traditional:
  "Here's foo.py" (turn 1)
  "Working on foo.py" (turn 2)
  "In foo.py on line 50" (turn 3)
  "foo.py line 50 again" (turn 4)
  
CodeHammer:
  System: "{file} contains foo.py" (constant)
  Conversation: "Fix the bug on line 50" (referenced, not duplicated)
```

---

## The Planning System

CodeHammer includes a planning module that tracks goals with linked files:

```
┌─────────────────────────────────────────────────┐
│  Goal: Fix auth bug                             │
│  Status: active | Priority: high                │
│  Files: auth.py, login.py                       │
└─────────────────────────────────────────────────┘
         │
         └── {planning} shows this to the LLM
                 │
                 └── LLM knows to open those files
```

### Workflow

1. **Create a goal** with files you need:
   ```
   create_goal("Fix auth bug", files=["auth.py", "login.py"])
   ```

2. **Work naturally** — the assistant sees the goal + files:
   ```
   {planning} → "🔴 #1 Fix auth bug
      - auth.py
      - login.py"
   {file} → live content of both files
   ```

3. **Close when done**:
   ```
   close_goal(goal_id=1)
   ```

---

## Token Efficiency

### Comparison

| Scenario | Traditional | CodeHammer |
|----------|-------------|------------|
| Edit 10 lines across 5 files | 5 files × N turns = huge | 5 files × 1 in system prompt |
| 20-turn debugging session | Token explosion | Stable (static parts cached) |
| Re-open file after context reset | Full re-send | File still tracked, content fresh |

### Why It's Faster

1. **Static context is cached** — tool docs, command lists only computed once
2. **Dynamic context is small** — only changed values (cwd, open files list)
3. **No conversation bloat** — the LLM refers to `{file}` instead of repeating file content
4. **File content read fresh** — edits are immediately visible, no stale context

---

## Modules

| Module | Purpose |
|--------|---------|
| **file/** | File tracking & editing (package) |
| **shell** | Run commands, manage background processes |
| **memory** | Store and search long-term memories |
| **memory_utils** | Memory API utilities |
| **planning** | Track goals with linked files |
| **shards** | Shard loading & execution |
| **time** | Current timestamp (always at bottom) |
| **web** | Fetch pages, search the web |

---

## Quick Start

1. Start the Memory API (port 8030)
2. Configure `secrets.yaml` with your LLM credentials
3. Run `python api.py`
4. Start a coding session

---

## The Core Idea

> **Context should be live, not history.**

The system prompt is the LLM's "workspace." Keep it clean:
- **Static docs** at the top (cached)
- **Dynamic state** in the middle (goals, files, cwd)
- **Time** at the bottom (always changes)

The LLM learns to look here for truth, not in conversation history. Less confusion, fewer tokens, faster responses.

---

## Files

```
riven_core/
├── README.md          # This file
├── docs/              # Architecture docs (THEORY.md, MODULES.md, etc.)
├── api.py             # HTTP server (your interface)
├── core.py            # Agent logic
├── config.py          # Configuration loading
├── config.yaml        # Default config
├── secrets.yaml       # API keys (gitignored)
├── context.py         # Context manager + memory client
├── _stream_worker.py  # Streaming utilities
├── killcheck.py       # Process cleanup helpers
├── shards/
│   ├── codehammer.yaml  # The coding shard config
│   ├── scribe.yaml      # Documentation shard
│   └── testhammer.yaml  # Testing shard
├── modules/
│   ├── file/          # File tracking & editing (package)
│   ├── file.py        # File module entry point
│   ├── shell.py       # Command execution
│   ├── memory.py      # Memory API client
│   ├── memory_utils.py    # Memory API utilities
│   ├── planning.py    # Goal tracking
│   ├── shards.py      # Shard loading & execution
│   ├── time.py        # Timestamp context
│   └── web.py         # Web fetching
└── tests/             # Test suite
```
