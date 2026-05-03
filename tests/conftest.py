"""Pytest fixtures and configuration for riven_core tests."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

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
def mock_memory_utils():
    """Mock the file module's self-contained DB wrapper.
    
    Provides the DB operations that file/editor.py expects:
    set_open_file, get_open_files, delete_open_file,
    add_file_change, get_file_changes.
    """
    mock = MagicMock()
    mock.set_open_file = MagicMock(return_value=True)
    mock.get_open_files = MagicMock(return_value=[])
    mock.delete_open_file = MagicMock(return_value=True)
    mock.delete_open_file_by_path = MagicMock(return_value=0)
    mock.delete_all_open_files = MagicMock(return_value=0)
    mock.get_open_file_by_keyword = MagicMock(return_value=None)
    mock.add_file_change = MagicMock(return_value=True)
    mock.get_file_changes = MagicMock(return_value=[])
    return mock


@pytest.fixture(autouse=True)
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
        mock_config.get.return_value = None
        mock_config.get_all.return_value = {
            "tool_timeout": 60.0,
        }
        mock_config._loaded = True
        mock_config._merged = {
            "tool_timeout": 60.0,
        }
        yield mock_config



