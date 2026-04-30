"""File module for Riven.

Provides file operations including:
- open_file: Add file to context
- open_function: Open specific class/function by name (AST-based)
- replace_text: Fuzzy-match replacement with auto-save
- batch_edit: Multiple replacements in one pass
- And more...

Implementation split into:
- editor.py: FileEditor class with all operations
- code_parser.py: AST-based code extraction
- memory.py: Memory tracking helpers
"""

import os
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

from modules import CalledFn, ContextFn, Module, get_session_id
from modules.memory_utils import _search_memories, _delete_memory, _set_memory

# Re-export requests for backward compatibility with tests
# Tests may mock modules.file.requests.post
import requests as requests_module
requests = requests_module

# Import from submodules
from modules.file.editor import (
    EditResult,
    FileEditor,
    Replacement,
    _atomic_write,
    _atomic_write_sync,
    _file_type,
    _find_best_window,
    _generate_diff,
    _sanitize_content,
    _validate_python,
)

from modules.file.code_parser import (
    CodeDefinition,
    DefinitionExtractor,
    _extract_code_definitions,
    _find_definitions_by_name,
    _extract_definition_source,
)

from modules.file.git import (
    _run_git,
    _is_git_repo,
    _is_git_tracked,
    _get_git_hash,
    _git_status,
    _git_status_summary,
    _git_warning,
)

from modules.file.memory import (
    format_file_history,
    get_file_history,
    get_open_files,
    hash_content,
    track_file_change,
)

# Screen subsystem
from modules.file.screens import (
    screen_list,
    screen_bind,
    screen_release,
    screen_status,
    screen_highlight,
)
from modules.file.screens import (
    broadcast_edit as _bc,
    broadcast_release_for_path,
    send_snapshots_for_path,
    send_snapshot_to_uid,
    register_routes as _register_screen_routes,
)
from modules.file.screens.constants import MEMORY_KEYWORD_PREFIX as SCREEN_KW_PREFIX
from modules.file.screens import constants as _screen_const

from modules.file.constants import MEMORY_KEYWORD_PREFIX, make_open_file_keyword, build_search_query, PROP_FILENAME, PROP_PATH, PROP_LINE_START, PROP_LINE_END


# =============================================================================
# File Editor Instance
# =============================================================================

_file_editor = FileEditor()


async def _broadcast_after_edit(path: str, session_id: str = "") -> None:
    """Broadcast a file edit to bound screens.

    Called after every successful edit. Errors are swallowed so they never
    interfere with the edit operation.
    """
    if not session_id:
        return
    try:
        from modules.file.memory import get_screen_uids_for_path
        from modules.file.screens import broadcast_edit as _bc
        uids = get_screen_uids_for_path(session_id, path)
        if uids:
            await _bc(path, uids)
    except Exception as e:
        import logging
        logging.getLogger("modules.file").warning(f"Screen broadcast error: {e}")


async def _broadcast_after_close(path: str, session_id: str = "") -> None:
    """Broadcast a file close to screens bound to that path.

    Called after a file is closed so screens can clear their content and go idle.
    Errors are swallowed so they never interfere with the close operation.
    """
    if not session_id:
        return
    try:
        from modules.file.screens import broadcast_release_for_path as _br
        # Normalize path so it matches what was stored during open/screen_bind
        abs_path = os.path.abspath(path)
        await _br(abs_path)
    except Exception as e:
        import logging
        logging.getLogger("modules.file").warning(f"Screen close broadcast error: {e}")


async def _broadcast_after_open(path: str, session_id: str = "") -> None:
    """Broadcast a file open to screens already bound to that path.

    Called after a file is opened so any screen already watching the file
    receives the current content. Errors are swallowed silently.
    """
    if not session_id:
        return
    try:
        from modules.file.screens import send_snapshots_for_path as _ss
        # Normalize path so it matches what was stored during open/screen_bind
        abs_path = os.path.abspath(path)
        await _ss(abs_path)
    except Exception as e:
        import logging
        logging.getLogger("modules.file").warning(f"Screen open broadcast error: {e}")


