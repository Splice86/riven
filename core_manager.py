"""Core Manager - simplified: session ID provides persistence, core is created per message."""

import os
import glob
import yaml
import uuid
import asyncio
from typing import Optional, List, Dict
from core import get_core


# ============== CORE MANAGER ==============

class CoreManager:
    """Manages cores - creates fresh core per message, session provides context."""
    
    def __init__(self):
        self._cores: Dict[str, Dict] = {}  # name -> config
        self._current_session: Optional[str] = None
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
        """Set the current session."""
        self._current_session = session_id
        return f"Switched to session {session_id}"
    
    def start(self, session_id: str = None, core_name: str = None,
              memory_api_url: str = "http://localhost:8030",
              default_db: str = "riven") -> Dict:
        """Start a new session (creates session ID, core is created per message)."""
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
        
        # Create session ID if not provided
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        self._current_session = session_id
        display = self._cores[core_name].get('display_name', core_name)
        
        return {
            "session_id": session_id,
            "message": f"Session {session_id} ready with {display}",
            "ok": True
        }
    
    def send(self, session_id: str, message: str, core_name: str = None) -> Dict:
        """Send a message - creates core, runs, returns output, drops core.
        
        Args:
            session_id: Session ID for context (via memory API)
            message: Message to send
            core_name: Optional core to use (uses default if not provided)
            
        Returns:
            dict with 'ok', 'output'
        """
        if core_name is None:
            core_name = self._get_default_core()
        
        if core_name not in self._cores:
            return {"ok": False, "error": f"Core '{core_name}' not found"}
        
        self._current_session = session_id
        
        try:
            # Create fresh core instance
            core = get_core(core_name)
            
            # Run synchronously
            result = asyncio.run(core.run(message))
            
            if result and hasattr(result, 'output'):
                output = str(result.output)
            elif result:
                output = str(result)
            else:
                output = ""
            
            return {"ok": True, "output": output}
            
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def _get_default_core(self) -> str:
        """Get default core name from config."""
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            "config.yaml"
        )
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
                return cfg.get('default_core', 'code_hammer')
        return 'code_hammer'
    
    def stop(self, session_id: str) -> Dict:
        """Stop a session (no-op since core is created per message)."""
        return {"message": f"Session {session_id} ended", "ok": True}
    
    def list_sessions(self) -> List[Dict]:
        """List sessions (simplified - just current)."""
        if self._current_session:
            return [{"session_id": self._current_session}]
        return []


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
    """Start a new session."""
    return get_manager().start(session_id, core_name)


def stop(session_id: str) -> Dict:
    """Stop a session."""
    return get_manager().stop(session_id)


def send(session_id: str, message: str, core_name: str = None) -> Dict:
    """Send a message and get output."""
    return get_manager().send(session_id, message, core_name)


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