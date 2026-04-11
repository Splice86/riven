"""Core Manager - manages core instances with threaded I/O channels."""

import os
import glob
import yaml
import uuid
import threading
import queue
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, field
from datetime import datetime


# ============== CHANNELS ==============

class Channel:
    """Message channel with emit pattern for callbacks."""
    
    def __init__(self):
        self._callbacks: List[Callable] = []
    
    def emit(self, callback: Callable) -> None:
        """Register a callback to fire when messages are sent."""
        self._callbacks.append(callback)
    
    def _fire(self, message) -> None:
        """Fire all callbacks with the message."""
        for cb in self._callbacks:
            try:
                cb(message)
            except Exception as e:
                print(f"Channel callback error: {e}")


class InputChannel(Channel):
    """Channel for sending messages INTO a core."""
    
    def __init__(self):
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
    
    def send(self, message: str) -> None:
        """Queue a message to be processed by the core."""
        self._queue.put(message)
        self._fire(message)
    
    def get(self, timeout: float = None) -> str:
        """Get next message from queue."""
        return self._queue.get(timeout=timeout)
    
    def empty(self) -> bool:
        return self._queue.empty()


class OutputChannel(Channel):
    """Channel for receiving messages FROM a core."""
    
    def __init__(self):
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
    
    def send(self, message: str) -> None:
        """Push a message to output (for external producers)."""
        self._queue.put(message)
        self._fire(message)
    
    def get(self, timeout: float = None) -> str:
        """Get next message from queue."""
        return self._queue.get(timeout=timeout)
    
    def empty(self) -> bool:
        return self._queue.empty()


# ============== CORE INSTANCE ==============

@dataclass
class CoreInstance:
    """A running core instance with I/O channels."""
    id: str
    session_id: str
    core_name: str
    thread: Optional[threading.Thread] = None
    input_channel: InputChannel = field(default_factory=InputChannel)
    output_channel: OutputChannel = field(default_factory=OutputChannel)
    started_at: datetime = field(default_factory=datetime.now)
    status: str = "starting"  # starting, running, stopping, stopped


# ============== CORE MANAGER ==============

