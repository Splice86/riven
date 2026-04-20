"""File module with fuzzy matching for temp_riven.

Provides file editing capabilities with:
- open_file: Add file to context (stored in memory DB)
- replace_text: Fuzzy-match replacement with auto-save
- preview_replace: Show matched text without modifying
- diff_text: Show before/after of a replacement
- close_file: Remove from context
- close_all_files: Clear all open files
- file_info: Get file metadata
- search_files: Grep pattern across files
- list_dir: List directory contents
- get_context: Context function that injects open file content

Session ID is automatically available via get_session_id().
"""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import requests
import jellyfish

from modules import CalledFn, ContextFn, Module, get_session_id
from modules.memory_utils import _search_memories, _delete_memory, _get_memory_url


def _count_tokens(text: str) -> int:
    """Rough token count - ~4 chars per token."""
    return len(text) // 4


def _find_best_window(
    haystack_lines: list[str],
    needle: str,
    threshold: float = 0.95
) -> tuple[tuple[int, int] | None, float]:
    """Find line window with best Jaro-Winkler similarity to needle.
    
    Args:
        haystack_lines: The file content split into lines
        needle: The text to search for
        threshold: Minimum similarity score (0.0-1.0)
        
    Returns:
        ((start_line, end_line), score) or (None, best_score) if not found
    """
    needle = needle.rstrip("\n")
    needle_lines = needle.splitlines()
    win_size = len(needle_lines)
    
    if win_size == 0:
        return None, 0.0
    
    best_score = 0.0
    best_span: tuple[int, int] | None = None
    
    for i in range(len(haystack_lines) - win_size + 1):
        window = "\n".join(haystack_lines[i:i + win_size])
        window_clean = window.rstrip('\n')
        score = jellyfish.jaro_winkler_similarity(window_clean, needle)
        if score > best_score:
            best_score = score
            best_span = (i, i + win_size)
    
    if best_score >= threshold:
        return best_span, best_score
    return None, best_score


def _file_type(path: str) -> str:
    """Return a short file type description based on extension."""
    ext = Path(path).suffix.lower()
    type_map = {
        '.py': 'python',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.json': 'json',
        '.md': 'markdown',
        '.txt': 'text',
        '.sh': 'shell',
        '.bash': 'shell',
        '.zsh': 'shell',
        '.c': 'c',
        '.h': 'c',
        '.cpp': 'cpp',
        '.rs': 'rust',
        '.go': 'go',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.html': 'html',
        '.css': 'css',
        '.sql': 'sql',
        '.toml': 'toml',
        '.ini': 'ini',
        '.cfg': 'cfg',
        '.conf': 'conf',
        '.env': 'env',
        '.gitignore': 'gitignore',
        '.dockerfile': 'dockerfile',
    }
    return type_map.get(ext, ext.lstrip('.') or 'file')


def _file_help() -> str:
    """Static tool documentation - does not change between calls."""
    return """## File Tools (Help)

### Workflow
1. **open_file(path, line_start?, line_end?)** - Open a file into context
2. **replace_text(path, old_text, new_text, threshold?)** - Fuzzy-match replacement (auto-saves)
3. **preview_replace(path, old_text, threshold?)** - Show matched text without modifying
4. **diff_text(path, old_text, new_text, threshold?)** - Show before/after of proposed change
5. **close_file(filename, line_start?, line_end?)** - Close file/range
6. **close_all_files()** - Close all open files
7. **file_info(path)** - Get file metadata
8. **search_files(pattern, path?)** - Grep pattern across files
9. **list_dir(path?)** - List directory contents

### Guidelines
- Prefer opening whole files (no line_start/line_end) - small files are fine to read entirely
- Avoid opening the same file multiple times in different ranges - open once with a wider range or not at all
- Use search_files() to find patterns before opening files
- Use preview_replace() to verify a match before committing to replace_text()
- Use diff_text() to preview a full change before applying it
- Close files when done to keep context clean
- Use file_info() for metadata without loading content
- Be sensitive to context growth - open only what you need"""