def register_routes(app) -> None:
    """Register all file module routes (including screens) with the FastAPI app."""
    from fastapi.staticfiles import StaticFiles
    import os

    # Mount static files for screen.html
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static/file", StaticFiles(directory=static_dir), name="file_static")

    # Screen WebSocket and HTTP routes
    from modules.file.screens import register_routes as _sr
    _sr(app)
    # Screen broadcasting is enabled lazily on first edit


# =============================================================================
# Forwarding Functions (connect FileEditor to CalledFn interface)
# =============================================================================

async def open_file(path: str, line_start: int = None, line_end: int = None, allow_untracked: bool = False) -> str:
    """Open a file and add it to the file context."""
    return await _file_editor.open_file(path, line_start, line_end, allow_untracked)


async def close_file(name: str, line_start: int = None, line_end: int = None) -> str:
    """Close a file from the file context."""
    return await _file_editor.close_file(name, line_start, line_end)


async def close_all_files() -> str:
    """Close all files from the file context."""
    return await _file_editor.close_all_files()


async def replace_text(
    path: str,
    old: str,
    new: str,
    threshold: float = 0.95,
    validate_syntax: bool = True
) -> str:
    """Replace text in a file using fuzzy matching."""
    return await _file_editor.replace_text(path, old, new, threshold, validate_syntax)


async def batch_edit(
    path: str,
    replacements: list,
    threshold: float = 0.95,
    validate_syntax: bool = True
) -> EditResult:
    """Apply multiple replacements in a single pass."""
    reps = []
    for r in replacements:
        if isinstance(r, Replacement):
            reps.append(r)
        else:
            reps.append(Replacement(old_str=r["old"], new_str=r["new"]))
    return await _file_editor.batch_edit(path, reps, threshold, validate_syntax)


async def delete_snippet(path: str, snippet: str, threshold: float = 0.95) -> EditResult:
    """Remove a snippet from a file."""
    return await _file_editor.delete_snippet(path, snippet, threshold)


async def write_text(path: str, content: str, create_parent_dirs: bool = False) -> str:
    """Write content to a file."""
    return await _file_editor.write_text(path, content, create_parent_dirs)


async def delete_file(path: str) -> EditResult:
    """Delete a file."""
    return await _file_editor.delete_file(path)


async def open_function(
    path: str,
    name: str,
    include_docstring: bool = True,
    include_decorators: bool = True
) -> str:
    """Open a specific class or function by name using AST parsing."""
    return await _file_editor.open_function(path, name, include_docstring, include_decorators)


async def restore_from_git(path: str) -> str:
    """Restore a file to its last committed state in git."""
    return await _file_editor.restore_from_git(path)


async def preview_replace(path: str, old: str, threshold: float = 0.95) -> str:
    """Preview where a replacement would match."""
    return await _file_editor.preview_replace(path, old, threshold)


async def diff_text(path: str, old: str, new: str, threshold: float = 0.95) -> str:
    """Show diff of a proposed replacement."""
    return await _file_editor.diff_text(path, old, new, threshold)


async def search_files(pattern: str, path: str = ".") -> str:
    """Search for pattern in files."""
    return await _file_editor.search_files(pattern, path)


async def list_dir(path: str = ".") -> str:
    """List directory contents."""
    return await _file_editor.list_dir(path)


async def file_info(path: str) -> str:
    """Get information about a file."""
    return await _file_editor.file_info(path)


async def pwd() -> str:
    """Get current working directory."""
    return await _file_editor.pwd()


async def chdir(path: str) -> str:
    """Change current working directory."""
    return await _file_editor.chdir(path)


async def list_open_files() -> str:
    """List all open files for current session."""
    return _file_editor.list_open_files()


async def get_file_history(path: str = None) -> str:
    """Get file change history.
    
    Args:
        path: Optional path to filter by (default: None = all files)
        
    Note: For backward compatibility, if path looks like a session ID
    (contains 'session' or starts with 'test-'), it's treated as path filter.
    """
    session_id = get_session_id()
    from modules.file.memory import get_file_history as _get_file_history_impl
    memories = _get_file_history_impl(session_id, path)
    return format_file_history(memories)