class CoreManager:
    """Manages core instances with threading and channels."""
    
    def __init__(self):
        self._cores: Dict[str, Dict] = {}  # name -> config
        self._instances: Dict[str, CoreInstance] = {}  # session_id -> instance
        self._current_session: Optional[str] = None
        self._lock = threading.Lock()
        self._load_cores()
    
    def _load_cores(self) -> None:
        """Load available cores from the cores/ folder."""
        cores_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            "cores"
        )
        
        if not os.path.exists(cores_dir):
            return
        
        for filepath in glob.glob(os.path.join(cores_dir, "*.yaml")):
            with open(filepath) as f:
                config = yaml.safe_load(f)
                if config and 'name' in config:
                    name = config.pop('name')
                    self._cores[name] = config
    
    def list(self) -> List[Dict]:
        """List available cores."""
        return [
            {
                'name': name,
                'display_name': config.get('display_name', name),
                'description': config.get('description', ''),
            }
            for name, config in self._cores.items()
        ]
    
    def get(self, name: str) -> Optional[Dict]:
        """Get core config by name."""
        return self._cores.get(name)
    
    def exists(self, name: str) -> bool:
        """Check if a core exists."""
        return name in self._cores
    
    def get_current(self) -> Optional[str]:
        """Get the current session ID."""
        return self._current_session
    
    def set_current(self, session_id: str) -> str:
        """Set the current session.
        
        Args:
            session_id: Session to make active
            
        Returns:
            Confirmation message
        """
        if session_id not in self._instances:
            return f"Session '{session_id}' not found"
        
        self._current_session = session_id
        inst = self._instances[session_id]
        return f"Switched to session {session_id} ({inst.core_name})"
    
    def start(self, session_id: str = None, core_name: str = None, 
              memory_api_url: str = "http://localhost:8030",
              default_db: str = "riven") -> Dict:
        """Start a new core instance.
        
        Args:
            session_id: Optional session ID (creates/gets from DB if not provided)
            core_name: Optional core name (uses default if not provided)
            memory_api_url: URL for memory API
            default_db: Default database name
            
        Returns:
            dict with 'session_id', 'message', 'ok'
        """
        # Load default core from config if not provided
        if core_name is None:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 
                "config.yaml"
            )
            if os.path.exists(config_path):
                with open(config_path) as f:
                    cfg = yaml.safe_load(f)
                    core_name = cfg.get('default_core', 'code_hammer')
            else:
                core_name = 'code_hammer'
        
        # Validate core exists
        if core_name not in self._cores:
            available = ", ".join(self._cores.keys())
            return {
                "session_id": None,
                "message": f"Core '{core_name}' not found. Available: {available}",
                "ok": False
            }
        
        # Get or create session ID
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        # Check if already running
        with self._lock:
            if session_id in self._instances:
                inst = self._instances[session_id]
                return {
                    "session_id": session_id,
                    "message": f"Session {session_id} already running with {inst.core_name}",
                    "ok": True
                }
        
        # Create instance
        instance = CoreInstance(
            id=session_id,
            session_id=session_id,
            core_name=core_name,
        )
        
        # Start core thread
        def core_loop():
            """Run the core in a loop, processing input channel."""
            try:
                instance.status = "running"
                self._run_core(instance, memory_api_url, default_db)
            except Exception as e:
                print(f"Core error: {e}")
            finally:
                instance.status = "stopped"
        
        instance.thread = threading.Thread(target=core_loop, daemon=True)
        instance.thread.start()
        
        # Store instance
        with self._lock:
            self._instances[session_id] = instance
            self._current_session = session_id
        
        display = self._cores[core_name].get('display_name', core_name)
        return {
            "session_id": session_id,
            "message": f"Running {display} with session {session_id}",
            "ok": True
        }
    
    def _run_core(self, instance: CoreInstance, memory_api_url: str, default_db: str):
        """Run the core loop with actual core."""
        import asyncio
        import threading
        import sys
        from core import get_core
        
        def process_message(msg: str):
            """Process a single message synchronously."""
            try:
                result = asyncio.run(core.run(msg))
                if result and hasattr(result, 'output'):
                    instance.output_channel.send(str(result.output))
                elif result:
                    instance.output_channel.send(str(result))
            except Exception as e:
                instance.output_channel.send(f"Error: {e}")
        
        # Create the real core instance
        core = get_core(instance.core_name)
        
        def run_loop():
            """Run core in background thread."""
            while instance.status == "running":
                try:
                    msg = instance.input_channel.get(timeout=1)
                    process_message(msg)
                except queue.Empty:
                    continue
                except Exception as e:
                    instance.output_channel.send(f"Error: {e}")
                    break
        
        # Run in background thread
        core_thread = threading.Thread(target=run_loop, daemon=True)
        core_thread.start()
    
    def stop(self, session_id: str) -> Dict:
        """Stop a running core instance.
        
        Args:
            session_id: Session to stop
            
        Returns:
            dict with 'message', 'ok'
        """
        with self._lock:
            if session_id not in self._instances:
                return {"message": f"Session '{session_id}' not found", "ok": False}
            
            instance = self._instances[session_id]
            instance.status = "stopping"
            
            if instance.thread and instance.thread.is_alive():
                instance.thread.join(timeout=5)
            
            del self._instances[session_id]
            
            if self._current_session == session_id:
                self._current_session = None
        
        return {"message": f"Stopped session {session_id}", "ok": True}
    
    def send(self, session_id: str, message: str) -> Dict:
        """Send a message to a running core.
        
        Args:
            session_id: Target session
            message: Message to send
            
        Returns:
            dict with 'ok'
        """
        with self._lock:
            if session_id not in self._instances:
                return {"ok": False, "error": f"Session '{session_id}' not found"}
        
        instance = self._instances[session_id]
        instance.input_channel.send(message)
        return {"ok": True}
    
    def receive(self, session_id: str, timeout: float = 0.1) -> List[str]:
        """Receive messages from a running core.
        
        Args:
            session_id: Source session
            timeout: Max time to wait
            
        Returns:
            List of message strings
        """
        messages = []
        
        with self._lock:
            if session_id not in self._instances:
                return []
            instance = self._instances[session_id]
        
        while not instance.output_channel.empty():
            try:
                msg = instance.output_channel.get(timeout=0.01)
                messages.append(msg)
            except queue.Empty:
                break
        
        return messages
    
    def list_sessions(self) -> List[Dict]:
        """List all running sessions."""
        with self._lock:
            return [
                {
                    "session_id": inst.session_id,
                    "core_name": inst.core_name,
                    "status": inst.status,
                    "started_at": inst.started_at.isoformat(),
                    "is_current": inst.session_id == self._current_session,
                }
                for inst in self._instances.values()
            ]
    
    def get_instance(self, session_id: str) -> Optional[CoreInstance]:
        """Get a core instance by session ID."""
        return self._instances.get(session_id)
    
    def get_channels(self, session_id: str) -> Optional[tuple]:
        """Get input/output channels for a session."""
        inst = self._instances.get(session_id)
        if inst:
            return (inst.input_channel, inst.output_channel)
        return None
    
    def get_config(self, name: str = None) -> Dict:
        """Get full config for a core."""
        if name is None and self._current_session:
            inst = self._instances.get(self._current_session)
            name = inst.core_name if inst else None
        return self._cores.get(name, {})


# ============== GLOBAL INSTANCE ==============

_manager: Optional[CoreManager] = None


def get_manager() -> CoreManager:
    """Get the global CoreManager instance."""
    global _manager
    if _manager is None:
        _manager = CoreManager()
    return _manager


# ============== CONVENIENCE FUNCTIONS ==============

def list_cores() -> List[Dict]:
    """List available cores."""
    return get_manager().list()


def start(session_id: str = None, core_name: str = None) -> Dict:
    """Start a new core instance."""
    return get_manager().start(session_id, core_name)


def stop(session_id: str) -> Dict:
    """Stop a running core."""
    return get_manager().stop(session_id)


def send(session_id: str, message: str) -> Dict:
    """Send a message to a core."""
    return get_manager().send(session_id, message)


def receive(session_id: str, timeout: float = 0.1) -> List[str]:
    """Receive messages from a core."""
    return get_manager().receive(session_id, timeout)


def list_sessions() -> List[Dict]:
    """List running sessions."""
    return get_manager().list_sessions()


def get_current_session() -> Optional[str]:
    """Get current session ID."""
    return get_manager().get_current()


def switch_session(session_id: str) -> str:
    """Switch to a different session."""
    return get_manager().set_current(session_id)


def core_exists(name: str) -> bool:
    """Check if a core exists."""
    return get_manager().exists(name)