def _file_context() -> str:
    """Dynamic context - currently open files. Changes when files are opened/closed."""
    session_id = get_session_id()
    query = "k:file"
    memories = _search_memories(session_id, query, limit=50)
    
    if not memories:
        return "No files currently open"
    
    lines = ["=== Open Files ==="]
    total_tokens = 0
    
    for mem in memories:
        props = mem.get("properties", {})
        path = props.get("path")
        
        if not path or not os.path.exists(path):
            continue
        
        try:
            with open(path, 'r') as f:
                content = f.read()
            
            line_start = props.get("line_start", "0")
            line_end = props.get("line_end", "*")
            
            start = int(line_start) if line_start != "0" else 0
            if line_end and line_end != "*":
                content_lines = content.splitlines(keepends=True)
                content = ''.join(content_lines[start:int(line_end)])
            
            filename = os.path.basename(path)
            end_display = line_end if line_end != "*" else "end"
            lines.append(f"\n=== {filename} [lines {line_start}-{end_display}] ===")
            lines.append(content)
            total_tokens += _count_tokens(content)
        except Exception:
            continue
    
    lines.append(f"\n\n--- File Context Stats ---")
    lines.append(f"Total open file tokens: {total_tokens:,}")
    
    return "\n".join(lines)


# --- Called Functions ---

async def open_file(path: str, line_start: int = None, line_end: int = None) -> str:
    """Open a file and add it to the file context.
    
    Args:
        path: Path to the file to open.
        line_start: Start line for partial opening (0-indexed, None = from start)
        line_end: End line for partial opening (None = to end)
        
    Returns:
        Confirmation message with file metadata
    """
    path = os.path.expanduser(path)
    abs_path = os.path.abspath(path)
    
    if not os.path.exists(abs_path):
        return f"Error: File {abs_path} not found"
    
    filename = os.path.basename(abs_path)
    session_id = get_session_id()
    
    line_start = line_start if line_start is not None else 0
    line_end_str = line_end if line_end is not None else "*"
    line_range = f"{line_start}-{line_end_str}"
    
    keywords = [
        session_id,
        "file",
        f"file:{filename}",
        f"file:{filename}:{line_range}"
    ]
    payload = {
        "content": f"open: {filename} [{line_range}]",
        "keywords": keywords,
        "properties": {
            "path": abs_path,
            "filename": filename,
            "line_start": str(line_start),
            "line_end": str(line_end) if line_end is not None else "*"
        }
    }
    
    try:
        url = f"{_get_memory_url()}/memories"
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code != 200:
            return f"Error saving to memory: {resp.text[:200]}"
    except Exception as e:
        return f"Error saving to memory: {e}"
    
    try:
        with open(abs_path, 'r') as f:
            content = f.read()
        total_lines = len(content.splitlines())
    except Exception:
        total_lines = "?"
    
    file_type_str = _file_type(abs_path)
    line_info = ""
    if line_start > 0 or line_end is not None:
        line_info = f" (lines {line_start}-{line_end or 'end'})"
    
    large_warning = ""
    if total_lines != "?" and total_lines > 1000:
        large_warning = " [!LARGE FILE - consider using line_start/line_end to limit scope]"
    
    return f"Opened {filename} ({file_type_str}, {total_lines} lines){line_info}{large_warning}"


async def replace_text(
    path: str,
    old_text: str,
    new_text: str,
    threshold: float = 0.95
) -> str:
    """Replace text in a file using fuzzy matching (auto-saves).
    
    Args:
        path: Path to the file
        old_text: Text to find and replace
        new_text: Replacement text
        threshold: Minimum Jaro-Winkler similarity (0.0-1.0, default 0.95)
        
    Returns:
        Confirmation message or error with best match info
    """
    path = os.path.expanduser(path)
    abs_path = os.path.abspath(path)
    
    try:
        with open(abs_path, 'r') as f:
            content = f.read()
        lines = content.splitlines(keepends=True)
    except Exception as e:
        return f"Error reading {abs_path}: {e}"
    
    span, score = _find_best_window(lines, old_text, threshold=threshold)
    
    if not span:
        # Find best match even below threshold so we can show it
        best_span, best_score = _find_best_window(lines, old_text, threshold=0.0)
        if best_span:
            start, end = best_span
            matched_lines = lines[start:end]
            matched_text = ''.join(matched_lines).strip()
            return (
                f"Text not found (best match was {best_score:.0%} — below {threshold:.0%} threshold).\n\n"
                f"Best match found:\n{matched_text[:300]}\n\n"
                f"Tips:\n"
                f"- Try lowering threshold (e.g., threshold=0.75) if whitespace differs\n"
                f"- Make sure indentation and newlines match the file format\n"
                f"- The more text you provide, the better the fuzzy match"
            )
        return (
            f"Text not found.\n\n"
            f"Tips:\n"
            f"- Check for whitespace differences (spaces/tabs)\n"
            f"- Make sure newlines match the file format\n"
            f"- The more text you provide, the better the fuzzy match"
        )
    
    start, end = span
    
    new_lines = new_text.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'
    lines[start:end] = new_lines
    new_content = ''.join(lines)
    
    try:
        with open(abs_path, 'w') as f:
            f.write(new_content)
    except Exception as e:
        return f"Error saving {abs_path}: {e}"
    
    return f"Replaced lines {start+1}-{end} (fuzzy match {score:.0%})"