def screen_context() -> str:
    """Context function that injects current screen status for the session.

    Reads live screen data from the sync-accessible session cache so it can be
    called from the synchronous context-building path.
    """
    from config import get
    session_id = get_session_id()
    port = get('server.port', 8000)

    try:
        from modules.file.screens import get_session_screens_sync
        screens = get_session_screens_sync(session_id)
    except Exception:
        return f"[Screens] No screens available. Open http://localhost:{port}/module/file/screens to register a screen."

    if not screens:
        return (
            f"[Screens] No screens registered for this session.\n"
            f"Open http://localhost:{port}/module/file/screens "
            f"in a browser tab, then call screen_list() to see the UID."
        )

    lines = [f"[Screens] {len(screens)} screen(s) online for this session:"]
    for s in screens:
        bound = s.get("bound_path")
        status = f"bound to {bound}" if bound else "idle (no file)"
        lines.append(f"  [{s['uid']}] {s['client_name']} — {status}")

    lines.append("")
    lines.append(f"Call screen_bind(\"<path\", \"<uid>\") to bind a screen to a file.")
    lines.append(f"Call screen_highlight(\"<path>\", start, end) to scroll+flash a line range.")
    return "\n".join(lines)


def _file_help() -> str:
    """Static tool documentation - does not change between calls."""
    from modules import _tool_ref  # Local import to avoid top-level cycle
    return """## File Tools (Help)

### CRITICAL: Context Budget
Every file open consumes context space. LLM context windows are finite.
- Keep 2-4 files open maximum at any time.
- Close files the moment you no longer need them — do not wait.
- Open files are listed in context below ({file}). Check list_open_files() before adding more.

### File Lifecycle Rules
1. **BEFORE opening**: always call list_open_files() first to see what's already in context.
   - If the file is already open, read from context — do NOT call open_file() again.
   - If the file is open with a partial range and you need the full file, close it first,
     then open it without line bounds. If it's already open with a wide range
     (e.g. lines 0-to-end or lines 0-1200+), just work with what's there — no need to re-open.
2. **When you open a file**: its content is immediately available in the {file} context block. Proceed to work with it — do not ask the user what to look at.
3. **WHILE working**: if you switch to a new goal or task and the open files are no longer relevant,
   call close_file() on the old ones before opening new ones.
4. **AFTER finishing**: when a file's work is done, close it immediately.
   Do NOT leave files open "just in case." Open them again when needed.
5. **Large files**: files >1200 lines are truncated in context. Use open_function(path, name)
   to extract specific classes/functions via AST instead of opening the whole file.

### Tool Reference

""" + _tool_ref('file') + """

### Workflow
1. Call list_open_files() to see what's in context
2. Use search_files() to locate code before opening
3. If open_file() fails with a git-tracking warning, call create_project('.') first
4. open_file() only files you will actively edit/read in the next few steps
5. For large Python files, prefer open_function() over open_file() with wide line ranges
6. As soon as you finish a task or switch goals, close_file() the now-irrelevant files

### Screen Broadcasts (Live File View)
Screens are browser windows (e.g., a workshop monitor or split-pane editor) that show a
live view of the file being edited. Changes appear in the browser within ~1 second of
each edit. Any number of screens can be open simultaneously, watching the same or different
files.

**One-time browser setup:**
1. Open a new browser tab (or a separate browser window/monitor)
2. Navigate to the `/module/file/screens` endpoint — the URL is in server config
   — A screen card appears showing its UID (e.g. `screen-abc123`) and status (⚪ idle)
3. Copy the UID from the browser — you'll pass it to screen_bind()
4. Call `screen_bind("path/to/file.py", "screen-abc123")` to bind it
5. The browser immediately shows the full file content; subsequent edits stream in live
6. After binding, {screens} in context shows which screens are active

**Screen lifecycle:**
- A screen stays bound to its file across edits until you call screen_release()
- To watch a different file on the same screen: bind it to the new path (binding transfers)
- Browser tab closed and reopened: binding auto-restores (the server remembers per screen)
- Call screen_list() anytime to see which screens are bound to which files

**When to use screens:**
- Useful when you want to verify edit results visually without re-reading file context
- For read-only verification, the file context (injected by file_context()) is usually enough
- Screens add value when editing large files or when visually confirming layout changes

**Drawing attention to code:**
After open_function(), consider calling screen_highlight(path, line_start, line_start)
to scroll the browser screen to that function and flash it gold — useful when asking
the user to look at a specific result. Check {screens} after binding to confirm
the screen is online and watching the right file."""


