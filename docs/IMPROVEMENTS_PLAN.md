# Riven Core — Improvement Plan

## Status: COMPLETE (all actionable items fixed, outstanding items documented below)

## Issues Found & Fixed

### 1. ✅ `import os` inside functions (planning.py)
- **Status**: FIXED (committed)
- **Problem**: `import os` appeared 5 times inside function bodies in `modules/planning.py`
- **Fix**: Moved to module-level import, removed all inline imports
- **Tests**: 13/13 pass

### 2. ✅ Duplicate shard `default.yaml`
- **Status**: FIXED (committed)
- **Problem**: `shards/default.yaml` was an exact copy of `shards/codehammer.yaml`
- **Fix**: Deleted `default.yaml`, it's now just an alias pointing to `codehammer` config defaults
- **Tests**: 5/5 pass (including duplicate detection test)

### 3. ✅ Hardcoded paths
- **Status**: FIXED (committed)
- **Problems**:
  - `shards/codehammer.yaml` had `debug_dir: "/home/david/Projects/..."` 
  - `core.py` had hardcoded `/home/david/Projects/riven_projects/riven_core/context_logs`
  - `core.py` error message hardcoded `port 8030`
- **Fix**: 
  - Removed `debug_dir` from `codehammer.yaml` (now from config.yaml)
  - `core.py` uses `os.path.dirname(__file__)` for relative resolution
  - Error message now uses actual `memory_url`
  - `context.py` `ContextManager` resolves relative paths to absolute using `Path(__file__).parent`
  - `config.yaml` now has `debug_dir` and `debug_snapshots` settings
  - `Core.__init__` falls back to config for debug settings

### 4. ✅ `import requests` inside function in api.py
- **Status**: FIXED (committed)
- **Problem**: `import requests` inside `send_message()` 
- **Fix**: Moved `import requests`, `import glob`, `import yaml` to module level
- **Tests**: 2/2 pass (inline import test now passes)

### 5. ✅ Duplicate shard listing code in api.py
- **Status**: FIXED (committed)
- **Problem**: Identical logic for globbing `shards/*.yaml` appeared in both `list_shards()` and `_load_shard()`
- **Fix**: Extracted `_shard_files()` helper used by both functions
- **Tests**: Shard listing test passes

### 6. ✅ Empty `Constants` section in context.py
- **Status**: FIXED (committed)
- **Problem**: `# Constants` section with no content between two section dividers
- **Fix**: Removed the empty section

### 7. ✅ `self.session_id = session_id` duplicated in `MemoryClient.__init__`
- **Status**: FIXED (committed)
- **Location**: `context.py` `MemoryClient.__init__`
- **Problem**: `session_id` assigned twice (once before `base_url`, once after)
- **Fix**: Removed the first assignment

### 8. ✅ `import re` inside `reorder_messages` method
- **Status**: FIXED (committed)
- **Location**: `context.py`, inside `reorder_messages` static method
- **Problem**: `import re` inside function body
- **Fix**: Moved `import re` to module level

### 9. ✅ `pass` statement in `prepare_messages_for_llm`
- **Status**: FIXED (committed)
- **Location**: `context.py`, `prepare_messages_for_llm` method
- **Problem**: Dead `pass` statement after truncation check
- **Fix**: Replaced with comment

### 10. ✅ `code_hammer` typo in config.yaml
- **Status**: FIXED (committed)
- **Location**: `config.yaml`
- **Problem**: `default_shard: code_hammer` should be `codehammer`
- **Fix**: Changed to `codehammer`

---

## Items NOT Fixed (documented as non-issues or low-priority)

### 11. Magic numbers in `truncate_tool_result` (200, 150)
- **Location**: `context.py` `ContextManager.__init__`
- **Note**: These are reasonable defaults. Could be made configurable via config.yaml if desired.
- **Decision**: Left as-is — not a bug, just a potential future config improvement.

### 12. `aclose()` on async generator
- **Location**: `api.py` `generate()`
- **Note**: `aclose()` is Python 3.11+. Project uses Python 3.13, so no issue.
- **Decision**: Left as-is — acceptable given Python version.

### 13. Non-streaming mode loop behavior
- **Location**: `api.py`, non-streaming path
- **Status**: Verified — single-turn non-streaming is intentional behavior. Harness sends one message per request, so `break` → `return` is correct. The outer `while True` exists for streaming multi-turn sessions.
- **Decision**: Closed as intentional.

### 14. ⬜ `__pycache__` in modules/
- **Status**: Already covered by `.gitignore`
- **Decision**: No action needed.

---

## Commits Made

1. **fix: move import os to module level in planning.py** — planning tests + init file
2. **fix: remove redundant default.yaml shard and hardcoded paths** — shards tests + conftest
3. **fix: dedupe shard listing in api.py, move imports to module level** — api tests, context fixes, config typo fix

## Final Test Count
- **20/20 tests passing** (planning: 13, shards: 5, api: 2)

## Files Modified

- `modules/planning.py`
- `modules/__init__.py`
- `shards/default.yaml` (deleted)
- `shards/codehammer.yaml`
- `core.py`
- `context.py`
- `config.yaml`
- `api.py`
- `tests/conftest.py`
- `tests/test_planning.py`
- `tests/test_shards.py`
- `tests/test_api.py`
- `IMPROVEMENTS_PLAN.md`