async def preview_replace(path: str, old_text: str, threshold: float = 0.95) -> str:
    """Show the matched text window without modifying the file.
    
    Args:
        path: Path to the file
        old_text: Text to search for
        threshold: Minimum Jaro-Winkler similarity (0.0-1.0, default 0.95)
        
    Returns:
        Matched text window or not-found message
    """
    path = os.path.expanduser(path)
    abs_path = os.path.abspath(path)
    
    try:
        with open(abs_path, 'r') as f:
            content = f.read()
        lines = content.splitlines(keepends=True)
    except Exception as e:
        return f"Error reading {abs_path}: {e}"
    
    span, score = _find_best_window(lines, old_text, threshold=threshold)
    
    if not span:
        best_span, best_score = _find_best_window(lines, old_text, threshold=0.0)
        if best_span:
            start, end = best_span
            matched_text = ''.join(lines[start:end]).strip()
            return (
                f"No match above {threshold:.0%} threshold. "
                f"Best match ({best_score:.0%}) at lines {start+1}-{end}:\n"
                f"{matched_text[:300]}"
            )
        return f"Text not found in {os.path.basename(abs_path)}."
    
    start, end = span
    matched_text = ''.join(lines[start:end]).strip()
    return f"Match at lines {start+1}-{end} (similarity {score:.0%}):\n{matched_text}"


async def diff_text(
    path: str,
    old_text: str,
    new_text: str,
    threshold: float = 0.95
) -> str:
    """Show the before/after of a proposed replacement without modifying.
    
    Args:
        path: Path to the file
        old_text: Text to find
        new_text: Replacement text
        threshold: Minimum Jaro-Winkler similarity (0.0-1.0, default 0.95)
        
    Returns:
        Formatted before/after diff
    """
    path = os.path.expanduser(path)
    abs_path = os.path.abspath(path)
    
    try:
        with open(abs_path, 'r') as f:
            content = f.read()
        lines = content.splitlines(keepends=True)
    except Exception as e:
        return f"Error reading {abs_path}: {e}"
    
    span, score = _find_best_window(lines, old_text, threshold=threshold)
    
    if not span:
        best_span, best_score = _find_best_window(lines, old_text, threshold=0.0)
        if best_span:
            start, end = best_span
            matched_text = ''.join(lines[start:end]).rstrip()
            return (
                f"Cannot diff — best match ({best_score:.0%}) is below {threshold:.0%} threshold.\n\n"
                f"Best match at lines {start+1}-{end}:\n{matched_text[:300]}\n\n"
                f"Try lowering threshold for this replacement."
            )
        return f"Cannot diff — text not found in {os.path.basename(abs_path)}."
    
    start, end = span
    before = ''.join(lines[start:end]).rstrip()
    
    new_lines = new_text.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'
    after = ''.join(new_lines).rstrip()
    
    filename = os.path.basename(abs_path)
    return (
        f"=== diff: {filename} lines {start+1}-{end} (match {score:.0%}) ===\n"
        f"\n--- BEFORE ---:\n{before}\n\n--- AFTER ---:\n{after}"
    )


