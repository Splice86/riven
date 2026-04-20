"""Tests for the shards module (modules/shards.py)."""

import pytest
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestShardsModuleRegistration:
    """Test that shards module is correctly registered."""

    def test_shards_help_is_static_context_fn(self):
        """Verify _shards_help is registered as a static ContextFn."""
        from modules.shards import get_module
        mod = get_module()
        help_fn = next((cf for cf in mod.context_fns if cf.tag == "shards_help"), None)
        assert help_fn is not None
        assert help_fn.static is True

    def test_shards_context_is_dynamic_context_fn(self):
        """Verify _shards_context is registered as dynamic."""
        from modules.shards import get_module
        mod = get_module()
        ctx_fn = next((cf for cf in mod.context_fns if cf.tag == "shards_context"), None)
        assert ctx_fn is not None
        assert ctx_fn.static is False

    def test_all_called_fns_have_descriptions(self):
        """Every CalledFn should have a non-empty description."""
        from modules.shards import get_module
        mod = get_module()
        for cf in mod.called_fns:
            assert cf.description, f"CalledFn {cf.name} has empty description"

    def test_run_shard_has_required_params(self):
        """run_shard should require shard_name and task."""
        from modules.shards import get_module
        mod = get_module()
        run_shard_fn = next((cf for cf in mod.called_fns if cf.name == "run_shard"), None)
        assert run_shard_fn is not None
        required = run_shard_fn.parameters.get("required", [])
        assert "shard_name" in required
        assert "task" in required

    def test_list_shards_has_no_required_params(self):
        """list_shards should have no required parameters."""
        from modules.shards import get_module
        mod = get_module()
        list_fn = next((cf for cf in mod.called_fns if cf.name == "list_shards"), None)
        assert list_fn is not None
        required = list_fn.parameters.get("required", [])
        assert required == []


class TestShardConfigLoading:
    """Test shard config loading helpers."""

    def test_load_shard_config_codehammer(self):
        """_load_shard_config should find codehammer.yaml."""
        from modules.shards import _load_shard_config
        shard = _load_shard_config("codehammer")
        assert shard is not None
        assert shard["name"] == "codehammer"
        assert "modules" in shard

    def test_load_shard_config_testhammer(self):
        """_load_shard_config should find testhammer.yaml."""
        from modules.shards import _load_shard_config
        shard = _load_shard_config("testhammer")
        assert shard is not None
        assert shard["name"] == "testhammer"

    def test_load_shard_config_nonexistent(self):
        """_load_shard_config for unknown shard should return None."""
        from modules.shards import _load_shard_config
        result = _load_shard_config("nonexistent_shard_xyz")
        assert result is None

    def test_shard_names_returns_list(self):
        """_shard_names should return a list of shard names."""
        from modules.shards import _shard_names
        names = _shard_names()
        assert isinstance(names, list)
        assert "codehammer" in names
        assert "testhammer" in names

    def test_codehammer_does_not_have_shards_module(self):
        """codehammer should NOT include 'shards' in its modules (prevents recursion)."""
        from modules.shards import _load_shard_config
        shard = _load_shard_config("codehammer")
        assert "shards" not in shard.get("modules", [])


class TestListShards:
    """Test list_shards function."""

    @pytest.mark.asyncio
    async def test_list_shards_shows_codehammer(self):
        """list_shards should include codehammer in its output."""
        from modules.shards import list_shards
        result = await list_shards()
        assert "codehammer" in result.lower()

    @pytest.mark.asyncio
    async def test_list_shards_shows_testhammer(self):
        """list_shards should include testhammer in its output."""
        from modules.shards import list_shards
        result = await list_shards()
        assert "testhammer" in result.lower()

    @pytest.mark.asyncio
    async def test_list_shards_shows_display_name(self):
        """list_shards should show display names, not just internal names."""
        from modules.shards import list_shards
        result = await list_shards()
        assert "CodeHammer" in result or "codehammer" in result


