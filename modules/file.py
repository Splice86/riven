"""File module v2 for riven - simplified session-aware file management with memory DB."""

import os
import requests
from typing import Optional
from datetime import datetime

# For fuzzy matching
try:
    import jellyfish
    HAS_JELLYFISH = True
except ImportError:
    HAS_JELLYFISH = False

from modules import Module
from riven_secrets import get_memory_api, get_secret


# Memory API configuration
MEMORY_API_URL = os.environ.get("MEMORY_API_URL", get_memory_api())
DEFAULT_DB = os.environ.get("MEMORY_DB", get_secret('memory_api', 'db_name', default="default"))


def _count_tokens(text: str) -> int:
    """Rough token count - ~4 chars per token."""
    return len(text) // 4


def _find_best_window(
    haystack_lines: list[str],
    needle: str,
    threshold: float = 0.95
) -> tuple[tuple[int, int] | None, float]:
    """Find line window with best Jaro-Winkler similarity to needle."""
    if not HAS_JELLYFISH or not needle:
        return None, 0.0
    
    needle = needle.rstrip("\n")
    needle_lines = needle.splitlines()
    win_size = len(needle_lines)
    
    if win_size == 0:
        return None, 0.0
    
    best_score = 0.0
    best_span: tuple[int, int] | None = None
    
    for i in range(len(haystack_lines) - win_size + 1):
        window = "\n".join(haystack_lines[i:i + win_size])
        score = jellyfish.jaro_winkler_similarity(window, needle)
        if score > best_score:
            best_score = score
            best_span = (i, i + win_size)
    
    if best_score >= threshold:
        return best_span, best_score
    return None, best_score


