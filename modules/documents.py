"""Documents module for riven - manage open documents with line editing.

Workflow:
    1. open_document(path) - Opens a file, adds to context, shows content with line numbers
    2. get_lines(path, start, end) - View specific lines (must be open first)
    3. replace_lines(path, start, end, new_content) - Replace lines in memory
    4. insert_lines(path, after_line, new_content) - Insert new lines
    5. remove_lines(path, start, end) - Delete lines
    6. save_document(path) - Write changes to disk
    
Note: All edit operations work on the in-memory version. Call save_document to persist.
      Files stay open in context until explicitly closed with close_document.
"""

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
        Use save_document to write changes to disk.
        
        Args:
            path: Path to the file
            show_line_numbers: Include line numbers in output (default: True)
            max_lines: Truncate output to N lines (None for all, 200 for auto-truncate)
            
        Returns:
            Document content with line numbers (or just confirmation if show_line_numbers=False)
        """
        
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
        """Format document content with line numbers.
        
        Args:
            doc: OpenDocument instance
            max_lines: Maximum lines to show
            
        Returns:
            Formatted string with line numbers
        """
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
        """Get a specific range of lines from an open document.
        
        Args:
            path: Path to the file
            start: Start line number (1-indexed)
            end: End line number (inclusive, None for all remaining)
            
        Returns:
            Formatted lines with numbers
        """
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_document first."
        
        doc = self._documents[abs_path]
        
        # Convert to 0-indexed
        start_idx = max(0, start - 1)
        end_idx = min(len(doc.lines), end) if end else len(doc.lines)
        
        if start_idx >= len(doc.lines):
            return f"Error: Line {start} is beyond file ({len(doc.lines)} lines)"
        
        # Extract the requested range
        range_lines = doc.lines[start_idx:end_idx]
        
        # Format with line numbers
        num_digits = len(str(end_idx))
        fmt = f"{{:{num_digits}}} │ {{}}"
        
        output = [f"Lines {start}-{end_idx} of {len(doc.lines)}:"]
        for i, line in enumerate(range_lines, start):
            output.append(fmt.format(i, line.rstrip('\n')))
        
        return "\n".join(output)
    
    def replace_lines(
        self,
        path: str,
        start: int,
        end: int,
        new_content: str
    ) -> str:
        """Replace specific lines in an open document.
        
        Args:
            path: Path to the file
            start: Start line number (1-indexed, inclusive)
            end: End line number (inclusive)
            new_content: New content to replace the range with
            
        Returns:
            Confirmation message
        """
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_document first."
        
        doc = self._documents[abs_path]
        
        # Validate range
        if start < 1:
            return f"Error: Start line must be >= 1"
        if end > len(doc.lines):
            return f"Error: End line {end} is beyond file ({len(doc.lines)} lines)"
        if start > end:
            return f"Error: Start line must be <= end line"
        
        # Convert to 0-indexed
        start_idx = start - 1
        end_idx = end  # Exclusive for slicing
        
        # Split new content into lines
        new_lines = new_content.splitlines(keepends=True)
        
        # Ensure last line has newline if original did
        if new_lines and doc.lines[start_idx:end_idx]:
            # Check if we're replacing to the end of the file
            was_at_end = end_idx >= len(doc.lines)
            had_newline = doc.lines[start_idx:end_idx][-1].endswith('\n')
            
            if not was_at_end and had_newline and not new_lines[-1].endswith('\n'):
                new_lines[-1] += '\n'
        
        # Perform replacement
        doc.lines[start_idx:end_idx] = new_lines
        doc.content = ''.join(doc.lines)
        
        return f"Replaced lines {start}-{end} in {os.path.basename(path)} ({len(new_lines)} new lines)"
    
    def insert_lines(
        self,
        path: str,
        after_line: int,
        new_content: str
    ) -> str:
        """Insert new lines after a specific line.
        
        Args:
            path: Path to the file
            after_line: Insert after this line number
            new_content: Content to insert
            
        Returns:
            Confirmation message
        """
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_document first."
        
        doc = self._documents[abs_path]
        
        if after_line < 0 or after_line > len(doc.lines):
            return f"Error: after_line must be between 0 and {len(doc.lines)}"
        
        # Convert to 0-indexed (insert position)
        insert_idx = after_line
        
        # Split new content into lines
        new_lines = new_content.splitlines(keepends=True)
        
        # Ensure proper newlines
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'
        
        # Insert at position
        doc.lines[insert_idx:insert_idx] = new_lines
        doc.content = ''.join(doc.lines)
        
        return f"Inserted {len(new_lines)} lines after line {after_line} in {os.path.basename(path)}"
    
    def remove_lines(self, path: str, start: int, end: int) -> str:
        """Remove specific lines from an open document.
        
        Args:
            path: Path to the file
            start: Start line number (1-indexed, inclusive)
            end: End line number (inclusive)
            
        Returns:
            Confirmation message
        """
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_document first."
        
        doc = self._documents[abs_path]
        
        # Validate range
        if start < 1:
            return f"Error: Start line must be >= 1"
        if end > len(doc.lines):
            return f"Error: End line {end} is beyond file ({len(doc.lines)} lines)"
        if start > end:
            return f"Error: Start line must be <= end line"
        
        # Convert to 0-indexed
        start_idx = start - 1
        end_idx = end  # Exclusive for slicing
        
        # Count lines to remove
        num_removed = end_idx - start_idx
        
        # Remove the lines
        del doc.lines[start_idx:end_idx]
        doc.content = ''.join(doc.lines)
        
        return f"Removed lines {start}-{end} from {os.path.basename(path)} ({num_removed} lines)"
    
def save(self, path: str) -> str:
        """Save an open document's in-memory changes to disk.
        
        Writes the current in-memory content to the original file path.
        Use this after making edits with replace_lines, insert_lines, or remove_lines.
        
        Args:
            path: Path to the file (must already be open)
            
        Returns:
            Confirmation message with filename and line count
        """
        abs_path = os.path.abspath(path)
        
        if abs_path not in self._documents:
            return f"Error: {path} not open. Use open_document first."
        
        doc = self._documents[abs_path]
        
        try:
            with open(abs_path, 'w') as f:
                f.write(doc.content)
            return f"Saved {os.path.basename(path)} ({len(doc.lines)} lines)"
        except Exception as e:
            return f"Error saving {abs_path}: {e}"
    
    def save_all(self) -> str:
        """Save all open documents.
        
        Returns:
            Confirmation message
        """
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
def close(self, path: str) -> str:
        """Close a document, remove from context.
        
        Removes the file from memory. If there are unsaved changes, they are lost.
        Use save_document before closing if you want to keep changes.
        
        Args:
            path: Path to the file (must already be open)
            
        Returns:
            Status message (success or error)
        """
        abs_path = os.path.abspath(path)
        
        if abs_path in self._documents:
            del self._documents[abs_path]
            return f"Closed {path}"
        return f"Error: {path} not open"
    
    def get_context(self) -> str:
        """Get documents formatted for system prompt.
        
        Returns:
            Summary of open documents
        """
        if not self._documents:
            return "No documents open"
        
        parts = []
        for path, doc in self._documents.items():
            basename = os.path.basename(path)
            parts.append(f"{basename} ({len(doc.lines)} lines)")
        
        return "Open: " + ", ".join(parts)
    
    def list_open(self) -> list[str]:
        """List all open documents.
        
        Returns:
            List of open file paths
        """
        return list(self._documents.keys())


def get_module():
    """Get the documents module."""
    manager = DocumentManager()
    
    async def open_document(
        path: str,
        show_line_numbers: bool = True,
        max_lines: Optional[int] = None
    ) -> str:
        """Open a document and add it to the context.
        
        Args:
            path: Path to the document to open.
            show_line_numbers: Include line numbers in output (default: True)
            max_lines: Maximum lines to show (None for all, use 200 for auto-truncate)
            
        Returns:
            Document content with line numbers
        """
        return manager.open(path, show_line_numbers, max_lines)
    
    async def get_lines(path: str, start: int = 1, end: Optional[int] = None) -> str:
        """Get a specific range of lines from an open document.
        
        Args:
            path: Path to the document.
            start: Start line number (1-indexed).
            end: End line number (inclusive, None for all remaining).
            
        Returns:
            Formatted lines with numbers
        """
        return manager.get_lines(path, start, end)
    
    async def replace_lines(
        path: str,
        start: int,
        end: int,
        new_content: str
    ) -> str:
        """Replace specific lines in an open document.
        
        Args:
            path: Path to the document.
            start: Start line number (1-indexed, inclusive).
            end: End line number (inclusive).
            new_content: New content to replace the range with.
            
        Returns:
            Confirmation message
        """
        return manager.replace_lines(path, start, end, new_content)
    
    async def insert_lines(path: str, after_line: int, new_content: str) -> str:
        """Insert new lines after a specific line number.
        
        Args:
            path: Path to the document.
            after_line: Insert after this line number (0 = at start).
            new_content: Content to insert.
            
        Returns:
            Confirmation message
        """
        return manager.insert_lines(path, after_line, new_content)
    
    async def remove_lines(path: str, start: int, end: int) -> str:
        """Remove specific lines from an open document.
        
        Args:
            path: Path to the document.
            start: Start line number (1-indexed, inclusive).
            end: End line number (inclusive).
            
        Returns:
            Confirmation message
        """
        return manager.remove_lines(path, start, end)
    
    async def save_document(path: str) -> str:
        """Save an open document to disk.
        
        Args:
            path: Path to the document to save.
            
        Returns:
            Confirmation message
        """
        return manager.save(path)
    
    async def save_all_documents() -> str:
        """Save all open documents to disk.
        
        Returns:
            Confirmation message
        """
        return manager.save_all()
    
    async def close_document(path: str) -> str:
        """Close a document and remove it from the context.
        
        Args:
            path: Path to the document to close.
            
        Returns:
            Status message
        """
        return manager.close(path)
    
    async def list_open_documents() -> str:
        """List all currently open documents.
        
        Returns:
            Formatted list of open files
        """
        open_files = manager.list_open()
        if not open_files:
            return "No documents open"
        
        lines = ["Open documents:"]
        for path in open_files:
            doc = manager._documents[path]
            lines.append(f"  - {os.path.basename(path)} ({len(doc.lines)} lines)")
        
        return "\n".join(lines)
    
    return Module(
        name="documents",
        enrollment=lambda: None,
        functions={
            "open_document": open_document,
            "get_lines": get_lines,
            "replace_lines": replace_lines,
            "insert_lines": insert_lines,
            "remove_lines": remove_lines,
            "save_document": save_document,
            "save_all_documents": save_all_documents,
            "close_document": close_document,
            "list_open_documents": list_open_documents,
        },
        get_context=manager.get_context,
        tag="documents"
    )