def _count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken if available, else rough estimate.
    
    Uses cl100k_base encoding (GPT-4/GPT-3.5-turbo) which is a good general-purpose
    tokenizer. Falls back to char/4 estimate if tiktoken not installed.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except (ImportError, Exception):
        # Rough fallback: ~4 chars per token for typical code/text
        return len(text) // 4


def _get_token_limit() -> int:
    """Get the file.token_limit config value, defaulting to 0 (disabled)."""
    try:
        from config import get
        limit = get('file.token_limit', 0)
        return int(limit) if limit else 0
    except Exception:
        return 0


def file_context() -> str:
    """Context function that injects open file information and contents.
    
    Reads the actual content of all open files from disk and formats them
    for injection into the system prompt.
    """
    import os
    
    session_id = get_session_id()
    query = build_search_query()
    memories = _search_memories(session_id, query, limit=100)
    
    if not memories:
        return "[File Context] No open files in context."
    
    # Show total count upfront so model knows how much context there is
    total_files = len(memories)
    lines: list[str] = [
        f"[File Context] {total_files} file(s) open in context:",
        "=" * 60,
        "",
    ]
    
    # Track total tokens across all open files
    total_tokens = 0
    file_contents: list[tuple[str, str, int]] = []  # (path, content, tokens)
    
    for i, mem in enumerate(memories, 1):
        props = mem.get("properties", {})
        path = props.get(PROP_PATH, "unknown")
        line_start = int(props.get(PROP_LINE_START, 0))
        line_end = props.get(PROP_LINE_END, None)
        
        # File header with full path and line range
        if line_end is None or line_end == "*" or line_end == "":
            range_label = f"lines {line_start}+ (to end)"
        else:
            line_end = int(line_end)
            range_label = f"lines {line_start}-{line_end}"
        
        lines.append(f"[File {i}/{total_files}] {path}")
        lines.append(f"  Range: {range_label}")
        lines.append("  " + "-" * 55)
        
        # Read the actual file content
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
            
            total_lines_in_file = len(all_lines)
            
            # Handle line range
            if line_end is None or line_end == "*" or line_end == "":
                file_content = ''.join(all_lines[line_start:])
            else:
                file_content = ''.join(all_lines[line_start:line_end])
            
            # Truncate very long content to avoid context overflow
            MAX_LINES = 1200
            content_lines = file_content.split('\n')
            num_lines_in_context = len(content_lines)
            
            if num_lines_in_context > MAX_LINES:
                file_content = '\n'.join(content_lines[:MAX_LINES])
                lines.append(f"  NOTE: Content truncated at {MAX_LINES} lines of {num_lines_in_context} total. Use open_function() to see specific functions.")
            else:
                lines.append(f"  Showing {num_lines_in_context} lines of {total_lines_in_file} total lines in file.")
            
            # Count tokens for this file's content
            file_tokens = _count_tokens(file_content)
            total_tokens += file_tokens
            
            lines.append(f"  Tokens: ~{file_tokens}")
            lines.append("")
            lines.append(file_content)
            
        except Exception as e:
            lines.append(f"  [ERROR reading file: {e}]")
        
        lines.append("")
        lines.append("=" * 60)
        lines.append("")
    
    # Check token limit and add warning if exceeded
    token_limit = _get_token_limit()
    if token_limit > 0 and total_tokens > token_limit:
        lines.insert(3, f"")
        lines.insert(4, f"[WARNING] Total tokens ({total_tokens}) exceeds file.token_limit ({token_limit}).")
        lines.insert(5, f"         Consider closing some files with close_file() to free up context.")
        lines.insert(6, f"")
    
    # Add total token count at the top
    lines.insert(3, f"[Token estimate] ~{total_tokens} tokens total (limit: {token_limit or 'disabled'})")
    
    return "\n".join(lines)


