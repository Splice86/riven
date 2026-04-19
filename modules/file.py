"""File module with fuzzy matching for temp_riven.

Provides file editing capabilities with:
- open_file: Add file to context (stored in memory DB)
- replace_text: Fuzzy-match replacement with auto-save
- close_file: Remove from context
- close_all_files: Clear all open files
- file_info: Get file metadata
- get_context: Context function that injects open file content

Session ID is automatically available via get_session_id().
"""

import os
import requests
import jellyfish
from datetime import datetime

from modules import CalledFn, ContextFn, Module, get_session_id
from config import get


MEMORY_API_URL = get('memory_api.url', 'http://127.0.0.1:8030')


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
        # Strip trailing newline to match needle (which is rstrip'd)
        window_clean = window.rstrip('\n')
        score = jellyfish.jaro_winkler_similarity(window_clean, needle)
        if score > best_score:
            best_score = score
            best_span = (i, i + win_size)
    
    if best_score >= threshold:
        return best_span, best_score
    return None, best_score


def _search_memories(session_id: str, query: str, limit: int = 50) -> list[dict]:
    """Search memory DB and return results."""
    search_query = f"k:{session_id} AND {query}"
    
    try:
        url = f"{MEMORY_API_URL}/memories/search"
        resp = requests.post(
            url,
            json={"query": search_query, "limit": limit},
            timeout=5
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get("memories", [])
    except Exception:
        pass
    return []


def _delete_memory(memory_id: str) -> None:
    """Delete a memory by ID."""
    try:
        requests.delete(
            f"{MEMORY_API_URL}/memories/{memory_id}",
            timeout=5
        )
    except Exception:
        pass


def _file_help() -> str:
    """Static tool documentation - does not change between calls."""
    return """## File Tools (Help)

### Workflow
1. **open_file(path, line_start?, line_end?)** - Open a file into context
2. **replace_text(path, old_text, new_text)** - Fuzzy-match replacement (auto-saves)
3. **close_file(filename, line_start?, line_end?)** - Close file/range
4. **close_all_files()** - Close all open files
5. **file_info(path)** - Get file metadata

### Notes
- Open files are automatically included in your context below
- Use replace_text() for edits - it saves automatically
- Close files when done to keep context clean"""
    
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
            
            # Apply line range if specified
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
        Confirmation message
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
    
    # Save file record to memory DB with range-aware keywords
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
        url = f"{MEMORY_API_URL}/memories"
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code != 200:
            return f"Error saving to memory: {resp.text[:200]}"
    except Exception as e:
        return f"Error saving to memory: {e}"
    
    # Get line count
    try:
        with open(abs_path, 'r') as f:
            total_lines = len(f.readlines())
    except:
        total_lines = "?"
    
    line_info = ""
    if line_start > 0 or line_end is not None:
        line_info = f" (lines {line_start}-{line_end or 'end'})"
    
    return f"Opened {filename} ({total_lines} lines){line_info}"


async def replace_text(path: str, old_text: str, new_text: str) -> str:
    """Replace text in a file using fuzzy matching (auto-saves).
    
    Args:
        path: Path to the file
        old_text: Text to find and replace
        new_text: Replacement text
        
    Returns:
        Confirmation message or error
    """
    path = os.path.expanduser(path)
    abs_path = os.path.abspath(path)
    
    # Read file from disk
    try:
        with open(abs_path, 'r') as f:
            content = f.read()
        lines = content.splitlines(keepends=True)
    except Exception as e:
        return f"Error reading {abs_path}: {e}"
    
    # Fuzzy matching across the document
    span, score = _find_best_window(lines, old_text, threshold=0.95)
    
    if not span:
        # Provide helpful error message
        actual_content = ''.join(lines[:20])
        return (
            f"Text not found - fuzzy match failed.\n\n"
            f"Expected (not in file):\n{repr(old_text[:200])}\n\n"
            f"Actual file content (first 20 lines):\n{actual_content[:500]}\n\n"
            f"Tips:\n"
            f"- Check for whitespace differences (spaces/tabs)\n"
            f"- Make sure newlines match the file format\n"
            f"- The more text you provide, the better the fuzzy match"
        )
    
    start, end = span
    
    # Replace the matched span with new_text
    new_lines = new_text.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'
    lines[start:end] = new_lines
    new_content = ''.join(lines)
    
    # Save to disk
    try:
        with open(abs_path, 'w') as f:
            f.write(new_content)
    except Exception as e:
        return f"Error saving {abs_path}: {e}"
    
    return f"Replaced lines {start+1}-{end} (fuzzy match {score:.0%})"


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
        # Exact range match - close specific range
        ls = line_start if line_start is not None else 0
        le = line_end if line_end is not None else "*"
        range_key = f"file:{name}:{ls}-{le}"
        query = f"k:{range_key}"
        memories = _search_memories(session_id, query, limit=10)
    else:
        # No range specified - close ALL ranges for this file
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
    
    return (
        f"File: {os.path.basename(abs_path)}\n"
        f"Path: {abs_path}\n"
        f"Lines: {line_count}\n"
        f"Tokens: ~{token_count:,}\n"
        f"Size: {stat.st_size:,} bytes\n"
        f"Modified: {datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}"
    )


def get_module():
    """Get the file module."""
    return Module(
        name="file",
        called_fns=[
            CalledFn(
                name="open_file",
                description="Open a file and add it to the file context. Use this before reading or editing a file.",
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
                description="Replace text in an open file using fuzzy matching. Auto-saves the file.",
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
                        }
                    },
                    "required": ["path", "old_text", "new_text"]
                },
                fn=replace_text,
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
                description="Get file metadata (line count, size, modified date) without loading content.",
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
        ],
        context_fns=[
            ContextFn(tag="file_help", fn=_file_help),
            ContextFn(tag="file", fn=_file_context),
        ],
    )