async def close_file(filename: str, line_start: int = None, line_end: int = None) -> str:
    """Close a file by removing its record from memory DB.
    
    Args:
        filename: Filename to close (can be full path or just name)
        line_start: Optional. Close only this specific range.
        line_end: Optional. Close only this specific range.
        
    Returns:
        Confirmation message
    """
    name = os.path.basename(filename)
    session_id = get_session_id()
    
    if line_start is not None or line_end is not None:
        ls = line_start if line_start is not None else 0
        le = line_end if line_end is not None else "*"
        range_key = f"file:{name}:{ls}-{le}"
        query = f"k:{range_key}"
        memories = _search_memories(session_id, query, limit=10)
    else:
        query = f"k:file:{name}"
        memories = _search_memories(session_id, query, limit=10)
    
    if memories:
        count = 0
        for mem in memories:
            _delete_memory(mem['id'])
            count += 1
        range_desc = f" [{line_start or 0}-{line_end or '*'}]" if line_start is not None or line_end is not None else ""
        return f"Closed {name}{range_desc} ({count} range{'s' if count > 1 else ''})"
    
    return f"File {name} not open"


async def close_all_files() -> str:
    """Close all open files for this session.
    
    Returns:
        Confirmation message with count
    """
    session_id = get_session_id()
    memories = _search_memories(session_id, "k:file", limit=100)
    
    count = 0
    for mem in memories:
        _delete_memory(mem['id'])
        count += 1
    
    return f"Closed {count} open files"


async def file_info(path: str) -> str:
    """Get file metadata without loading content.
    
    Args:
        path: Path to the file
        
    Returns:
        Formatted file metadata
    """
    path = os.path.expanduser(path)
    abs_path = os.path.abspath(path)
    
    if not os.path.exists(abs_path):
        return f"Error: File {abs_path} not found"
    
    stat = os.stat(abs_path)
    
    try:
        with open(abs_path, 'r') as f:
            content = f.read()
        line_count = len(content.splitlines())
        token_count = _count_tokens(content)
    except Exception:
        line_count = 0
        token_count = 0
    
    file_type_str = _file_type(abs_path)
    
    return (
        f"File: {os.path.basename(abs_path)}\n"
        f"Type: {file_type_str}\n"
        f"Lines: {line_count}\n"
        f"Tokens: ~{token_count:,}\n"
        f"Size: {stat.st_size:,} bytes\n"
        f"Modified: {datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}"
    )


