"""File module for riven - manage open files with line editing."""

import os
from dataclasses import dataclass, field
from typing import Optional

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


class DocumentManager:
    """Manages open documents with line-aware operations."""
    
    def __init__(self):
        self._documents: dict[str, OpenDocument] = {}
    
    def open(
        self,
        path: str,
        show_line_numbers: bool = True,
        max_lines: Optional[int] = None
    ) -> str:
        """Open a document, add to context, and display content.
        
        Once opened, the file stays in memory until explicitly closed.
        Use get_lines, replace_lines, insert_lines, or remove_lines to modify.
        Use save_file to write changes to disk.
        
        Args:
            path: Path to the file
            show_line_numbers: Include line numbers in output (default: True)
            max_lines: Truncate output to N lines (None for all, 200 for auto-truncate)
            
        Returns:
            Document content with line numbers (or just confirmation if show_line_numbers=False)
        """
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found"
        
        if abs_path in self._documents and not show_line_numbers:
            # Already open, just return content without re-reading
            doc = self._documents[abs_path]
            content = doc.content
        else:
            try:
                with open(abs_path, 'r') as f:
                    content = f.read()
            except Exception as e:
                return f"Error reading {abs_path}: {e}"
            
            self._documents[abs_path] = OpenDocument(path=abs_path, content=content)
        
        doc = self._documents[abs_path]
        
        # Format with line numbers
        if show_line_numbers:
            return self._format_with_lines(doc, max_lines)
        else:
            return f"Opened {abs_path} ({len(doc.lines)} lines)"
    
    def _format_with_lines(self, doc: OpenDocument, max_lines: Optional[int] = None) -> str:
        """Format document content with line numbers."""
        lines = doc.lines
        truncated = False
        display_count = len(lines)
        
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True
            display_count = max_lines
        elif len(lines) > 1000:
            lines = lines[:1000]
            truncated = True
            display_count = 1000
        
        # Calculate padding for line numbers
        num_digits = len(str(len(lines)))
        fmt = f"{{:{num_digits}}} │ {{}}"
        
        output_lines = [f"File: {doc.path} ({len(doc.lines)} lines)"]
        
        for i, line in enumerate(lines, 1):
            output_lines.append(fmt.format(i, line.rstrip('\n')))
        
        if truncated:
            output_lines.append(f"... ({len(doc.lines) - display_count} more lines)")
        
        return "\n".join(output_lines)
    
    def get_lines(self, path: str, start: int = 1, end: Optional[int] = None) -> str:
        """Get a specific range of lines from an open document."""
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_file first."
        
        doc = self._documents[abs_path]
        
        if start < 1:
            start = 1
        if end is None or end > len(doc.lines):
            end = len(doc.lines)
        
        if start > end:
            return f"Error: start line {start} > end line {end}"
        
        # Get lines (0-indexed in list, but user uses 1-indexed)
        selected = doc.lines[start-1:end]
        
        num_digits = len(str(len(selected)))
        fmt = f"{{:{num_digits}}} │ {{}}"
        
        output_lines = [f"Lines {start}-{end} from {os.path.basename(path)}"]
        for i, line in enumerate(selected, start):
            output_lines.append(fmt.format(i, line.rstrip('\n')))
        
        return "\n".join(output_lines)
    
    def replace_lines(self, path: str, start: int, end: int, new_content: str) -> str:
        """Replace a range of lines with new content."""
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_file first."
        
        doc = self._documents[abs_path]
        
        if start < 1:
            start = 1
        if end > len(doc.lines):
            end = len(doc.lines)
        
        # Convert to list of lines
        new_lines = new_content.splitlines(keepends=True)
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'
        
        # Replace in place
        doc.lines[start-1:end] = new_lines
        doc.content = ''.join(doc.lines)
        
        return f"Replaced lines {start}-{end} with {len(new_lines)} lines"
    
    def insert_lines(self, path: str, after_line: int, new_content: str) -> str:
        """Insert new content after a specific line."""
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_file first."
        
        doc = self._documents[abs_path]
        
        if after_line < 0 or after_line > len(doc.lines):
            return f"Error: invalid after_line {after_line}"
        
        new_lines = new_content.splitlines(keepends=True)
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'
        
        doc.lines[after_line:after_line] = new_lines
        doc.content = ''.join(doc.lines)
        
        return f"Inserted {len(new_lines)} lines after line {after_line}"
    
    def remove_lines(self, path: str, start: int, end: int) -> str:
        """Remove a range of lines."""
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_file first."
        
        doc = self._documents[abs_path]
        
        if start < 1:
            start = 1
        if end > len(doc.lines):
            end = len(doc.lines)
        
        num_removed = end - start + 1
        del doc.lines[start-1:end]
        doc.content = ''.join(doc.lines)
        
        return f"Removed lines {start}-{end} from {os.path.basename(path)} ({num_removed} lines)"
    
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
    
    def save_all(self) -> str:
        """Save all open documents."""
        saved = []
        errors = []
        
        for path, doc in self._documents.items():
            try:
                with open(path, 'w') as f:
                    f.write(doc.content)
                saved.append(os.path.basename(path))
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
        
        if errors:
            return f"Saved {len(saved)} files. Errors: {'; '.join(errors)}"
        return f"Saved {len(saved)} files: {', '.join(saved)}"
    
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


