# Riven Core Agent - Process Flow Plan

## Problem Statement

Tool calls may modify the system context (via codehammer or other mechanisms). These modifications must be:
1. **Stored** to Memory API after tool execution
2. **Fetched** on subsequent LLM calls to ensure fresh context
3. **Applied** to the system prompt template for the next iteration

## Key Entities

| Entity | Responsibility |
|--------|----------------|
| **Memory API** | Persistent storage by `session_id`. Stores conversation history + context state. |
| **Core** | Stateless agent loop. Takes session_id, fetches context, runs LLM, executes tools, stores results. |
| **Harness** | Orchestrates. Stores user prompt to Memory before calling Core. |
| **Shard Config** | Defines modules, system template, memory settings. |
| **Context Functions** | Auto-run functions that inject dynamic values into system prompt via `{tag}` placeholders. |

## Process Flow

### Phase 1: Initialization (Pre-Core)

```
User Input
    ↓
Harness stores user message to Memory API
    ↓
Harness creates Core with shard config + LLM config + session_id
    ↓
Core loads modules from shard (registers called_fns and context_fns)
```

### Phase 2: Core Run Stream

```
run_stream(session_id)
    │
    ├─ Set session_id in context_var (modules can access it)
    │
    ├─ Build functions list from registry
    │
    ├─ Fetch history from Memory API (session_id)
    │   └─ Returns: [{"role": "user", "content": "..."}, ...]
    │
    └─ Loop:
        │
        ├─ [A] Build System Prompt
        │   │   context_fns run → {tag: content} dict
        │   │   System template replaces {tag} with content
        │   │   Result: "You are helpful. Current time: 2026-04-18..."
        │   │
        │   └─ If tool modified context in Memory → next iteration fetches updated state
        │
        ├─ [B] Build API Messages
        │   │   messages = [system] + history from Memory
        │   │
        │   └─ history includes: user + assistant + tool_results from this session
        │
        ├─ [C] Call LLM
        │   │   POST {model, messages, tools}
        │   │
        │   └─ Stream response
        │
        ├─ [D] Process Response
        │   │
        │   ├─ Token → yield {token: ...}
        │   │
        │   ├─ Thinking → yield {thinking: ...}
        │   │
        │   └─ Tool Calls → for each:
        │       │
        │       ├─ yield {tool_call: {id, name, arguments}}
        │       │
        │       ├─ Execute function with timeout
        │       │
        │       ├─ Store result to Memory API
        │       │   └─ POST /context {role: "tool", content: "fn: result", tool_call_id: ...}
        │       │
        │       └─ yield {tool_result: {id, name, content, error}}
        │
        └─ If NO tool calls:
            │
            ├─ yield {assistant: msg}
            │
            ├─ Store assistant message to Memory API
            │   └─ POST /context {role: "assistant", content: "..."}
            │
            └─ yield {done: True}
```

### Phase 3: Tool Call Context Modification (Critical Path)

When a tool call modifies context (e.g., codehammer updates a variable):

```
Tool Execution
    ↓
Tool modifies shared state (e.g., codehammer sets variable)
    ↓
Tool returns result with NEW context state
    ↓
Core stores result to Memory API
    ↓
[CRITICAL] Core should ALSO store updated context to Memory API
    ↓
Next iteration:
    ├─ Fetch history from Memory (includes tool results)
    ├─ Fetch context state from Memory (if stored separately)
    ├─ context_fns run (may read from Memory for fresh values)
    ├─ System prompt built with updated {tag} values
    └─ LLM sees updated context
```

## Memory API Schema

### Context Table

```json
{
  "session": "uuid",
  "role": "user|assistant|tool|system",
  "content": "message content",
  "tool_call_id": "optional - links tool results to calls",
  "context_data": {
    "key": "value",
    "time": "2026-04-18 01:00:00",
    "codehammer_vars": {...}
  }
}
```

### API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/context` | Store a message or context update |
| GET | `/context` | Fetch history + context for session |
| GET | `/context/state` | Fetch just context data (not history) |

## Implementation Status

### ✅ Issue 1: Mid-Run vs. Fetch Cycle

Context functions already read from Memory API on each iteration. `file_context()` calls `_search_memories()` every time, so file state is always fresh. No local accumulation of context state.

### ⚠️ Issue 2: Context Storage

Tool results are stored to Memory, but the **output of context functions is not stored separately**. Context is rebuilt fresh each iteration from Memory and the file system — this works because all context sources (open files, goals, cwd) are backed by Memory.

### ⚠️ Issue 3: Assistant Message with tool_calls

Assisted messages with `tool_calls` are stored as-is to Memory API. The LLM re-fetches them on subsequent iterations. This is acceptable in practice but could be normalized.

## Proposed Solution

### Approach: Store Context State Explicitly

After each tool execution (or periodically), store the current context state:

```python
async def _execute(self, call):
    result = await self._execute(call)
    
    # After successful execution, check if context changed
    context = self._build_context()
    memory.update_context(context)  # Store context state
    
    return result
```

### Approach: Context Functions Read from Memory

Context functions should be able to read tool-modified state from Memory:

```python
def get_codehammer_context():
    session_id = get_session_id()
    context = memory.get_context_state(session_id)
    return context.get("codehammer", "")
```

### Approach: Fetch-and-Rebuild Pattern

On each LLM call iteration:

```
1. Fetch history from Memory: messages[]
2. Fetch context state from Memory: {key: value}
3. context_fns run (may use Memory state or fresh compute)
4. Build system prompt with context_fns output
5. Build messages = [system] + history
6. Call LLM
```

## Summary of Key Points

1. **Memory API is the source of truth** for both history and context state
2. **Tool calls can modify context** - store changes to Memory immediately
3. **Fetch context on each iteration** - don't rely solely on local accumulation
4. **Context functions may need to read from Memory** to get tool-modified state
5. **System prompt is rebuilt each turn** from context_fns output

## TODO

- [ ] Consider normalizing assistant messages with `tool_calls` on re-fetch
- [ ] Add unit test: tool call modifies context → next LLM call sees update
- [ ] Add unit test: verify fetch pattern on each LLM call iteration

> **Deferred**: Explicit context state storage to Memory API — not needed since context functions rebuild from Memory + file system each turn. Current design is sufficient.
