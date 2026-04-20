"""Tests for the memory_utils module."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSearchMemories:
    """Test _search_memories utility function."""

    def test_search_returns_memories_on_success(self):
        """Test that search returns memories list on successful API call."""
        with patch("modules.memory_utils.requests") as mock_requests:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"memories": [{"id": 1}, {"id": 2}]}
            mock_requests.post.return_value = mock_resp

            from modules.memory_utils import _search_memories
            results = _search_memories("test-session", "k:file", limit=10)

            assert results == [{"id": 1}, {"id": 2}]
            mock_requests.post.assert_called_once()
            call_kwargs = mock_requests.post.call_args[1]
            assert call_kwargs["json"]["query"] == "k:test-session AND k:file"
            assert call_kwargs["json"]["limit"] == 10

    def test_search_returns_empty_on_api_error(self):
        """Test that search returns empty list on API error."""
        with patch("modules.memory_utils.requests") as mock_requests:
            mock_requests.post.side_effect = Exception("Connection refused")

            from modules.memory_utils import _search_memories
            results = _search_memories("test-session", "k:file", limit=10)

            assert results == []

    def test_search_returns_empty_on_bad_status(self):
        """Test that search returns empty list when API returns non-200."""
        with patch("modules.memory_utils.requests") as mock_requests:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_requests.post.return_value = mock_resp

            from modules.memory_utils import _search_memories
            results = _search_memories("test-session", "k:file", limit=10)

            assert results == []


class TestDeleteMemory:
    """Test _delete_memory utility function."""

    def test_delete_sends_correct_request(self):
        """Test that delete sends a DELETE request to the correct URL."""
        with patch("modules.memory_utils.requests") as mock_requests, \
             patch("modules.memory_utils.MEMORY_API_URL", "http://localhost:8030"):
            mock_requests.delete.return_value = MagicMock(status_code=200)

            from modules.memory_utils import _delete_memory
            _delete_memory("42")

            mock_requests.delete.assert_called_once_with(
                f"http://localhost:8030/memories/42",
                timeout=5
            )

    def test_delete_swallows_exceptions(self):
        """Test that delete silently handles errors (API contract)."""
        with patch("modules.memory_utils.requests") as mock_requests:
            mock_requests.delete.side_effect = Exception("Connection refused")

            from modules.memory_utils import _delete_memory
            # Should not raise
            _delete_memory("42")


class TestMemoryUtilsExports:
    """Test that memory_utils exports the correct functions."""

    def test_module_exports_search_and_delete(self):
        """Verify module exposes the expected functions."""
        from modules import memory_utils
        
        assert hasattr(memory_utils, '_search_memories')
        assert hasattr(memory_utils, '_delete_memory')
        assert hasattr(memory_utils, 'MEMORY_API_URL')