# =============================================================================
# Module Registration
# =============================================================================

def get_module() -> Module:
    """Get the file module with all registered functions."""
    return Module(
        name="file",
        called_fns=[
            CalledFn(
                name="open_file",
                description="Open a file and add it to the file context.\n\nRange validation:\n- Opening a range that is a subset of an already-open range is REJECTED (read from context).\n- Opening a range that supersets or overlaps an existing range EXPANDS the existing entry.\n\nArgs:\n- path: Path to the file to open\n- line_start: Start line for partial opening (0-indexed)\n- line_end: End line for partial opening (default: None = to end)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to open"},
                        "line_start": {"type": "integer", "description": "Start line for partial opening (0-indexed)"},
                        "line_end": {"type": "integer", "description": "End line for partial opening (default: None = to end)"},
                        "allow_untracked": {"type": "boolean", "description": "Override git-tracking gate (default: False). Rollback disabled if true."}
                    },
                    "required": ["path"]
                },
                fn=open_file,
            ),
            CalledFn(
                name="open_function",
                description="Open a specific class or function by name using AST parsing.\n\nArgs:\n- path: Path to the Python file\n- name: Name of the class or function (supports 'ClassName.method' for methods)\n- include_docstring: Whether to show docstring (default: True)\n- include_decorators: Whether to show decorators (default: True)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the Python file"},
                        "name": {"type": "string", "description": "Name of class or function"},
                        "include_docstring": {"type": "boolean", "description": "Show docstring (default: True)"},
                        "include_decorators": {"type": "boolean", "description": "Show decorators (default: True)"}
                    },
                    "required": ["path", "name"]
                },
                fn=open_function,
            ),
            CalledFn(
                name="restore_from_git",
                description="Restore a file to its last committed state in git.\\n\\nUse this to undo changes and roll back to the last committed version.\\n\\nArgs:\\n- path: Path to the file to restore",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to restore"}
                    },
                    "required": ["path"]
                },
                fn=restore_from_git,
            ),
            CalledFn(
                name="replace_text",
                description="Replace text in an open file using fuzzy matching. Auto-saves the file.\n\nArgs:\n- path: Path to the file\n- old: Text to find and replace\n- new: Replacement text\n- threshold: Minimum Jaro-Winkler similarity (default: 0.95)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "old": {"type": "string", "description": "Text to find and replace"},
                        "new": {"type": "string", "description": "Replacement text"},
                        "threshold": {"type": "number", "description": "Minimum similarity (0.0-1.0, default: 0.95)"}
                    },
                    "required": ["path", "old", "new"]
                },
                fn=replace_text,
            ),
            CalledFn(
                name="batch_edit",
                description="Apply multiple replacements in a single atomic operation.\n\nArgs:\n- path: Path to the file\n- replacements: List of {old, new} objects\n- threshold: Minimum Jaro-Winkler similarity (default: 0.95)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "replacements": {"type": "array", "description": "List of {old, new} objects"},
                        "threshold": {"type": "number", "description": "Minimum similarity (default: 0.95)"}
                    },
                    "required": ["path", "replacements"]
                },
                fn=batch_edit,
            ),
            CalledFn(
                name="delete_snippet",
                description="Remove a snippet from a file. Auto-saves.\n\nArgs:\n- path: Path to the file\n- snippet: Text to remove from file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "snippet": {"type": "string", "description": "Text to remove from file"}
                    },
                    "required": ["path", "snippet"]
                },
                fn=delete_snippet,
            ),
            CalledFn(
                name="write_text",
                description="Write content to a file, creating it if needed.\n\nArgs:\n- path: Path to the file\n- content: Content to write\n- create_parent_dirs: Create parent directories if needed (default: False)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "content": {"type": "string", "description": "Content to write"},
                        "create_parent_dirs": {"type": "boolean", "description": "Create parent dirs if needed"}
                    },
                    "required": ["path", "content"]
                },
                fn=write_text,
            ),
            CalledFn(
                name="delete_file",
                description="Delete a file.\n\nArgs:\n- path: Path to the file to delete",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to delete"}
                    },
                    "required": ["path"]
                },
                fn=delete_file,
            ),
            CalledFn(
                name="close_file",
                description="Close a file from the file context.\n\nArgs:\n- name: Filename to close\n- line_start: Specific line range start (optional)\n- line_end: Specific line range end (optional)",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Filename to close"},
                        "line_start": {"type": "integer", "description": "Line range start"},
                        "line_end": {"type": "integer", "description": "Line range end"}
                    },
                    "required": ["name"]
                },
                fn=close_file,
            ),
            CalledFn(
                name="close_all_files",
                description="Close all files from the file context.",
                parameters={"type": "object", "properties": {}},
                fn=close_all_files,
            ),
            CalledFn(
                name="preview_replace",
                description="Preview where a replacement would match without modifying.\n\nArgs:\n- path: Path to the file\n- old: Text to find\n- threshold: Minimum similarity (default: 0.95)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "old": {"type": "string", "description": "Text to find"},
                        "threshold": {"type": "number", "description": "Minimum similarity (default: 0.95)"}
                    },
                    "required": ["path", "old"]
                },
                fn=preview_replace,
            ),
            CalledFn(
                name="diff_text",
                description="Show diff of a proposed replacement without modifying.\n\nArgs:\n- path: Path to the file\n- old: Text to find\n- new: Proposed replacement\n- threshold: Minimum similarity (default: 0.95)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "old": {"type": "string", "description": "Text to find"},
                        "new": {"type": "string", "description": "Proposed replacement"},
                        "threshold": {"type": "number", "description": "Minimum similarity (default: 0.95)"}
                    },
                    "required": ["path", "old", "new"]
                },
                fn=diff_text,
            ),
            CalledFn(
                name="list_open_files",
                description="List all open files for the current session.",
                parameters={"type": "object", "properties": {}},
                fn=list_open_files,
            ),
            CalledFn(
                name="get_file_history",
                description="Get file change history for the current session.\n\nArgs:\n- path: Optional path to filter by",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Optional path to filter by"}
                    }
                },
                fn=get_file_history,
            ),
            CalledFn(
                name="search_files",
                description="Search for pattern in files.\n\nArgs:\n- pattern: Grep pattern to search for\n- path: Directory to search in (default: .)",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Grep pattern"},
                        "path": {"type": "string", "description": "Directory to search"}
                    },
                    "required": ["pattern"]
                },
                fn=search_files,
            ),
            CalledFn(
                name="list_dir",
                description="List directory contents.\n\nArgs:\n- path: Directory path (default: current directory)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"}
                    }
                },
                fn=list_dir,
            ),
            CalledFn(
                name="file_info",
                description="Get information about a file.\n\nArgs:\n- path: Path to the file",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"}
                    },
                    "required": ["path"]
                },
                fn=file_info,
            ),
            CalledFn(
                name="pwd",
                description="Get current working directory.",
                parameters={"type": "object", "properties": {}},
                fn=pwd,
            ),
            CalledFn(
                name="chdir",
                description="Change current working directory.\n\nArgs:\n- path: Directory path",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"}
                    },
                    "required": ["path"]
                },
                fn=chdir,
            ),
            CalledFn(
                name="screen_list",
                description="List all screens registered to this Riven session.\n\nShows screen UIDs, binding status, and online/offline state.\nUse screen_bind() to bind a screen to a file for live edit broadcasts.",
                parameters={"type": "object", "properties": {}},
                fn=screen_list,
            ),
            CalledFn(
                name="screen_bind",
                description="Bind a screen to a file for live edit broadcasts.\n\nOnce bound, the screen receives a full file snapshot, then incremental diffs\non every edit. The screen will remain bound until explicitly released.\n\nArgs:\n- path: Path to the file\n- screen_uid: UID of the screen to bind (from screen_list())\n- section: Optional line range (e.g., '0-30') for partial view",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "screen_uid": {"type": "string", "description": "Screen UID from screen_list()"},
                        "section": {"type": "string", "description": "Line range (e.g., '0-30') or None for full file"}
                    },
                    "required": ["path", "screen_uid"]
                },
                fn=screen_bind,
            ),
            CalledFn(
                name="screen_release",
                description="Release a screen from its current binding.\n\nArgs:\n- screen_uid: UID of the screen to release",
                parameters={
                    "type": "object",
                    "properties": {
                        "screen_uid": {"type": "string", "description": "Screen UID"}
                    },
                    "required": ["screen_uid"]
                },
                fn=screen_release,
            ),
            CalledFn(
                name="screen_status",
                description="Get detailed status for a specific screen.\n\nArgs:\n- screen_uid: UID of the screen to check",
                parameters={
                    "type": "object",
                    "properties": {
                        "screen_uid": {"type": "string", "description": "Screen UID"}
                    },
                    "required": ["screen_uid"]
                },
                fn=screen_status,
            ),
            CalledFn(
                name="screen_highlight",
                description="Highlight a line range on all screens showing a file.\n\nRiven uses this to draw the user's attention to a specific section.\nThe screen scrolls to the range, flashes the lines, and optionally shows\na toast with the label.\n\nArgs:\n- path: Path to the file to highlight in\n- start: First line to highlight (1-based, inclusive)\n- end: Last line to highlight (1-based, inclusive)\n- label: Optional toast message to show alongside the highlight\n- scroll: Whether to auto-scroll to the range (default True)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "start": {"type": "integer", "description": "First line to highlight (1-based, inclusive)"},
                        "end": {"type": "integer", "description": "Last line to highlight (1-based, inclusive)"},
                        "label": {"type": "string", "description": "Optional toast message to show"},
                        "scroll": {"type": "boolean", "description": "Whether to auto-scroll to the range"},
                    },
                    "required": ["path", "start", "end"],
                },
                fn=screen_highlight,
            ),
            # NOTE: read_file is intentionally not exposed as a tool.
            # Files should be opened via open_file() and their contents
            # will be automatically injected into the system prompt via file_context().
            # This ensures consistent file context management.
        ],
        context_fns=[
            ContextFn(
                tag="file_help",
                fn=_file_help,
                static=True,
            ),
            ContextFn(
                tag="file",
                fn=file_context,
            ),
            ContextFn(
                tag="screens",
                fn=screen_context,
            ),
        ],
    )


