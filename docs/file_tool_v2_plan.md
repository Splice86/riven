# File Tool V2 — Robust Edition

**Date**: 2026-04-22
**Status**: In Progress
**Reference**: `/home/david/Projects/code_puppy/code_puppy/tools/file_modifications.py`

---

## Overview

This document outlines the plan to make `replace_text()` and related file tools more robust by:

1. **Wiring up existing helpers** — `_atomic_write()`, `_validate_python()`, `_verify_write()` are already in place
2. **Adding new functions** — `batch_edit()`, `delete_snippet()`
3. **Understanding Codehammer architecture** — keeping files "live" in system context without bloating LLM context

---

## Architecture: Codehammer

### The Concept

**Codehammer** is the file management pattern where:

1. **Files or sections are loaded into system context** — The LLM sees the file content directly
2. **Each session has an ID** — All operations are tied to a session for persistence and tracking
3. **The database stores state and history** — Not just content, but file changes and actions for reference
4. **Only minimal tool calls go into context turns** — The actual tool invocations are minimal; the context shows what matters

### How It Works

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                              SYSTEM CONTEXT                                   │
│                                                                               │
│  Session ID: abc123                                                           │
│  cwd: /home/user/project                                                      │
│                                                                               │
│  === Open Files ===                                                           │
│                                                                               │
│  === main.py [lines 0-50] ===                                                │
│  def hello():                                                                 │
│      print("world")                                                           │
│                                                                               │
│  === utils.py [lines 100-150] ===                                             │
│  def helper():                                                                │
│      return True                                                              │
│                                                                               │
│  --- File Context Stats ---                                                   │
│  Total open file tokens: 847                                                  │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                              MEMORY DATABASE                                  │
│                                                                               │
│  Session: abc123                                                              │
│  ├── k:file:main.py            → path: /home/user/main.py, lines: 0-50       │
│  ├── k:file:utils.py           → path: /home/user/utils.py, lines: 100-150   │
│  ├── k:action:replace_text     → session_id, path, old_text, new_text, ts    │
│  └── k:action:open_file        → session_id, path, lines, ts                 │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

### The Three Principles

#### 1. Files Are Loaded, Not Just Referenced

When `open_file(path, line_start, line_end)` is called:
- The file's content is loaded into the context for this session
- The LLM sees the actual code, not just metadata
- Line ranges control how much is loaded (0-50, 100-150, etc.)

This differs from "metadata-only" approaches where the LLM would only know "file X is open" without seeing its content.

#### 2. Session + Database = Persistence

Each session has a unique ID that ties everything together:
- `session_id` is passed to every database operation
- Files opened, edits made, and actions taken are all recorded
- The LLM can reference past actions because they're stored
- Database queries are keyed by session, so sessions don't leak into each other

#### 3. Minimal Tool Calls, Rich Context

Tool invocations are small (just path + old_text + new_text):
- The LLM sees what the file looks like BEFORE the edit
- The LLM sees what the file looks like AFTER (if using `diff_text()`)
- Tool calls themselves don't carry the full file content
- This keeps context turns clean while still showing everything relevant

### Contrast: Codehammer vs Other Approaches

| Approach | What LLM Sees | What DB Tracks | Context Efficiency |
|----------|--------------|----------------|--------------------|
| **Full file in context** | Everything, always | Nothing | ❌ Wastes tokens |
| **Metadata only** | "File X is open" | State | ⚠️ LLM can't see code |
| **Codehammer** | File sections + history | State + actions | ✅ Just right |

### Key Workflow

1. **LLM calls `open_file(path, line_start=0, line_end=100)`**
   - Session ID: `abc123`
   - Database stores: `k:file:main.py`, `{path, lines: 0-100}`
   - Context shows: The actual file content for lines 0-100

2. **LLM calls `replace_text()` or `diff_text()`**
   - Tool call is minimal (path, old_text, new_text)
   - Database stores: `k:action:replace`, `{path, old_text, result}`
   - Context shows: Result message + diff (if using `diff_text()`)

3. **LLM continues with context intact**
   - Remembers what's open, what was changed
   - Can reference past actions via database
   - Can re-open different line ranges as needed

### Implementation Details

- **`_file_context()`** — Queries database for all `k:file` entries for this session, reads only those line ranges from disk, formats for LLM
- **`open_file()`** — Writes to database: session_id, path, line_start, line_end, keywords
- **`replace_text()`** — Reads from disk (not context), writes to disk, writes action to database
- **Context refresh** — Each turn, `_file_context()` is called to rebuild the context from database state

---

## Current State of `modules/file.py`

### ✅ Already Implemented (Infrastructure)

