# Riven Core Cleanup Plan

## Goals (Priority Order)

### GOAL 1: Extract shared memory utilities 🔴
- [ ] Create `modules/memory_utils.py` with `_search_memories` and `_delete_memory`
- [ ] Update `modules/file.py` to import from `memory_utils`
- [ ] Update `modules/planning.py` to import from `memory_utils`
- [ ] Add unit tests for memory utilities
- [ ] Commit

### GOAL 2: Remove dead code 🟠
- [ ] Remove `full_response` accumulation in `core.py` `run_stream()`
- [ ] Remove unused `original_len` in `context.py`
- [ ] Remove legacy tool message parsing block in `context.py`
- [ ] Add unit tests
- [ ] Commit

### GOAL 3: Consolidate config usage 🟠
- [ ] Move `web.py` `DEFAULT_TIMEOUT` to use config `get()`
- [ ] Move `api.py` host/port to config
- [ ] Fix `MEMORY_API_URL` import-time calls (cache in config, lazy-load in modules)
- [ ] Add unit tests
- [ ] Commit

### GOAL 4: Fix hardcoded model default 🟡
- [ ] Remove hardcoded `MiniMax-M2.7` default from `config.py`
- [ ] Ensure `config.yaml` is the single source of truth
- [ ] Add unit test
- [ ] Commit

### GOAL 5: Consolidate debug logging 🟡
- [ ] Pick `ContextManager.debug_save()` as canonical mechanism
- [ ] Remove manual `DEBUG_CONTEXT_DIR` dump from `core.py`
- [ ] Add unit test
- [ ] Commit

### GOAL 6: Fix silent exception handling 🟡
- [ ] Add logging to `try/except pass` blocks across modules
- [ ] Add unit test for logging behavior
- [ ] Commit

### GOAL 7: Cleanup config.py internals 🟢
- [ ] Fix `_deep_copy_dict` inline usage in `_deep_merge`
- [ ] Remove redundant `None` check in `_deep_copy_dict`
- [ ] Commit

### GOAL 8: Add docstring clarifying `reorder_messages` 🟢
- [ ] Clarify purpose of `reorder_messages` as belt-and-suspenders
- [ ] Commit

---

## Rules
- Write unit tests BEFORE making changes (TDD-lite)
- Commit after each goal with a clear message: `cleanup: <goal name> - <brief description>`
- Push after every commit
- Update this plan as goals complete
