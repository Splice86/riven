"""Socket base class for core communication."""

from abc import ABC, abstractmethod
from typing import Optional
from core_manager import get_manager


class SocketBase(ABC):
    """Abstract base class for sockets."""
    
    def __init__(self, session_strategy: str = "new"):
        """Initialize socket.
        
        Args:
            session_strategy: "new" for new session each time, 
                              "reuse" to reuse same session
        """
        self._session_strategy = session_strategy
        self._session_id: Optional[str] = None
        self._manager = get_manager()
    
    @property
    def session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self._session_id
    
    def connect(self, session_id: str = None, core_name: str = None) -> str:
        """Connect to core, returns session_id."""
        # Start the core
        result = self._manager.start(session_id=session_id, core_name=core_name)
        
        if result["ok"]:
            self._session_id = result["session_id"]
        
        return self._session_id
    
    def send(self, message: str) -> dict:
        """Send message to core, returns result dict with 'ok' and 'output'."""
        if not self._session_id:
            return {"ok": False, "error": "Not connected"}
        return self._manager.send(self._session_id, message)
    
    def disconnect(self) -> None:
        """Disconnect (no-op since core is created per message)."""
        self._session_id = None
    
    @abstractmethod
    def run(self) -> None:
        """Run the socket - to be implemented by subclasses."""
        pass