| Component | Location | Status |
|-----------|----------|--------|
| `_atomic_write()` | Line 160 | ✅ Ready to use |
| `_verify_write()` | Line 199 | ✅ Ready to use |
| `_sanitize_content()` | Line 217 | ✅ Ready to use |
| `_validate_python()` | Line 238 | ✅ Ready to use |
| `_find_best_window()` | Line 261 | ✅ Ready to use |
| `EditResult` dataclass | Line 38 | ✅ Ready to use |
| `Replacement` dataclass | Line 85 | ✅ Ready to use |
| `FileEditSession` dataclass | Line 104 | ✅ Ready to use |
| `preview_replace()` | Line 561 | ✅ Working |
| `diff_text()` | Line 601 | ✅ Working |
| `replace_text()` | Line 492 | ⚠️ Doesn't use helpers |
| Context system (`_file_context`) | Line 376 | ✅ Working |

### ❌ Gaps

| Gap | Impact | Priority |
|-----|--------|----------|
| `replace_text()` bypasses helpers | Syntax errors not caught, writes not atomic | **CRITICAL** |
| No `batch_edit()` function | Can't do multi-replacement atomically | MEDIUM |
| No `delete_snippet()` function | Can't delete text precisely | MEDIUM |
| `diff_text()` missing unified diff | Harder to review changes | LOW |
| No callback system | Can't do permission checks | FUTURE |

---

## Implementation Plan

### Phase 1: Fix `replace_text()` — Wire Up Helpers

**Current code (line 553-555)**:
```python
try:
    with open(abs_path, 'w') as f:
        f.write(new_content)
except Exception as e:
    return f"Error saving {abs_path}: {e}"
```

**Problem**:
- No syntax validation
- No atomic write
- No verification
- Returns string, not `EditResult`

**New code**:
```python
# 1. Validate syntax for .py files
if abs_path.endswith('.py'):
    is_valid, error = _validate_python(new_content)
    if not is_valid:
        return EditResult(
            success=False,
            path=abs_path,
            message=f"Syntax validation failed",
            syntax_error=error,
            similarity=score
        ).to_string()

# 2. Sanitize surrogates
new_content = _sanitize_content(new_content)

# 3. Atomic write
try:
    _atomic_write(abs_path, new_content)
except Exception as e:
    return EditResult(
        success=False,
        path=abs_path,
        message=f"Write failed: {e}",
        similarity=score
    ).to_string()

# 4. Verify
if not _verify_write(abs_path, new_content):
    return EditResult(
        success=True,
        path=abs_path,
        message="Write succeeded but verification failed",
        changed=True,
        line_start=start + 1,
        line_end=end,
        similarity=score
    ).to_string()

return EditResult(
    success=True,
    path=abs_path,
    message=f"Replaced lines {start+1}-{end} (fuzzy match {score:.0%})",
    changed=True,
    line_start=start + 1,
    line_end=end,
    similarity=score
).to_string()
```

### Phase 2: Add `batch_edit()` Function

```python
async def batch_edit(
    path: str,
    replacements: list[Replacement],
    threshold: float = 0.95
) -> str:
    """Apply multiple replacements in one atomic operation.
    
    All replacements are applied sequentially. If any fails, the file
    remains unchanged (atomic behavior).
    
    Args:
        path: Path to the file
        replacements: List of Replacement dataclasses
        threshold: Minimum Jaro-Winkler similarity (0.0-1.0)
        
    Returns:
        EditResult formatted as string
    """
    path = os.path.expanduser(path)
    abs_path = os.path.abspath(path)
    
    try:
        with open(abs_path, 'r') as f:
            content = f.read()
    except Exception as e:
        return EditResult(success=False, path=abs_path, message=f"Read failed: {e}").to_string()
    
    original_content = content
    changes = []
    
    for rep in replacements:
        lines = content.splitlines(keepends=True)
        span, score = _find_best_window(lines, rep.old_str, threshold=threshold)
        
        if not span:
            best_span, best_score = _find_best_window(lines, rep.old_str, threshold=0.0)
            if best_span:
                start, end = best_span
                matched = ''.join(lines[start:end]).strip()
                return EditResult(
                    success=False,
                    path=abs_path,
                    message=f"No match for replacement",
                    similarity=best_score
                ).to_string()
            return EditResult(
                success=False,
                path=abs_path,
                message="Text not found"
            ).to_string()
        
        start, end = span
        lines[start:end] = rep.new_str.splitlines(keepends=True)
        content = ''.join(lines)
        changes.append((start, end, score))
    
    # Validate syntax for .py files
    if abs_path.endswith('.py'):
        is_valid, error = _validate_python(content)
        if not is_valid:
            return EditResult(
                success=False,
                path=abs_path,
                message="Syntax validation failed",
                syntax_error=error,
                similarity=changes[-1][2] if changes else 0.0
            ).to_string()
    
    # Sanitize
    content = _sanitize_content(content)
    
    # Atomic write
    try:
        _atomic_write(abs_path, content)
    except Exception as e:
        return EditResult(
            success=False,
            path=abs_path,
            message=f"Write failed: {e}"
        ).to_string()
    
    # Verify
    if not _verify_write(abs_path, content):
        return EditResult(
            success=True,
            path=abs_path,
            message="Write succeeded but verification failed",
            changed=True
        ).to_string()
    
    return EditResult(
        success=True,
        path=abs_path,
        message=f"Applied {len(replacements)} replacement(s)",
        changed=True,
        line_start=changes[0][0] + 1 if changes else None,
        line_end=changes[-1][1] + 1 if changes else None,
        similarity=changes[-1][2] if changes else None
    ).to_string()
```