__all__ = [
    # Core classes
    "FileEditor",
    "EditResult",
    "Replacement",
    "CodeDefinition",
    "DefinitionExtractor",
    # File functions

    "open_file",
    "close_file",
    "close_all_files",
    "replace_text",
    "batch_edit",
    "delete_snippet",
    "write_text",
    "delete_file",
    "open_function",
    "restore_from_git",
    "preview_replace",
    "diff_text",
    "search_files",
    "list_dir",
    "file_info",
    "pwd",
    "chdir",
    "list_open_files",
    "get_file_history",
    "file_context",
    "get_module",
    "_file_editor",
    # Helpers
    "_atomic_write",
    "_atomic_write_sync",
    "_file_type",
    "_find_best_window",
    "_generate_diff",
    "_sanitize_content",
    "_validate_python",
    "_extract_code_definitions",
    "_find_definitions_by_name",
    "_extract_definition_source",
    "format_file_history",
    "get_file_history",
    "get_open_files",
    "hash_content",
    "track_file_change",
    # Git helpers
    "_run_git",
    "_is_git_repo",
    "_is_git_tracked",
    "_get_git_hash",
    "_git_status",
    "_git_warning",
    "_git_status_summary",
    # Screen broadcast functions
    "screen_list",
    "screen_bind",
    "screen_release",
    "screen_status",
    "screen_highlight",
    "broadcast_edit",
    "send_snapshot_to_uid",
    "_broadcast_after_edit",
]