def _search_memories(session_id: str, query: str, limit: int = 50) -> list[dict]:
    """Search memory DB and return results."""
    try:
        resp = requests.post(
            f"{MEMORY_API_URL}/memories/search",
            params={"db_name": DEFAULT_DB},
            json={"query": f"k:{session_id} AND k:file AND {query}", "limit": limit},
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json().get("memories", [])
    except Exception:
        pass
    return []


def _delete_memory(memory_id: str) -> None:
    """Delete a memory by ID."""
    try:
        requests.delete(
            f"{MEMORY_API_URL}/memories/{memory_id}",
            params={"db_name": DEFAULT_DB},
            timeout=5
        )
    except Exception:
        pass


def get_module(session_id: str = None):
    """Get the file module.
    
    Args:
        session_id: Optional session ID. Will be overwritten by registry.register().
    """
    
    # Create a container that will hold the session_id
    # Functions will reference this, and register() will update it
    class SessionContainer:
        _session_id = session_id or "default"
    
    _session = SessionContainer()
    
    # Helper to get session_id (prefers _session._session_id set by register())
    def _get_session_id():
        return _session._session_id
    
    # --- Tool Functions ---

    async def open_file(path: str, line_start: int = None, line_end: int = None) -> str:
        """Open a file and add it to the file context.
        
        Args:
            path: Path to the file to open.
            line_start: Start line for partial opening (0-indexed, None = from start)
            line_end: End line for partial opening (None = to end)
            
        Returns:
            Confirmation message
        """
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found"
        
        filename = os.path.basename(abs_path)
        line_start = line_start if line_start is not None else 0
        line_end = line_end if line_end is not None else "*"
        line_range = f"{line_start}-{line_end}"  # e.g., "0-50" or "100-*"
        
        # Save file record to memory DB with range-aware keywords
        try:
            requests.post(
                f"{MEMORY_API_URL}/memories",
                params={"db_name": DEFAULT_DB},
                json={
                    "content": f"open: {filename} [{line_range}]",
                    "keywords": [
                        _get_session_id(),
                        "file",
                        f"file:{filename}",               # For closing all ranges of this file
                        f"file:{filename}:{line_range}"    # For exact range match
                    ],
                    "properties": {
                        "path": abs_path,
                        "filename": filename,
                        "line_start": str(line_start),
                        "line_end": str(line_end)
                    }
                },
                timeout=5
            )
        except Exception as e:
            return f"Error saving to memory: {e}"
        
        # Get line count
        try:
            with open(abs_path, 'r') as f:
                total_lines = len(f.readlines())
        except:
            total_lines = "?"
        
        line_info = ""
        if line_start is not None or line_end is not None:
            line_info = f" (lines {line_start or 0}-{line_end or 'end'})"
        
        return f"Opened {filename} ({total_lines} lines){line_info}"

    async def replace_text(path: str, old_text: str, new_text: str, threshold: float = 0.95) -> str:
        """Replace text in a file using fuzzy matching (auto-saves).
        
        Args:
            path: Path to the file
            old_text: Text to find and replace
            new_text: Replacement text
            threshold: Fuzzy match threshold (0.0-1.0), default 0.95
            
        Returns:
            Confirmation message or error
        """
        abs_path = os.path.abspath(path)
        
        # Read file from disk
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            lines = content.splitlines(keepends=True)
        except Exception as e:
            return f"Error reading {abs_path}: {e}"
        
        # Use fuzzy matching across the document
        span, score = _find_best_window(lines, old_text, threshold)
        if span:
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
        else:
            actual_content = ''.join(lines[:20])
            return (
                f"Text not found. The text you're looking for is not in the file.\n"
                f"Expected (not in file):\n{repr(old_text[:200])}\n\n"
                f"Best fuzzy match: {score:.0%} (threshold was {threshold:.0%})\n"
                f"Actual file content (first 20 lines):\n{actual_content[:500]}\n\n"
                f"Tip: Lower threshold if needed."
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
        
        if line_start is not None or line_end is not None:
            # Exact range match - close specific range
            ls = line_start if line_start is not None else 0
            le = line_end if line_end is not None else "*"
            range_key = f"file:{name}:{ls}-{le}"
            memories = _search_memories(_get_session_id(), f"k:{range_key}", limit=10)
        else:
            # No range specified - close ALL ranges for this file
            memories = _search_memories(_get_session_id(), f"k:file:{name}", limit=10)
        
        if memories:
            count = 0
            for mem in memories:
                _delete_memory(mem['id'])
                count += 1
            range_desc = f" [{line_start or 0}-{line_end or '*'}]" if line_start is not None or line_end is not None else ""
            return f"Closed {name}{range_desc} ({count} range{'s' if count > 1 else ''})")
        
        return f"File {name} not open"

    async def close_all_files() -> str:
        """Close all open files for this session.
        
        Returns:
            Confirmation message with count
        """
        memories = _search_memories(_get_session_id(), "k:file", limit=100)
        
        count = 0
        for mem in memories:
            _delete_memory(mem['id'])
            count += 1
        
        return f"Closed {count} open files"

    async def file_info(path: str) -> dict:
        """Get file metadata without loading content.
        
        Args:
            path: Path to the file
            
        Returns:
            Dict with file metadata
        """
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return {"error": f"File {abs_path} not found"}
        
        stat = os.stat(abs_path)
        
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            line_count = len(content.splitlines())
            token_count = _count_tokens(content)
        except Exception:
            line_count = 0
            token_count = 0
        
        return {
            "path": abs_path,
            "filename": os.path.basename(abs_path),
            "line_count": line_count,
            "token_count": token_count,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }

    def get_context() -> str:
        """Return currently open files with their content.
        
        Queries memory DB for file records with session_id, then loads
        the actual file content from disk.
        """
        # Instructions for the AI
        instructions = f"""## File Tools

### Workflow
1. **open_file(path)** - Open a file into context
2. **open_file(path, line_start, line_end)** - Open specific line range
3. **replace_text(path, old_text, new_text)** - Replace text (auto-saves)
4. **close_file(filename)** - Close a file
5. **close_all_files()** - Close all open files
6. **file_info(path)** - Get file metadata

### Important
- Open files are automatically included in your context below
- Use replace_text() for edits - it saves automatically
- Close files when done to keep context clean
- Files not in context must be re-opened
"""
        
        # Search memory DB for open files
        memories = _search_memories(_get_session_id(), "k:file", limit=50)
        
        if not memories:
            return instructions + "\n\nNo files currently open"
        
        # Build context from disk
        lines = [instructions, "", "=== Open Files ==="]
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
                line_end = props.get("line_end", "*")  # Default to "*" means no end
                
                start = int(line_start) if line_start != "0" else 0
                if line_end and line_end != "*":
                    end = int(line_end)
                    content_lines = content.splitlines(keepends=True)
                    content = ''.join(content_lines[start:end])
                
                filename = os.path.basename(path)
                end_display = line_end if line_end != "*" else "end"
                lines.append(f"\n=== {filename} [lines {line_start}-{end_display}] ===")
                lines.append(content)
                total_tokens += _count_tokens(content)
                
            except Exception:
                continue
        
        # Token count
        lines.append(f"\n\n--- File Context Stats ---")
        lines.append(f"Total open file tokens: {total_tokens:,}")
        
        return "\n".join(lines)

    # Create module with all fields at once (avoids __post_init__ validation issues)
    module = Module(
        name="file",
        enrollment=lambda: None,
        functions={
            "open_file": open_file,
            "replace_text": replace_text,
            "close_file": close_file,
            "close_all_files": close_all_files,
            "file_info": file_info,
        },
        get_context=get_context,
        tag="file"
    )
    
    # Store session container for later update by register()
    module._session_container = _session
    
    return module