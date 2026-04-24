# File Tool Modifications Plan

**Date**: 2026-04-22
**Status**: Planned
**Reference**: `/home/david/Projects/code_puppy/code_puppy/tools/file_modifications.py`

---

## Overview

The current `replace_text()` implementation in `modules/file.py` frequently introduces syntax errors and indentation problems. This document outlines the steps to make it more robust by adopting patterns from Code Puppy's `file_modifications.py`.

---

## Current Problems

1. **No validation step** — `replace_text()` auto-saves immediately with no preview
2. **No syntax checking** — never validates Python syntax before writing
3. **No retry logic** — fails completely if the fuzzy match is wrong
4. **No verification** — doesn't confirm the change actually worked
5. **Direct file write** — no atomic write pattern

---

## Reference Implementation

Code Puppy's approach (`file_modifications.py`):

### Key Functions

| Function | Lines | Purpose |
|----------|-------|---------|
| `diff_text()` | 100-150 | Preview changes without modifying |
| `apply_patch()` | 186-220 | Execute replacement with retry logic |
| `_apply_regex_based()` | 275-350 | Regex-based replacement attempt |
| `_apply_line_by_line()` | 355-450 | Fallback line-by-line matching |
| `_validate_file()` | 460-480 | Validate result with `ast.parse()` |
| `_atomic_write()` | 229-237 | Atomic write via temp file |

### Validation Loop (lines 186-220)

```python
def apply_patch(path, old_text, new_text, timeout=5, max_retries=3):
    for attempt in range(max_retries):
        try:
            # Try regex-based replacement
            content = _apply_regex_based(path, old_text, new_text)
        except Exception:
            # Fallback to line-by-line
            content = _apply_line_by_line(path, old_text, new_text)
        
        # Validate syntax before writing
        if _validate_file(content):
            _atomic_write(path, content)
            return True
    return False
```

---

## Implementation Steps

### Step 1: Add Helper Functions

Add to `modules/file.py`:

```python
import ast
import tempfile
import os

def _validate_python(content: str, path: str) -> tuple[bool, str | None]:
    """Validate Python syntax. Returns (is_valid, error_message)."""
    try:
        ast.parse(content)
        return True, None
    except SyntaxError as e:
        return False, f"Syntax error in {path}:{e.lineno}: {e.msg}"

def _atomic_write(path: str, content: str):
    """Write content atomically using temp file + rename."""
    dir_path = os.path.dirname(path) or '.'
    fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
```

### Step 2: Create `preview_replace()` Logic (already exists)

The `preview_replace()` function already provides preview capability. Ensure it shows the exact text that will be replaced.

### Step 3: Create `diff_text()` Function

Add a function that shows before/after without modifying:

```python
async def diff_text(
    path: str,
    old_text: str,
    new_text: str,
    threshold: float = 0.95
) -> str:
    """Show the before/after of a proposed replacement without modifying."""
    # Find the match using fuzzy matching
    match_result = _find_fuzzy_match(path, old_text, threshold)
    if not match_result:
        return f"No match found for the specified text in {path}"
    
    start_line, end_line, matched_text = match_result
    
    with open(path) as f:
        lines = f.readlines()
    
    before = ''.join(lines[max(0, start_line-2):start_line])
    before += matched_text
    before += ''.join(lines[end_line:min(len(lines), end_line+2)])
    
    after = ''.join(lines[max(0, start_line-2):start_line])
    after += new_text
    after += ''.join(lines[end_line:min(len(lines), end_line+2)])
    
    return f"=== BEFORE (lines {start_line}-{end_line}) ===\n{before}\n\n=== AFTER ===\n{after}"
```

### Step 4: Rewrite `replace_text()` with Retry Logic

```python
async def replace_text(
    path: str,
    old_text: str,
    new_text: str,
    threshold: float = 0.95,
    max_retries: int = 3
) -> str:
    """Fuzzy-match replacement with validation and retry logic."""
    for attempt in range(max_retries):
        try:
            # Find the match
            match_result = _find_fuzzy_match(path, old_text, threshold)
            if not match_result:
                return f"No match found for the specified text in {path}"
            
            start_line, end_line, matched_text = match_result
            
            # Read the file
            with open(path) as f:
                content = f.read()
            
            # Check if we're doing a line-based or full-file replacement
            lines = content.splitlines(keepends=True)
            
            if len(lines) > 0 and matched_text in content:
                # Simple full-text replacement
                new_content = content.replace(matched_text, new_text, 1)
            else:
                # Line-by-line replacement
                new_lines = []
                i = start_line
                for line in lines:
                    if i == start_line:
                        new_lines.append(new_text)
                        if not new_text.endswith('\n') and i < len(lines):
                            new_lines.append('\n')
                    elif i > start_line and i <= end_line:
                        continue  # Skip old text lines
                    else:
                        new_lines.append(line)
                    i += 1
                new_content = ''.join(new_lines)
            
            # Validate Python syntax if file is .py
            if path.endswith('.py'):
                is_valid, error = _validate_python(new_content, path)
                if not is_valid:
                    return f"Validation failed: {error}"
            
            # Atomic write
            _atomic_write(path, new_content)
            
            # Verify the change
            with open(path) as f:
                verify_content = f.read()
            
            if new_text in verify_content:
                return f"Successfully replaced text in {path}"
            else:
                return f"Write succeeded but verification failed"
        
        except Exception as e:
            if attempt == max_retries - 1:
                return f"Failed after {max_retries} attempts: {e}"
            # Retry on failure
    
    return "Unknown error occurred"
```

### Step 5: Add Verification Helper

```python
async def verify_change(path: str, expected_snippet: str) -> bool:
    """Verify a change was applied correctly."""
    try:
        with open(path) as f:
            content = f.read()
        return expected_snippet in content
    except Exception:
        return False
```

---

## Testing Plan

1. Test with intentional syntax errors — should be caught before write
2. Test with fuzzy match failures — should retry or fail gracefully
3. Test atomic write — should not corrupt file on partial writes
4. Test verification — should detect failed writes
5. Compare before/after with Code Puppy's test suite

---

## Files to Modify

- `modules/file.py` — Add helper functions, rewrite `replace_text()`

---

## Acceptance Criteria

- [ ] `replace_text()` never introduces syntax errors on valid Python files
- [ ] Failed matches are reported clearly, not silently skipped
- [ ] All writes are atomic (no partial writes)
- [ ] Verification confirms changes before reporting success
- [ ] Retry logic handles transient failures