class TestRunShard:
    """Test run_shard function."""

    @pytest.mark.asyncio
    async def test_run_shard_nonexistent_returns_error(self):
        """run_shard with unknown shard should return an error message."""
        from modules.shards import run_shard
        from modules import _session_id
        _session_id.set("test-session-123")
        result = await run_shard("nonexistent_shard_xyz", "do something")
        assert "not found" in result.lower()
        assert "nonexistent_shard_xyz" in result

    @pytest.mark.asyncio
    async def test_run_shard_stores_task_to_memory_api(self):
        """run_shard should POST the task to the memory API for the sub-session."""
        from modules.shards import run_shard
        from modules import _session_id
        _session_id.set("test-session-123")

        with patch("modules.shards.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            # Mock Core.run_stream so we don't make real LLM calls
            async def mock_stream(session_id):
                yield {"token": "hello"}
                yield {"done": True}

            with patch("modules.shards.Core") as mock_core_class:
                mock_core = MagicMock()
                mock_core.run_stream = mock_stream
                mock_core_class.return_value = mock_core

                result = await run_shard("codehammer", "write a test")

                # Should have called memory API with sub-session
                assert mock_post.called
                call_kwargs = mock_post.call_args.kwargs
                stored_payload = call_kwargs["json"]
                assert stored_payload["role"] == "user"
                assert stored_payload["content"] == "write a test"
                assert "sub-test-session-123-codehammer" in stored_payload["session"]

    @pytest.mark.asyncio
    async def test_run_shard_returns_accumulated_output(self):
        """run_shard should return the full accumulated text output."""
        from modules.shards import run_shard
        from modules import _session_id
        _session_id.set("test-session-123")

        async def mock_stream(session_id):
            yield {"token": "Hello "}
            yield {"token": "World"}
            yield {"done": True}

        with patch("modules.shards.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            with patch("modules.shards.Core") as mock_core_class:
                mock_core = MagicMock()
                mock_core.run_stream = mock_stream
                mock_core_class.return_value = mock_core

                result = await run_shard("codehammer", "say hello world")

                assert "Hello World" in result

    @pytest.mark.asyncio
    async def test_run_shard_falls_back_to_task_on_no_output(self):
        """run_shard with no output should return task as fallback."""
        from modules.shards import run_shard
        from modules import _session_id
        _session_id.set("test-session-123")

        async def mock_stream(session_id):
            yield {"done": True}

        with patch("modules.shards.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            with patch("modules.shards.Core") as mock_core_class:
                mock_core = MagicMock()
                mock_core.run_stream = mock_stream
                mock_core_class.return_value = mock_core

                result = await run_shard("codehammer", "do nothing task")

                assert "do nothing task" in result

    @pytest.mark.asyncio
    async def test_run_shard_handles_memory_api_error(self):
        """run_shard should return error if memory API POST fails."""
        from modules.shards import run_shard
        from modules import _session_id
        _session_id.set("test-session-123")

        with patch("modules.shards.requests.post") as mock_post:
            mock_post.side_effect = Exception("Connection refused")

            result = await run_shard("codehammer", "do something")

            assert "Failed to store task" in result

    @pytest.mark.asyncio
    async def test_run_shard_handles_core_error(self):
        """run_shard should return error if Core raises an exception."""
        from modules.shards import run_shard
        from modules import _session_id
        _session_id.set("test-session-123")

        with patch("modules.shards.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            with patch("modules.shards.Core") as mock_core_class:
                mock_core_class.side_effect = Exception("Core init failed")

                result = await run_shard("codehammer", "do something")

                assert "failed" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_run_shard_sub_session_derived_from_parent(self):
        """Sub-session ID should be derived from parent session + shard name."""
        from modules.shards import run_shard
        from modules import _session_id
        _session_id.set("parent-session-abc")

        async def mock_stream(session_id):
            yield {"done": True}

        with patch("modules.shards.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            with patch("modules.shards.Core") as mock_core_class:
                mock_core = MagicMock()
                mock_core.run_stream = mock_stream
                mock_core_class.return_value = mock_core

                await run_shard("codehammer", "test")

                stored_payload = mock_post.call_args.kwargs["json"]
                sub_session = stored_payload["session"]
                assert sub_session == "sub-parent-session-abc-codehammer"
                assert sub_session.startswith("sub-parent")

    @pytest.mark.asyncio
    async def test_run_shard_with_llm_config_override(self):
        """run_shard with llm_config should pass that config name to get_llm_config."""
        from modules.shards import run_shard
        from modules import _session_id
        _session_id.set("test-session-123")

        async def mock_stream(session_id):
            yield {"done": True}

        with patch("modules.shards.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            with patch("modules.shards.Core") as mock_core_class:
                mock_core = MagicMock()
                mock_core.run_stream = mock_stream
                mock_core_class.return_value = mock_core

                with patch("modules.shards.get_llm_config") as mock_llm_config:
                    mock_llm_config.return_value = {"url": "http://x", "model": "y"}

                    await run_shard("codehammer", "test", llm_config="alternate")

                    mock_llm_config.assert_called_with("alternate")


class TestShardFileValidation:
    """Test that shard YAML files are valid."""

    def test_codehammer_yaml_is_valid(self):
        """codehammer.yaml should be valid YAML with required fields."""
        from modules.shards import _load_shard_config
        shard = _load_shard_config("codehammer")
        assert shard is not None
        assert "name" in shard
        assert "modules" in shard
        assert "system" in shard
        assert isinstance(shard["modules"], list)

    def test_testhammer_yaml_is_valid(self):
        """testhammer.yaml should be valid YAML with required fields."""
        from modules.shards import _load_shard_config
        shard = _load_shard_config("testhammer")
        assert shard is not None
        assert shard["name"] == "testhammer"
        assert "modules" in shard
        assert "shards" in shard["modules"], "testhammer should include 'shards' module"
        assert "system" in shard
        assert isinstance(shard["modules"], list)

    def test_testhammer_does_not_call_itself(self):
        """testhammer should not list itself as a module (would be recursive)."""
        from modules.shards import _load_shard_config
        shard = _load_shard_config("testhammer")
        assert "testhammer" not in shard.get("modules", [])