async def search_files(pattern: str, path: str = None) -> str:
    """Grep pattern across files under a directory.
    
    Args:
        pattern: Regex pattern to search for
        path: Directory to search under (default: cwd)
        
    Returns:
        Formatted list of matches (file:line:content)
    """
    search_path = os.path.expanduser(path) if path else os.getcwd()
    
    if not os.path.exists(search_path):
        return f"Path not found: {search_path}"
    
    try:
        result = subprocess.run(
            ['rg', '--line-number', '--color=never', pattern, search_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        output = result.stdout.strip()
    except FileNotFoundError:
        return "[ERROR] ripgrep (rg) not installed. Install ripgrep to use search_files."
    except subprocess.TimeoutExpired:
        return "[ERROR] Search timed out after 10 seconds."
    except Exception as e:
        return f"[ERROR] Search failed: {e}"
    
    if not output:
        return f"No matches for '{pattern}' under {search_path}"
    
    lines = output.splitlines()
    # ripgrep outputs: file:line:content — format nicely
    formatted = [f"=== Search: '{pattern}' ==="]
    for line in lines[:50]:  # cap at 50 matches
        formatted.append(line)
    
    if len(lines) > 50:
        formatted.append(f"... and {len(lines) - 50} more matches")
    
    return "\n".join(formatted)


async def list_dir(path: str = None) -> str:
    """List directory contents (files and subdirectories).
    
    Args:
        path: Directory to list (default: cwd)
        
    Returns:
        Formatted directory listing
    """
    dir_path = os.path.expanduser(path) if path else os.getcwd()
    
    if not os.path.exists(dir_path):
        return f"Directory not found: {dir_path}"
    
    if not os.path.isdir(dir_path):
        return f"Not a directory: {dir_path}"
    
    try:
        entries = os.listdir(dir_path)
    except PermissionError:
        return f"Permission denied: {dir_path}"
    
    dirs = []
    files = []
    for entry in entries:
        full_path = os.path.join(dir_path, entry)
        if os.path.isdir(full_path):
            dirs.append(entry + '/')
        else:
            files.append(entry)
    
    dirs.sort()
    files.sort()
    
    lines = [f"=== {dir_path} ==="]
    if dirs:
        lines.append("dirs:")
        lines.extend(f"  {d}" for d in dirs)
    if files:
        lines.append("files:")
        lines.extend(f"  {f}" for f in files)
    
    if not dirs and not files:
        lines.append("  (empty)")
    
    return "\n".join(lines)


def get_module():
    """Get the file module."""
    return Module(
        name="file",
        called_fns=[
            CalledFn(
                name="open_file",
                description="Open a file and add it to the file context. Returns file type and line count. Large files (>1000 lines) include a warning.\n\nArgs:\n- path: Path to the file to open\n- line_start: Start line for partial opening (0-indexed)\n- line_end: End line for partial opening",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file to open"
                        },
                        "line_start": {
                            "type": "integer",
                            "description": "Start line for partial opening (0-indexed, default: 0)"
                        },
                        "line_end": {
                            "type": "integer",
                            "description": "End line for partial opening (default: None = to end)"
                        }
                    },
                    "required": ["path"]
                },
                fn=open_file,
            ),
            CalledFn(
                name="replace_text",
                description="Replace text in an open file using fuzzy matching. Auto-saves the file.\n\nArgs:\n- path: Path to the file\n- old_text: Text to find and replace (fuzzy matched)\n- new_text: Replacement text\n- threshold: Minimum Jaro-Winkler similarity (0.0-1.0, default: 0.95). Lower values allow sloppier matches.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file"
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Text to find and replace (fuzzy matched)"
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text"
                        },
                        "threshold": {
                            "type": "number",
                            "description": "Minimum Jaro-Winkler similarity (0.0-1.0, default: 0.95). Lower to allow matches with whitespace differences."
                        }
                    },
                    "required": ["path", "old_text", "new_text"]
                },
                fn=replace_text,
            ),
            CalledFn(
                name="preview_replace",
                description="Show the matched text window without modifying the file. Use to verify the right location before committing to replace_text.\n\nArgs:\n- path: Path to the file\n- old_text: Text to search for\n- threshold: Minimum Jaro-Winkler similarity (0.0-1.0, default: 0.95)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file"
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Text to search for"
                        },
                        "threshold": {
                            "type": "number",
                            "description": "Minimum Jaro-Winkler similarity (0.0-1.0, default: 0.95)"
                        }
                    },
                    "required": ["path", "old_text"]
                },
                fn=preview_replace,
            ),
            CalledFn(
                name="diff_text",
                description="Show the before/after of a proposed replacement without modifying the file. Use to preview a full change before applying it.\n\nArgs:\n- path: Path to the file\n- old_text: Text to find\n- new_text: Replacement text\n- threshold: Minimum Jaro-Winkler similarity (0.0-1.0, default: 0.95)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file"
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Text to find"
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text"
                        },
                        "threshold": {
                            "type": "number",
                            "description": "Minimum Jaro-Winkler similarity (0.0-1.0, default: 0.95)"
                        }
                    },
                    "required": ["path", "old_text", "new_text"]
                },
                fn=diff_text,
            ),
            CalledFn(
                name="close_file",
                description="Close a file by removing it from the file context.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Filename to close (can be full path or just name)"
                        },
                        "line_start": {
                            "type": "integer",
                            "description": "Optional. Close only this specific range."
                        },
                        "line_end": {
                            "type": "integer",
                            "description": "Optional. Close only this specific range."
                        }
                    },
                    "required": ["filename"]
                },
                fn=close_file,
            ),
            CalledFn(
                name="close_all_files",
                description="Close all open files for this session. Use to clean up context.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                fn=close_all_files,
            ),
            CalledFn(
                name="file_info",
                description="Get file metadata (type, line count, size, modified date) without loading content.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file"
                        }
                    },
                    "required": ["path"]
                },
                fn=file_info,
            ),
            CalledFn(
                name="search_files",
                description="Grep pattern across files under a directory using ripgrep (rg). Returns file:line:content for each match, capped at 50 results.\n\nArgs:\n- pattern: Regex pattern to search for\n- path: Directory to search under (default: cwd)",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Regex pattern to search for"
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory to search under (default: cwd)"
                        }
                    },
                    "required": ["pattern"]
                },
                fn=search_files,
            ),
            CalledFn(
                name="list_dir",
                description="List directory contents (files and subdirectories).\n\nArgs:\n- path: Directory to list (default: cwd)",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory to list (default: cwd)"
                        }
                    },
                    "required": []
                },
                fn=list_dir,
            ),
        ],
        context_fns=[
            ContextFn(tag="file_help", fn=_file_help, static=True),
            ContextFn(tag="file", fn=_file_context),
        ],
    )