def get_module():
    """Get the file module."""
    manager = DocumentManager()
    
    async def open_file(
        path: str,
        show_line_numbers: bool = True,
        max_lines: Optional[int] = None
    ) -> str:
        """Open a file and add it to the context.
        
        Args:
            path: Path to the file to open.
            show_line_numbers: Include line numbers in output (default: True)
            max_lines: Maximum lines to show (None for all, use 200 for auto-truncate)
            
        Returns:
            File content with line numbers
        """
        return manager.open(path, show_line_numbers, max_lines)
    
    async def get_lines(path: str, start: int = 1, end: Optional[int] = None) -> str:
        """Get a specific range of lines from an open file.
        
        Args:
            path: Path to the file.
            start: Start line number (1-indexed).
            end: End line number (inclusive, None for all remaining).
            
        Returns:
            Selected lines with numbers
        """
        return manager.get_lines(path, start, end)
    
    async def replace_lines(path: str, start: int, end: int, new_content: str) -> str:
        """Replace a range of lines with new content.
        
        Args:
            path: Path to the file.
            start: Start line number (1-indexed, inclusive).
            end: End line number (inclusive).
            new_content: The new content to replace the range with.
            
        Returns:
            Confirmation message
        """
        return manager.replace_lines(path, start, end, new_content)
    
    async def insert_lines(path: str, after_line: int, new_content: str) -> str:
        """Insert new content after a specific line.
        
        Args:
            path: Path to the file.
            after_line: Insert after this line number.
            new_content: Content to insert.
            
        Returns:
            Confirmation message
        """
        return manager.insert_lines(path, after_line, new_content)
    
    async def remove_lines(path: str, start: int, end: int) -> str:
        """Remove a range of lines.
        
        Args:
            path: Path to the file.
            start: Start line number (1-indexed).
            end: End line number (inclusive).
            
        Returns:
            Confirmation message
        """
        return manager.remove_lines(path, start, end)
    
    async def save_file(path: str) -> str:
        """Save an open file's in-memory changes to disk.
        
        Args:
            path: Path to the file to save.
            
        Returns:
            Confirmation message
        """
        return manager.save(path)
    
    async def save_all_files() -> str:
        """Save all open files to disk.
        
        Returns:
            Confirmation message
        """
        return manager.save_all()
    
    async def close_file(path: str) -> str:
        """Close a file and remove it from the context.
        
        Args:
            path: Path to the file to close.
            
        Returns:
            Status message
        """
        return manager.close(path)
    
    async def list_open_files() -> str:
        """List all currently open files.
        
        Returns:
            Formatted list of open files
        """
        open_files = manager.list_open()
        if not open_files:
            return "No files open"
        
        lines = ["Open files:"]
        for path in open_files:
            doc = manager._documents[path]
            lines.append(f"  - {os.path.basename(path)} ({len(doc.lines)} lines)")
        
        return "\n".join(lines)
    
    return Module(
        name="file",
        enrollment=lambda: None,
        functions={
            "open_file": open_file,
            "get_lines": get_lines,
            "replace_lines": replace_lines,
            "insert_lines": insert_lines,
            "remove_lines": remove_lines,
            "save_file": save_file,
            "save_all_files": save_all_files,
            "close_file": close_file,
            "list_open_files": list_open_files,
        }
    )