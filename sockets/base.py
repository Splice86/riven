"""Socket base class for core communication."""

from abc import ABC, abstractmethod
from typing import Callable, Optional
from core_manager import get_manager


class SocketBase(ABC):
    """Abstract base class for sockets."""
    
    def __init__(self, session_strategy: str = "new"):
        """Initialize socket.
        
        Args:
            session_strategy: "new" for new session each time, 
                              "reuse" to reuse same session,
                              "auto" to try reuse, else new
        """
        self._session_strategy = session_strategy
        self._session_id: Optional[str] = None
        self._manager = get_manager()
        self._receive_callback: Optional[Callable] = None
    
    @property
    def session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self._session_id
    
    def connect(self, session_id: str = None, core_name: str = None) -> str:
        """Connect to core, returns session_id."""
        # Determine session strategy
        use_session = session_id
        
        if self._session_strategy == "reuse":
            # Use provided or stored session
            use_session = session_id or self._session_id
            if not use_session:
                use_session = "security"  # default persistent session
        
        elif self._session_strategy == "auto":
            # Use provided, else create new
            use_session = session_id
        
        # Start the core
        result = self._manager.start(session_id=use_session, core_name=core_name)
        
        if result["ok"]:
            self._session_id = result["session_id"]
            
            # Register output callback if we have one
            self._register_output_callback()
        
        return self._session_id
    
    def _register_output_callback(self) -> None:
        """Register callback on output channel."""
        channels = self._manager.get_channels(self._session_id)
        if channels and self._receive_callback:
            _, output = channels
            output.emit(self._receive_callback)
    
    def on_receive(self, callback: Callable[[str], None]) -> None:
        """Register callback for incoming messages from core."""
        self._receive_callback = callback
        # Register immediately if already connected
        if self._session_id:
            self._register_output_callback()
    
    def send(self, message: str) -> bool:
        """Send message to core."""
        if not self._session_id:
            return False
        result = self._manager.send(self._session_id, message)
        return result.get("ok", False)
    
    def receive(self, timeout: float = 0.1) -> list[str]:
        """Poll for messages from core."""
        if not self._session_id:
            return []
        return self._manager.receive(self._session_id, timeout)
    
    def disconnect(self) -> None:
        """Disconnect and optionally stop session."""
        if self._session_id and self._session_strategy == "new":
            # Stop session if new strategy
            self._manager.stop(self._session_id)
        self._session_id = None
    
    @abstractmethod
    def run(self) -> None:
        """Run the socket - to be implemented by subclasses."""
        pass