"""Documents module for riven - manage open documents in context."""

from dataclasses import dataclass
from modules import Module


@dataclass
class OpenDocument:
    """A document open in the context."""
    path: str
    content: str


class DocumentManager:
    """Manages open documents."""
    
    def __init__(self):
        self._documents: dict[str, OpenDocument] = {}
    
    def open(self, path: str) -> str:
        """Open a document, add to context."""
        import os
        abs_path = os.path.abspath(path)
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            self._documents[abs_path] = OpenDocument(path=abs_path, content=content)
            return f"Opened {abs_path} ({len(content)} chars)"
        except FileNotFoundError:
            return f"Error: File {abs_path} not found"
        except Exception as e:
            return f"Error opening {abs_path}: {e}"
    
    def close(self, path: str) -> str:
        """Close a document, remove from context."""
        if path in self._documents:
            del self._documents[path]
            return f"Closed {path}"
        return f"Error: {path} not open"
    
    def get_context(self) -> str:
        """Get documents formatted for system prompt."""
        if not self._documents:
            return "No documents open"
        
        parts = []
        for doc in self._documents.values():
            # Show first 500 chars as preview
            preview = doc.content[:500]
            if len(doc.content) > 500:
                preview += f"\n... ({len(doc.content) - 500} more chars)"
            
            parts.append(f"File: {doc.path}\n{preview}")
        
        return "\n\n".join(parts)


def get_documents_module():
    """Get the documents module."""
    manager = DocumentManager()
    
    async def open_document(path: str) -> str:
        """Open a document and add it to the context.
        
        Args:
            path: Path to the document to open.
            
        Returns:
            Status message with document info.
        """
        return manager.open(path)
    
    async def close_document(path: str) -> str:
        """Close a document and remove it from the context.
        
        Args:
            path: Path to the document to close.
            
        Returns:
            Status message.
        """
        return manager.close(path)
    
    return Module(
        name="documents",
        enrollment=lambda: None,
        functions={
            "open_document": open_document,
            "close_document": close_document,
        },
        get_context=manager.get_context,
        tag="documents"
    )
