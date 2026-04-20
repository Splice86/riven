# Riven Core Cleanup Plan

## Goals (Priority Order)

### GOAL 1: Extract shared memory utilities 🔴
- [x] Create `modules/memory_utils.py` with `_search_memories` and `_delete_memory`
- [x] Update `modules/file.py` to import from `memory_utils`
- [x] planning.py has _search_planning (adds k:planning) - intentionally separate
- [x] Add unit tests for memory utilities
- [x] Commit [ff8b732]

### GOAL 2: Remove dead code 🟠
- [x] Remove `full_response` accumulation in `core.py` `run_stream()` (already gone)
- [x] Remove unused `original_len` in `context.py` (already gone)
- [x] Remove legacy tool message parsing block in `context.py` (already gone)
- [ ] Add unit tests
- [ ] Commit

### GOAL 3: Consolidate config usage 🟠
- [x] Move `web.py` `DEFAULT_TIMEOUT` to use config `get()`
- [x] Move `api.py` host/port to config
- [ ] Fix `MEMORY_API_URL` import-time calls (cache in config, lazy-load in modules)
- [ ] Add unit tests
- [ ] Commit

### GOAL 4: Fix hardcoded model default 🟡
- [x] Model default stays in `config.py` — it's non-secret config, silent fallback is fine UX
- [x] `config.yaml` is the source of truth for production values
- [ ] Add unit test
- [ ] Commit

### GOAL 5: Consolidate debug logging 🟡
- [x] Pick `ContextManager.debug_save()` as canonical mechanism (manual dump not present in code)
- [x] Remove manual `DEBUG_CONTEXT_DIR` dump from `core.py` (already gone)
- [ ] Add unit test
- [ ] Commit

### GOAL 6: Fix silent exception handling 🟡
- [x] Add logging to `try/except pass` blocks across modules (none found - already clean)
- [ ] Add unit test for logging behavior
- [ ] Commit

### GOAL 7: Cleanup config.py internals 🟢
- [x] Fix `_deep_copy_dict` inline usage in `_deep_merge`
- [ ] Remove redundant `None` check in `_deep_copy_dict` (keep - intentional defensive guard)
- [ ] Commit

### GOAL 8: Add docstring clarifying `reorder_messages` 🟢
- [x] Clarify purpose of `reorder_messages` as belt-and-suspenders (already present)
- [ ] Commit

---

## Rules
- Write unit tests BEFORE making changes (TDD-lite)
- Commit after each goal with a clear message: `cleanup: <goal name> - <brief description>`
- Push after every commit
- Update this plan as goals complete
