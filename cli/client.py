"""Riven API Client - connects to Riven API server."""

import os
import yaml
import requests
from typing import Optional, List, Dict


# ============== CONFIG ==============

def _load_config() -> dict:
    """Load CLI config from secrets.yaml."""
    config_path = os.path.join(os.path.dirname(__file__), "secrets.yaml")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {"api": {"url": "http://localhost:8080", "timeout": 60}}

CONFIG = _load_config()
API_URL = CONFIG.get("api", {}).get("url", "http://localhost:8080")
API_TIMEOUT = CONFIG.get("api", {}).get("timeout", 60)


# ============== CLIENT ==============

class RivenClient:
    """Client for Riven API."""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or API_URL
        self.session_id: Optional[str] = None
    
    def list_cores(self) -> List[Dict]:
        """List available cores."""
        resp = requests.get(f"{self.base_url}/api/v1/cores")
        resp.raise_for_status()
        return resp.json().get("cores", [])
    
    def create_session(self, core_name: str = None) -> Dict:
        """Create a new session."""
        data = {"core_name": core_name} if core_name else {}
        resp = requests.post(f"{self.base_url}/api/v1/sessions", json=data)
        resp.raise_for_status()
        result = resp.json()
        self.session_id = result.get("session_id")
        return result
    
    def send_message(self, message: str, stream: bool = False) -> Dict:
        """Send a message to the current session."""
        if not self.session_id:
            raise ValueError("No session - call create_session first")
        
        resp = requests.post(
            f"{self.base_url}/api/v1/sessions/{self.session_id}/messages",
            json={"message": message, "stream": stream}
        )
        resp.raise_for_status()
        
        if stream:
            # Return the raw response for streaming
            return {"stream": True, "response": resp}
        
        return resp.json()
    
    def stream_message(self, message: str) -> str:
        """Send message and stream response token by token."""
        if not self.session_id:
            raise ValueError("No session - call create_session first")
        
        import json
        with requests.post(
            f"{self.base_url}/api/v1/sessions/{self.session_id}/messages",
            json={"message": message, "stream": True},
            stream=True
        ) as resp:
            resp.raise_for_status()
            output = ""
            for line in resp.iter_lines():
                if line:
                    data = line.decode('utf-8')
                    if data.startswith('data: '):
                        try:
                            token_data = json.loads(data[6:])
                            token = token_data.get('token', '')
                            print(token, end=' ', flush=True)
                            output += token + " "
                            if token_data.get('done'):
                                break
                        except:
                            pass
            print()  # newline after stream
            return output
    
    def poll_messages(self) -> List[str]:
        """Poll for messages from the session."""
        if not self.session_id:
            return []
        
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/sessions/{self.session_id}/messages",
                timeout=1
            )
            if resp.status_code == 200:
                return resp.json().get("messages", [])
        except:
            pass
        return []
    
    def list_sessions(self) -> List[Dict]:
        """List running sessions."""
        resp = requests.get(f"{self.base_url}/api/v1/sessions")
        resp.raise_for_status()
        return resp.json().get("sessions", [])
    
    def close_session(self) -> None:
        """Close the current session."""
        if self.session_id:
            try:
                requests.delete(f"{self.base_url}/api/v1/sessions/{self.session_id}")
            except:
                pass
            self.session_id = None


# ============== CONVENIENCE ==============

def get_client() -> RivenClient:
    """Get a Riven client instance."""
    return RivenClient()