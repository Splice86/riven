"""File module for riven - manage open files with line editing."""

import os
from dataclasses import dataclass, field
from typing import Optional

# For fuzzy matching
try:
    import jellyfish
    HAS_JELLYFISH = True
except ImportError:
    HAS_JELLYFISH = False

from modules import Module


@dataclass
class OpenDocument:
    """A document open in the context."""
    path: str
    content: str
    lines: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        # Pre-split into lines for easy editing
        self.lines = self.content.splitlines(keepends=True)


def _find_best_window(
    haystack_lines: list[str],
    needle: str,
    threshold: float = 0.95
) -> tuple[tuple[int, int] | None, float]:
    """Find line window with best Jaro-Winkler similarity to needle.
    
    Args:
        haystack_lines: Lines to search in
        needle: Text to match
        threshold: Minimum similarity score (0.0-1.0)
    
    Returns:
        Tuple of (span, score) where span is (start, end) line indices,
        or (None, score) if no match above threshold
    """
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


class DocumentManager:
    """Manages open documents with line-aware operations."""
    
    def __init__(self):
        self._documents: dict[str, OpenDocument] = {}
    
    def open(
        self,
        path: str,
    ) -> str:
        """Open a document and add to context.
        
        Once opened, the file content is available in the system prompt.
        Use get_lines, replace_lines, insert_lines, or remove_lines to modify.
        All edits auto-save automatically.
        
        Args:
            path: Path to the file
            
        Returns:
            Confirmation message
        """
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found"
        
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
        except Exception as e:
            return f"Error reading {abs_path}: {e}"
        
        self._documents[abs_path] = OpenDocument(path=abs_path, content=content)
        doc = self._documents[abs_path]
        
        return f"Opened {os.path.basename(abs_path)} ({len(doc.lines)} lines). File content is now in system prompt."
    
    def replace_text(
        self,
        path: str,
        old_text: str,
        new_text: str,
    ) -> str:
        """Replace text anywhere in file using fuzzy matching.
        
        Uses fuzzy matching (Jaro-Winkler 95%+) to find the text anywhere in the file.
        No need to specify line numbers - just provide the text to find and replace.
        
        Args:
            path: Path to the file.
            old_text: Text to find (will use fuzzy matching).
            new_text: Replacement text.
            
        Returns:
            Confirmation message with what was replaced.
        """
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_file first."
        
        doc = self._documents[abs_path]
        
        # First try exact match
        found = False
        for i, line in enumerate(doc.lines):
            if old_text in line:
                new_line = line.replace(old_text, new_text, 1)
                doc.lines[i] = new_line
                found = True
                break
        
        if not found:
            # Try fuzzy matching across the document
            span, score = _find_best_window(doc.lines, old_text)
            if span:
                start, end = span
                # Replace the matched span with new_text
                new_lines = new_text.splitlines(keepends=True)
                if new_lines and not new_lines[-1].endswith('\n'):
                    new_lines[-1] += '\n'
                doc.lines[start:end] = new_lines
                found = True
                self.save(abs_path)
                return f"Replaced lines {start+1}-{end} (fuzzy match {score:.0%})"
            else:
                # Show what's actually in the file to help model
                actual_content = ''.join(doc.lines[:20])
                return (
                    f"Text not found. The text you're looking for is not in the file.\n"
                    f"Expected (not in file):\n{repr(old_text[:200])}\n\n"
                    f"Best fuzzy match: {score:.0%}\n"
                    f"Actual file content (first 20 lines):\n{actual_content[:500]}\n\n"
                    f"Tip: Use open_file first to see current content, then provide EXACT text to replace."
                )
        
        doc.content = ''.join(doc.lines)
        self.save(abs_path)
        
        return f"Replaced text"
    
    def save(self, path: str) -> str:
        """Save an open document's in-memory changes to disk."""
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_file first."
        
        doc = self._documents[abs_path]
        
        try:
            with open(abs_path, 'w') as f:
                f.write(doc.content)
            return f"Saved {os.path.basename(path)} ({len(doc.lines)} lines)"
        except Exception as e:
            return f"Error saving {abs_path}: {e}"
    
    def close(self, path: str) -> str:
        """Close a document, remove from context."""
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open."
        
        del self._documents[abs_path]
        return f"Closed {os.path.basename(path)}"
    
    def list_open(self) -> list[str]:
        """List all open document paths."""
        return list(self._documents.keys())