### Phase 3: Add `delete_snippet()` Function

```python
async def delete_snippet(
    path: str,
    snippet: str
) -> str:
    """Remove the first occurrence of a text snippet from a file.
    
    Uses exact matching (no fuzzy). For fuzzy deletion, use batch_edit.
    
    Args:
        path: Path to the file
        snippet: Text to remove
        
    Returns:
        EditResult formatted as string
    """
    path = os.path.expanduser(path)
    abs_path = os.path.abspath(path)
    
    try:
        with open(abs_path, 'r') as f:
            original = f.read()
    except Exception as e:
        return EditResult(success=False, path=abs_path, message=f"Read failed: {e}").to_string()
    
    if snippet not in original:
        return EditResult(
            success=False,
            path=abs_path,
            message="Snippet not found in file"
        ).to_string()
    
    modified = original.replace(snippet, "", 1)
    
    # Validate syntax
    if abs_path.endswith('.py'):
        is_valid, error = _validate_python(modified)
        if not is_valid:
            return EditResult(
                success=False,
                path=abs_path,
                message="Syntax validation failed",
                syntax_error=error
            ).to_string()
    
    # Sanitize
    modified = _sanitize_content(modified)
    
    # Atomic write
    try:
        _atomic_write(abs_path, modified)
    except Exception as e:
        return EditResult(
            success=False,
            path=abs_path,
            message=f"Write failed: {e}"
        ).to_string()
    
    # Verify
    if not _verify_write(abs_path, modified):
        return EditResult(
            success=True,
            path=abs_path,
            message="Write succeeded but verification failed",
            changed=True
        ).to_string()
    
    return EditResult(
        success=True,
        path=abs_path,
        message="Snippet deleted from file",
        changed=True
    ).to_string()
```

### Phase 4: Update `diff_text()` with Unified Diff

Add proper unified diff output:

```python
import difflib

# In diff_text(), replace the return with:
diff = "".join(
    difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3  # context lines
    )
)

return (
    f"=== diff: {filename} lines {start+1}-{end} (match {score:.0%}) ===\n"
    f"\n--- BEFORE ---:\n{before}\n\n--- AFTER ---:\n{after}\n\n"
    f"--- UNIFIED DIFF ---:\n{diff}"
)
```

### Phase 5: Register New Functions

Add to `get_module()` CalledFns:

```python
CalledFn(
    name="batch_edit",
    description="Apply multiple text replacements in one atomic operation...",
    parameters={...},
    fn=batch_edit,
),
CalledFn(
    name="delete_snippet",
    description="Remove the first occurrence of a text snippet from a file...",
    parameters={...},
    fn=delete_snippet,
),
```

---

## Acceptance Criteria

- [ ] `replace_text()` never introduces syntax errors on valid Python files
- [ ] All writes use `_atomic_write()` (no partial writes)
- [ ] All writes are verified with `_verify_write()`
- [ ] `batch_edit()` applies multiple replacements atomically
- [ ] `delete_snippet()` removes text with exact matching
- [ ] `diff_text()` shows unified diff format
- [ ] All functions return `EditResult.to_string()`
- [ ] All new functions registered in `get_module()`

---

## Testing Plan

1. **Syntax validation tests**
   - Create a file with valid syntax
   - Call `replace_text()` with new text that creates invalid syntax
   - Expect failure before write occurs

2. **Atomic write tests**
   - Mock `_atomic_write` to fail partway
   - Verify original file is unchanged

3. **Verification tests**
   - Verify `_verify_write()` catches mismatches
   - Test with large files where memory != disk

