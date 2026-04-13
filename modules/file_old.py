"""File module for riven - session-aware file management with memory DB integration."""

import os
import io
import requests
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

# For fuzzy matching
try:
    import jellyfish
    HAS_JELLYFISH = True
except ImportError:
    HAS_JELLYFISH = False

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
try:
    import yaml
    with open(CONFIG_PATH) as f:
        CONFIG = yaml.safe_load(f)
except Exception:
    CONFIG = {}

from modules import Module
from riven_secrets import get_memory_api, get_secret


# Memory API configuration
MEMORY_API_URL = os.environ.get("MEMORY_API_URL", get_memory_api())
DEFAULT_DB = os.environ.get("MEMORY_DB", get_secret('memory_api', 'db_name', default="default"))


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


def _count_tokens(text: str) -> int:
    """Rough token count - ~4 chars per token."""
    return len(text) // 4


class DocumentManager:
    """Manages open documents with line-aware operations.
    
    session_id_getter: callable that returns the current session_id from the Module.
    """
    
    def __init__(self, session_id_getter: callable = None):
        self._session_id_getter = session_id_getter
    
    def _get_session_id(self) -> str:
        """Get session_id from the Module."""
        if self._session_id_getter:
            return self._session_id_getter()
        raise ValueError("No session_id_getter set on DocumentManager")
    
    def _get_memory_db(self) -> str:
        """Get the memory DB name."""
        return DEFAULT_DB
    
    def _save_to_memory(self, path: str, line_start: int = 0, line_end: Optional[int] = None) -> None:
        """Save file record to memory DB."""
        session_id = self._get_session_id()
        
        abs_path = os.path.abspath(path)
        filename = os.path.basename(abs_path)
        line_end_str = str(line_end) if line_end else ""
        
        # Content: filename,line_start,line_end
        content = f"{filename},{line_start},{line_end_str}"
        
        try:
            requests.post(
                f"{MEMORY_API_URL}/memories",
                params={"db_name": self._get_memory_db()},
                json={
                    "content": content,
                    "keywords": [session_id, "file_record"],
                    "properties": {"path": abs_path, "session": session_id}
                },
                timeout=5
            )
        except Exception:
            pass  # Non-critical if memory save fails
    
    def _delete_from_memory(self, path: str) -> None:
        """Delete file record from memory DB."""
        session_id = self._get_session_id()
        
        abs_path = os.path.abspath(path)
        
        try:
            # Search for this file record and delete it
            resp = requests.post(
                f"{MEMORY_API_URL}/memories/search",
                params={"db_name": self._get_memory_db()},
                json={
                    "query": f"k:{self._get_session_id()} AND k:file_record AND path:{abs_path}",
                    "limit": 10
                },
                timeout=5
            )
            if resp.status_code == 200:
                results = resp.json().get("memories", [])
                for mem in results:
                    requests.delete(
                        f"{MEMORY_API_URL}/memories/{mem['id']}",
                        params={"db_name": self._get_memory_db()},
                        timeout=5
                    )
        except Exception:
            pass  # Non-critical
    
    def _load_from_memory(self) -> list[tuple[str, int, Optional[int]]]:
        """Load open files from memory DB. Returns list of (path, line_start, line_end)."""
        session_id = self._get_session_id()

        try:
            resp = requests.post(
                f"{MEMORY_API_URL}/memories/search",
                params={"db_name": self._get_memory_db()},
                json={
                    "query": f"p:session={session_id} AND k:file_record",
                    "limit": 50
                },
                timeout=5
            )
            if resp.status_code != 200:
                return []
            
            results = resp.json().get("memories", [])
            files = []
            for mem in results:
                props = mem.get("properties", {})
                path = props.get("path")
                if not path:
                    continue
                
                # Parse content: filename,line_start,line_end
                content = mem.get("content", "")
                parts = content.split(",")
                try:
                    line_start = int(parts[1]) if len(parts) > 1 else 0
                    line_end = int(parts[2]) if len(parts) > 2 and parts[2] else None
                except (ValueError, IndexError):
                    line_start, line_end = 0, None
                
                files.append((path, line_start, line_end))
            return files
        except Exception:
            return []
    
    def open(self, path: str, line_start: int = None, line_end: int = None) -> str:
        """Open a file and add record to memory DB.
        
        Args:
            path: Path to the file
            line_start: Start line for partial opening (0-indexed, None = from start)
            line_end: End line for partial opening (None = to end)
            
        Returns:
            Confirmation message
        """
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found"
        
        session_id = self._get_session_id()
        
        filename = os.path.basename(abs_path)
        line_start_str = str(line_start) if line_start is not None else "0"
        line_end_str = str(line_end) if line_end is not None else ""
        
        try:
            requests.post(
                f"{MEMORY_API_URL}/memories",
                params={"db_name": self._get_memory_db()},
                json={
                    "content": f"open: {filename}",
                    "keywords": ["file_record"],
                    "properties": {
                        "session": session_id,
                        "path": abs_path,
                        "filename": filename,
                        "line_start": line_start_str,
                        "line_end": line_end_str
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
    
    def replace_text(
        self,
        path: str,
        old_text: str,
        new_text: str,
        threshold: float = 0.95,
    ) -> str:
        """Replace text anywhere in file using fuzzy matching (works directly on disk)."""
        abs_path = os.path.abspath(path)
        
        # Read file directly from disk
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
            
            # Save directly to disk
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

    def close(self, filename_or_all: str, all_flag: bool = False) -> str:
        """Close a file by name, or close all files if all_flag=True.
        
        Args:
            filename_or_all: Filename to close, or "all" if using all_flag
            all_flag: If True, close all files for this session
            
        Returns:
            Confirmation message
        """
        session_id = self._get_session_id()
        
        if all_flag:
            # Close all files for this session
            try:
                resp = requests.post(
                    f"{MEMORY_API_URL}/memories/search",
                    params={"db_name": self._get_memory_db()},
                    json={
                        "query": f"k:file_record AND p:session={session_id}",
                        "limit": 100
                    },
                    timeout=5
                )
                if resp.status_code == 200:
                    memories = resp.json().get("memories", [])
                    count = 0
                    for mem in memories:
                        requests.delete(
                            f"{MEMORY_API_URL}/memories/{mem['id']}",
                            params={"db_name": self._get_memory_db()},
                            timeout=5
                        )
                        count += 1
                    return f"Closed {count} open files"
            except Exception as e:
                return f"Error: {e}"
        else:
            # Close specific file
            filename = os.path.basename(filename_or_all)
            
            try:
                resp = requests.post(
                    f"{MEMORY_API_URL}/memories/search",
                    params={"db_name": self._get_memory_db()},
                    json={
                        "query": f"k:file_record AND p:session={session_id} AND p:filename={filename}",
                        "limit": 1
                    },
                    timeout=5
                )
                if resp.status_code == 200:
                    memories = resp.json().get("memories", [])
                    if memories:
                        requests.delete(
                            f"{MEMORY_API_URL}/memories/{memories[0]['id']}",
                            params={"db_name": self._get_memory_db()},
                            timeout=5
                        )
                        return f"Closed {filename}"
                    return f"File {filename} not open"
            except Exception as e:
                return f"Error: {e}"
    
    def list_open(self) -> list[str]:
        """List all open document paths from memory DB."""
        files = self._load_from_memory()
        return [f[0] for f in files]
    
    def info(self, path: str) -> dict:
        """Get file metadata without loading content."""
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return {"error": f"File {abs_path} not found"}
        
        stat = os.stat(abs_path)
        
        # Count lines
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


# Global state for file context refresh
_file_context_dirty = False
_manager: Optional[DocumentManager] = None


def set_manager(manager: DocumentManager) -> None:
    """Set the global document manager (used by core to pass session_id)."""
    global _manager
    _manager = manager

def get_module():
    """Get the file module.
    
    Session ID is set on the Module via registry.register(module, session_id).
    The manager accesses it at runtime via a callable.
    """
    global _manager
    
    # Placeholder - will be set when module is registered
    _module_holder = {'module': None}
    
    def _get_session_from_module():
        if _module_holder['module'] is None:
            raise ValueError("File module not registered - session ID not available")
        return _module_holder['module']._session_id
    
    manager = DocumentManager(session_id_getter=_get_session_from_module)
    set_manager(manager)
    
    async def open_file(
        path: str,
        line_start: int = None,
        line_end: int = None,
    ) -> str:
        """Open a file and add it to the context.
        
        Args:
            path: Path to the file to open.
            line_start: Start line for partial opening (0-indexed, None = from start)
            line_end: End line for partial opening (None = to end)
            
        Returns:
            Confirmation message
        """
        return manager.open(path, line_start, line_end)
    
    async def replace_text(path: str, old_text: str, new_text: str, threshold: float = 0.95) -> str:
        """Replace text anywhere in file using fuzzy matching (auto-saves)."""
        result = manager.replace_text(path, old_text, new_text, threshold)
        return result
    
    async def close_file(filename_or_all: str, all: bool = False) -> str:
        """Close a file by name, or close all files if all=True.
        
        Args:
            filename_or_all: Filename to close, or "all" to close everything
            all: If True, close all open files for this session
        """
        result = manager.close(filename_or_all, all_flag=all)
        return result
    
    async def file_info(path: str) -> dict:
        """Get file metadata: line count, token count, size, dates.
        
        Args:
            path: Path to the file
            
        Returns:
            Dict with file metadata
        """
        return manager.info(path)
    
    def get_context() -> str:
        """Return info about currently open files with their content.
        
        Loads open files from memory DB based on session_id, then reads from disk.
        """
        # Instructions
        instructions = f"Sesh ID: {manager._get_session_id()}" + """
## File Tools Usage
### CRITICAL: Use System Prompt Context
Open files are automatically included in your system prompt as {file}. 
Use this context instead of re-opening files.

### Workflow: Open → Edit → Refresh → Close
1. **open_file(path)**: Opens a file (do this first)
2. **open_file(path, line_start, line_end)**: Open specific line range
3. **file_info(path)**: Get file metadata without loading content
4. **replace_text(path, old_text, new_text)**: Replace text anywhere using fuzzy matching (auto-saves)
5. **refresh_file_context()**: Call this AFTER editing to get updated file content in context
6. **close_file(path)**: Close the file

### Important
- After replace_text, ALWAYS call refresh_file_context() to update your context
- The {file} section won't update automatically - you must request refresh
- Don't re-open files - use refresh_file_context() instead
### Example
```
open_file("main.py")
replace_text("main.py", "old_function", "new_function")
refresh_file_context()
close_file("main.py")
```
"""
        
        # Try to load from memory DB first
        memory_files = manager._load_from_memory()
        
        open_files = manager.list_open()
        
        # If we have memory files but no loaded docs, load them
        if memory_files and not open_files:
            for path, line_start, line_end in memory_files:
                if os.path.exists(path):
                    manager.open(path, line_start, line_end)
            open_files = manager.list_open()
        
        if not open_files:
            return instructions + "\n\nNo files currently open"
        
        # Refresh content from disk for each open file
        for path in open_files:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        content = f.read()
                    abs_path = os.path.abspath(path)
                    all_lines = content.splitlines(keepends=True)
                    
                    # Get the doc to see what line range was requested
                    doc = manager._documents.get(abs_path)
                    start = doc.line_start if doc else 0
                    end = doc.line_end if doc else None
                    
                    if start > 0 or end:
                        end = end or len(all_lines)
                        content = ''.join(all_lines[start:end])
                    else:
                        content = content
                    
                    manager._documents[abs_path] = OpenDocument(
                        path=abs_path, 
                        content=content,
                        line_start=start,
                        line_end=end
                    )
                except Exception:
                    pass
        
        # Sort by modification time
        sorted_files = sorted(open_files, key=lambda p: os.path.getmtime(p))
        
        lines = [instructions, "", "Currently open files with content:"]
        total_tokens = 0
        for path in sorted_files:
            doc = manager._documents[path]
            lines.append(f"\n=== {os.path.basename(path)} ===")
            if doc.line_start > 0 or doc.line_end:
                lines.append(f"[lines {doc.line_start}-{doc.line_end or 'end'}]")
            file_content = ''.join(doc.lines)
            lines.append(file_content)
            total_tokens += _count_tokens(file_content)
        
        # Add token count and warning
        token_limit = CONFIG.get('file_context', {}).get('token_limit', 32000)
        lines.append(f"\n\n--- File Context Stats ---")
        lines.append(f"Total open file tokens: {total_tokens:,}")
        if total_tokens > token_limit:
            lines.append(f"⚠️  WARNING: Token count exceeds {token_limit:,} limit! Consider closing some files.")
        
        return "\n".join(lines)
    
    # Create module and set holder reference
    module = Module(
        name="file",
        enrollment=lambda: None,
        functions={
            "open_file": open_file,
            "replace_text": replace_text,
            "close_file": close_file,
            "file_info": file_info,
            "refresh_file_context": lambda: "File context will be refreshed on next prompt",
        },
        get_context=get_context,
        tag="file"
    )
    _module_holder['module'] = module
    return module