# Global state for file context refresh
_file_context_dirty = False

def mark_dirty() -> None:
    """Mark file context as needing refresh."""
    global _file_context_dirty
    _file_context_dirty = True

def is_dirty() -> bool:
    """Check if file context needs refresh."""
    global _file_context_dirty
    return _file_context_dirty

def clear_dirty() -> None:
    """Clear the dirty flag after refresh."""
    global _file_context_dirty
    _file_context_dirty = False

def get_module():
    """Get the file module."""
    manager = DocumentManager()
    
    async def open_file(
        path: str,
    ) -> str:
        """Open a file and add it to the context.
        
        Args:
            path: Path to the file to open.
            
        Returns:
            Confirmation message
        """
        return manager.open(path)
    
    async def replace_text(path: str, old_text: str, new_text: str) -> str:
        """Replace text anywhere in file using fuzzy matching.
        
        Args:
            path: Path to the file.
            old_text: Text to find (uses fuzzy matching).
            new_text: Replacement text.
            
        Returns:
            Confirmation message with what was replaced.
        """
        result = manager.replace_text(path, old_text, new_text)
        mark_dirty()
        return result
    
    async def close_file(path: str) -> str:
        """Close a file and remove it from the context.
        
        Args:
            path: Path to the file to close.
            
        Returns:
            Status message
        """
        result = manager.close(path)
        mark_dirty()
        return result
    
    async def refresh_file_context() -> str:
        """Force refresh of file context. Call this after editing files to get updated content.
        
        Returns:
            Confirmation message
        """
        # This will trigger a refresh on next get_file_context call
        return "File context will be refreshed on next prompt"
    
    def get_file_context() -> str:
        """Return info about currently open files with their content."""
        global _file_context_dirty
        _file_context_dirty = False  # Clear dirty flag after refresh
        # Tool usage instructions
        instructions = """## File Tools Usage

### CRITICAL: Use System Prompt Context
Open files are automatically included in your system prompt as {file}. 
Use this context instead of re-opening files.

### Workflow: Open → Edit → Refresh → Close
1. **open_file(path)**: Opens a file (do this first)
2. **replace_text(path, old_text, new_text)**: Replace text anywhere using fuzzy matching (auto-saves)
3. **refresh_file_context()**: Call this AFTER editing to get updated file content in context
4. **close_file(path)**: Close the file

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
        
        open_files = manager.list_open()
        if not open_files:
            return instructions + "\n\nNo files currently open"
        
        # Refresh content from disk for each open file
        for path in open_files:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        content = f.read()
                    manager._documents[path] = OpenDocument(content)
                except Exception:
                    pass  # Keep cached version if read fails
        
        # Sort by modification time (oldest first = most recently modified at bottom)
        sorted_files = sorted(open_files, key=lambda p: os.path.getmtime(p))
        
        lines = [instructions, "", "Currently open files with content:"]
        for path in sorted_files:
            doc = manager._documents[path]
            lines.append(f"\n=== {os.path.basename(path)} ===")
            lines.append(''.join(doc.lines))
        return "\n".join(lines)
    
    return Module(
        name="file",
        enrollment=lambda: None,
        functions={
            "open_file": open_file,
            "replace_text": replace_text,
            "close_file": close_file,
            "refresh_file_context": refresh_file_context,
        },
        get_context=get_file_context,
        tag="file"
    )