4. **Batch edit tests**
   - Apply 3 replacements
   - Verify all succeed or all fail (atomic)
   - Test partial failure scenarios

5. **Delete snippet tests**
   - Delete text from middle of file
   - Verify content before and after is correct
   - Test snippet not found scenario

---

## Files to Modify

- `modules/file.py` — Add helpers wiring, new functions, update registrations

---

## Reference: Code Puppy vs Riven Comparison

### Side-by-Side Feature Comparison

| Feature | Riven (`modules/file.py`) | Code Puppy (`file_modifications.py`) | Winner |
|---------|---------------------------|--------------------------------------|--------|
| **Fuzzy Matching** | ✅ Jaro-Winkler + configurable threshold | ⚠️ Jaro-Winkler, hardcoded 0.95 | ✅ Riven |
| **Atomic Write** | ✅ `_atomic_write()` helper exists | ❌ Direct `open()` write | ✅ Riven |
| **Syntax Validation** | ✅ `_validate_python()` helper exists | ❌ None | ✅ Riven |
| **Write Verification** | ✅ `_verify_write()` helper exists | ❌ None | ✅ Riven |
| **Surrogate Handling** | ⚠️ `_sanitize_content()` exists | ✅ In every helper | ✅ Code Puppy |
| **Batch Replacements** | ⚠️ `Replacement` dataclass exists, no function | ✅ `_replace_in_file()` | ✅ Code Puppy |
| **Delete Snippet** | ❌ None | ✅ `_delete_snippet_from_file()` | ✅ Code Puppy |
| **Unified Diff** | ⚠️ Basic (BEFORE/AFTER only) | ✅ Always via `difflib.unified_diff()` | ✅ Code Puppy |
| **Structured Responses** | ✅ `EditResult` dataclass | ⚠️ Raw dicts | ✅ Riven |
| **Callback System** | ❌ None | ✅ `on_edit_file`, `on_delete_file` | ✅ Code Puppy |
| **Group IDs** | ❌ None | ✅ For operation tracking | ✅ Code Puppy |
| **Session/Context System** | ✅ MemoryDB + session_id | ❌ None (per-message only) | ✅ Riven |

### Implementation Pattern Comparison

#### Riven's Current `replace_text()` (line 492)
```python
# Problem: bypasses all helpers!
with open(abs_path, 'w') as f:
    f.write(new_content)
```

#### Code Puppy's `_replace_in_file()` (line 260)
```python
# Better: sanitizes, generates diff, reports clearly
original = f.read()
original = original.encode("utf-8", errors="surrogatepass").decode(...)
modified = original.replace(snippet, new_snippet, 1)
diff_text = "".join(difflib.unified_diff(original.splitlines(), modified.splitlines(), ...))
with open(file_path, "w") as f:
    f.write(modified)
return {"success": True, "path": file_path, "message": "Replacements applied.", "diff": diff_text}
```

### What Riven Should Borrow from Code Puppy

1. **Batch replacements** — Riven has the `Replacement` dataclass but no function to use it
2. **Delete snippet** — Simple helper that's missing from Riven
3. **Unified diff output** — Replace the basic BEFORE/AFTER with proper `difflib.unified_diff()`
4. **Surrogate sanitization in every helper** — Riven has the helper but doesn't use it consistently

### What Riven Has That Code Puppy Doesn't

1. **Atomic write with verification** — Critical for preventing corrupted files
2. **Syntax validation** — Prevents introducing syntax errors
3. **Structured `EditResult` responses** — Machine-readable, not just strings
4. **Session/context persistence** — Actions are tracked across turns
5. **Configurable threshold** — Fuzzy matching threshold can be tuned per-call

### Goal: Combine the Best

```
┌─────────────────────────────────────────────────────┐
│                    RIVEN V2                         │
├─────────────────────────────────────────────────────┤
│ Riven's:          │ Code Puppy's:                   │
│ ✅ EditResult     │ ✅ Batch replacements           │
│ ✅ Session/DB     │ ✅ Delete snippet               │
│ ✅ Atomic write   │ ✅ Unified diff always          │
│ ✅ Syntax check   │ ✅ Surrogate in every helper    │
│ ✅ Configurable   │ ✅ Clear error messages         │
│   threshold       │                                 │
├─────────────────────────────────────────────────────┤
│ Missing (needs work):                               │
│ ❌ Wire up helpers in replace_text()                │
│ ❌ Add batch_edit() function                        │
│ ❌ Add delete_snippet() function                    │
│ ❌ Update diff_text() with unified diff             │
└─────────────────────────────────────────────────────┘
```
