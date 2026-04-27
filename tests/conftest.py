"""Pytest fixtures and configuration for riven_core tests."""

import pytest
import os
import sys
from unittest.mock import patch, MagicMock

# Add riven_core to path so tests can import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Disable file context guard for functional tests (they test the editing ops
# directly; open_file is a separate concern they don't exercise).
os.environ.setdefault('RV_FILE__CONTEXT_REQUIRED', 'false')


@pytest.fixture
def mock_session_id():
    """Provide a mock session ID for tests."""
    return "test-session-123"


@pytest.fixture
def mock_memory_api():
    """Mock memory API responses."""
    with patch("modules.planning.requests") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 1,
            "content": "test content",
            "keywords": ["test"],
            "properties": {"status": "active", "priority": "medium", "title": "Test Goal", "files": "[]"}
        }
        mock_req.get.return_value = mock_resp
        mock_req.post.return_value = mock_resp
        mock_req.put.return_value = mock_resp
        yield mock_req


@pytest.fixture
def clean_context():
    """Reset context variables between tests."""
    from modules import _session_id
    _session_id.set("")
    yield
    _session_id.set("")


@pytest.fixture
def mock_config_singleton():
    """Mock the config singleton to avoid file I/O during tests."""
    with patch("config.config") as mock_config:
        mock_config.get.return_value = "http://localhost:8030"
        mock_config.get_all.return_value = {
            "memory_api": {"url": "http://localhost:8030"},
            "tool_timeout": 60.0,
        }
        mock_config._loaded = True
        mock_config._merged = {
            "memory_api": {"url": "http://localhost:8030"},
            "tool_timeout": 60.0,
        }
        yield mock_config
