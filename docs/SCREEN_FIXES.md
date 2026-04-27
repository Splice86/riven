"""Screen System Fix Plan

## Issues Identified (from code review)

### Issue 1: Raw HTML / Changes Not Populating
**Root cause**: In `_broadcaster.py`, `broadcast_edit()` hardcodes `old_version=0`:
    diff = snapshots.compute_diff(path, old_version=0, new_version=new_version)
This treats every diff as if the file is empty, causing wrong indices in the frontend.

**Files**: modules/file/screens/_broadcaster.py

**Fix**:
- Store the current version per path+uid in the registry or snapshot store
- Pass actual old_version to compute_diff()
- Fix the frontend's renderLines 'added' action to handle diff sections properly

### Issue 2: New Screen Doesn't Show Content Until Refreshed
**Root cause**: 
- `open_file()` doesn't broadcast to already-bound screens
- `track_screen_bound` only called via screen_bind tool, not automatically on open
- Snapshot might not be sent immediately on bind

**Files**: modules/file/editor.py, modules/file/__init__.py, modules/file/screens/_tools.py

**Fix**:
- Option A: Have open_file() auto-broadcast snapshot to screens bound to that path
- Option B: Ensure screen_bind sends snapshot immediately (it does via bc.send_snapshot)

### Issue 3: Screen Doesn't Blank When File Is Closed
**Root cause**: close_file() deletes memory entries but never notifies screens.
Registry screen.bound_path is never cleared on close.

**Files**: modules/file/editor.py, modules/file/__init__.py

**Fix**:
- Add screen release notification on close_file()
- Get UIDs bound to the path being closed
- Broadcast "released" message to those screens

### Issue 4: Title Shows "Riven Screen" Instead of File Name
**Root cause**: 
- The <title> tag is hardcoded as "Riven Screen"
- The #header .title span is never updated with the file name
- The header shows file-path in .meta but title stays static

**Files**: modules/file/static/screen.html

**Fix**:
- Update #header .title to show file name when bound
- Update <title> tag to show file name or "Riven Screen" when idle

### Issue 5: session_id Attribute Missing from ScreenConnection
**Root cause**: 
- ScreenConnection class doesn't have session_id field
- broadcast_bind() references screen.session_id which doesn't exist
- send_snapshot_to_session() calls registry.get_by_session() which doesn't exist

**Files**: modules/file/screens/_registry.py, modules/file/screens/_broadcaster.py

**Fix**:
- Add session_id to ScreenConnection.__slots__ and __init__
- Store session_id on registration in _ws.py
- Remove or fix broadcast_bind's session_id reference
- Remove or fix send_snapshot_to_session (or implement get_by_session)

---

## Fix Execution Order

1. [x] Fix Issue 5 (session_id / missing attrs) - foundation issues
2. [x] Fix Issue 4 (title/header display) - straightforward HTML fix
3. [x] Fix Issue 1 (raw HTML/diff logic) - the big one
4. [x] Fix Issue 3 (blank on close) - needs close_file modification
5. [x] Fix Issue 2 (auto-broadcast on open) - open_file modification

## Files to Modify

1. modules/file/screens/_registry.py       - Add session_id to ScreenConnection
2. modules/file/screens/_ws.py             - Store session_id on registration
3. modules/file/screens/_broadcaster.py    - Fix old_version, remove broken funcs
4. modules/file/screens/_tools.py          - Add close notification support
5. modules/file/static/screen.html         - Update title/header display
6. modules/file/editor.py                  - Add close_file broadcast
7. modules/file/__init__.py                - Wire close_file broadcast
"""
