"""Core Manager - manages core instances and switching between them."""

import os
import glob
import yaml
import uuid
from typing import Optional, List, Dict


class CoreManager:
    """Manages core instances and switching between them."""
    
    def __init__(self):
        self._cores: dict[str, dict] = {}  # name -> config
        self._current: Optional[str] = None
        self._instances: dict[str, dict] = {}  # instance_id -> instance data
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
        """List available cores.
        
        Returns:
            List of dicts with 'name', 'display_name', 'description'
        """
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
        """Get the current core name."""
        return self._current
    
    def set_current(self, name: str) -> str:
        """Set the current core.
        
        Args:
            name: Core name to switch to
            
        Returns:
            Confirmation message
        """
        if name not in self._cores:
            available = ", ".join(self._cores.keys())
            return f"Core '{name}' not found. Available: {available}"
        
        self._current = name
        display = self._cores[name].get('display_name', name)
        desc = self._cores[name].get('description', '')
        return f"Switched to {display}: {desc}"
    
    def create_instance(self, name: str = None) -> str:
        """Create a new core instance.
        
        Args:
            name: Core name (uses current if not provided)
            
        Returns:
            Instance ID
        """
        if name is None:
            name = self._current or list(self._cores.keys())[0]
        
        if name not in self._cores:
            raise ValueError(f"Core '{name}' not found")
        
        instance_id = f"{name}_{str(uuid.uuid4())[:8]}"
        self._instances[instance_id] = {
            'name': name,
            'created_at': None,  # TODO: timestamp
        }
        return instance_id
    
    def get_instance(self, instance_id: str) -> Optional[dict]:
        """Get an instance by ID."""
        return self._instances.get(instance_id)
    
    def list_instances(self) -> List[Dict]:
        """List all instances."""
        return [
            {
                'id': id_,
                'name': inst['name'],
            }
            for id_, inst in self._instances.items()
        ]
    
    def get_config(self, name: str = None) -> Dict:
        """Get full config for a core."""
        if name is None:
            name = self._current
        return self._cores.get(name, {})


# Global instance
_manager: Optional[CoreManager] = None


def get_manager() -> CoreManager:
    """Get the global CoreManager instance."""
    global _manager
    if _manager is None:
        _manager = CoreManager()
    return _manager


# Convenience functions
def list_cores() -> list[dict]:
    """List available cores."""
    return get_manager().list()


def get_current_core() -> Optional[str]:
    """Get the current core name."""
    return get_manager().get_current()


def switch_core(name: str) -> str:
    """Switch to a different core."""
    return get_manager().set_current(name)


def core_exists(name: str) -> bool:
    """Check if a core exists."""
    return get_manager().exists(name)