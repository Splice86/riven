# Riven Modules Reference

| Module | Called Functions (Tools) | Static Tag | Dynamic Tag |
|--------|--------------------------|------------|-------------|
| **file** | `open_file`, `replace_text`, `close_file`, `close_all_files`, `file_info` | `{file_help}` | `{file}` |
| **shell** | `run`, `run_background`, `kill`, `cd`, `get_cwd`, `which` | `{shell_help}` | `{shell}` |
| **memory** | `search_memories`, `add_memory`, `get_memory`, `list_memories`, `get_memory_stats`, `add_link`, `delete_memory`, `update_memory`, `execute_sql` | `{memory_help}` | — |
| **time** | — (context only) | — | `{time}` |
| **web** | `fetch_page`, `fetch_page_links`, `web_search` | `{web_help}` | — |
| **planning** | `create_goal`, `add_file_to_goal`, `remove_file_from_goal`, `update_goal_status`, `list_goals`, `get_goal`, `close_goal` | `{planning_help}` | `{planning}` |

**Convention:** Static context (`_help`) goes at TOP of prompt (cacheable). Dynamic context (`_context`) goes AFTER statics.

---

## Detailed Function Reference

### file module

> Manages open files in context. Files are tracked in Memory API and actual content is injected via `{file}`.

| Function | Description | Parameters |
|----------|-------------|------------|
| `open_file` | Open a file and add to context | `path`, `line_start?`, `line_end?` |
| `replace_text` | Fuzzy-match text replacement (auto-saves) | `path`, `old_text`, `new_text` |
| `close_file` | Close a specific file/range | `filename`, `line_start?`, `line_end?` |
| `close_all_files` | Close all open files | _(none)_ |
| `file_info` | Get file metadata | `path` |

**Context Output:** Lists all open files with their actual content, file context stats

---

### shell module

> Execute shell commands with timeout and process group handling.

| Function | Description | Parameters |
|----------|-------------|------------|
| `run` | Execute command (SIGTERM→SIGKILL on timeout) | `command`, `timeout?`, `cwd?` |
| `run_background` | Start process, get PID + log path | `command`, `cwd?` |
| `kill` | Send signal to process | `pid`, `sig?` (15=SIGTERM, 9=SIGKILL) |
| `cd` | Change working directory | `path` |
| `get_cwd` | Get current directory | _(none)_ |
| `which` | Find executable path | `program` |

**Context Output:** Current directory, available commands, usage tips

---

### memory module

> Long-term storage via Memory API. Search, store, link, update memories.

| Function | Description | Parameters |
|----------|-------------|------------|
| `search_memories` | Search with DSL query | `query`, `limit?` |
| `add_memory` | Store new memory | `content`, `keywords?`, `properties?` |
| `get_memory` | Get by ID | `memory_id` |
| `list_memories` | List recent memories | `limit?` |
| `get_memory_stats` | Database statistics | _(none)_ |
| `add_link` | Link two memories | `source_id`, `target_id`, `link_type?` |
| `delete_memory` | Delete by ID | `memory_id` |
| `update_memory` | Update metadata | `memory_id`, `properties?`, `keywords?` |
| `execute_sql` | Raw SQL (debug only) | `sql`, `params?` |

**Search DSL:**
- `k:keyword` — exact keyword match
- `s:keyword` — semantic similarity
- `q:text` — semantic text search
- `d:date` — date filter (`d:last 7 days`)
- `p:key=value` — property filter
- `AND`, `OR`, `NOT` — operators

**Context Output:** Tool documentation, usage tips

---

### time module

> Current time as dynamic context only. No callable functions.

**Context Output:** `Current time: YYYY-MM-DD HH:MM:SS` (at bottom of prompt)

---

### web module

> Fetch web pages via lynx, search DuckDuckGo.

| Function | Description | Parameters |
|----------|-------------|------------|
| `fetch_page` | Get page text content | `url` |
| `fetch_page_links` | Extract all links | `url` |
| `web_search` | Search DuckDuckGo | `query`, `num_results?` |

**Context Output:** Tool documentation, lynx installation note

---

### planning module

> Goal tracking with file associations. Goals store which files are relevant so the assistant knows what to have open.

| Function | Description | Parameters |
|----------|-------------|------------|
| `create_goal` | Create a new goal | `title`, `description?`, `priority?`, `files?` |
| `add_file_to_goal` | Link a file to a goal | `goal_id`, `file_path` |
| `remove_file_from_goal` | Unlink a file | `goal_id`, `file_path` |
| `update_goal_status` | Change status | `goal_id`, `status` (active/paused/complete) |
| `list_goals` | List all goals | `status?` (filter) |
| `get_goal` | Full goal details + files | `goal_id` |
| `close_goal` | Mark complete | `goal_id` |

**Priority Levels:** critical > high > medium > low

**Context Output:** Active goals with their linked files (so assistant knows what to open)

---

## Usage in Shards

```yaml
# shards/codehammer.yaml
modules:
  - time       # {time} - current time (dynamic)
  - shell      # {shell_help} (static), {shell} (dynamic)
  - file       # {file_help} (static), {file} (dynamic)
  - memory     # {memory_help} (static)
  - web        # {web_help} (static)
  - planning   # {planning_help} (static), {planning} (dynamic)

system: |
  ## Context (Static - cacheable)
  
  {file_help}
  {shell_help}
  {web_help}
  {memory_help}
  {planning_help}
  
  --- Dynamic ---
  
  {planning}
  {file}
  {shell}
  
  {time}  # Bottom - always changes
```

**Convention:** Static context (`_help`) goes at TOP of prompt (cacheable). Dynamic context (`_context`) goes AFTER statics. `{time}` always at bottom since it changes every call.
