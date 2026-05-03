"""Tests for config.py — loading, precedence, env override, get_llm_config."""

import os
import pytest
from unittest.mock import patch, MagicMock

# Reset config singleton between tests
@pytest.fixture(autouse=True)
def clean_config():
    """Fresh config state for each test."""
    import config as cfg_module
    cfg_module.config._loaded = False
    cfg_module.config._merged = {}
    cfg_module.config._search_paths = []
    cfg_module._project_root_cache.clear()
    yield
    cfg_module.config._loaded = False
    cfg_module.config._merged = {}
    cfg_module.config._search_paths = []
    cfg_module._project_root_cache.clear()


class TestCoerce:
    """Test _coerce type conversions."""

    def test_coerce_true_values(self):
        from config import _coerce
        for val in ("true", "True", "yes", "YES", "1"):
            assert _coerce(val) is True

    def test_coerce_false_values(self):
        from config import _coerce
        for val in ("false", "False", "no", "NO", "0"):
            assert _coerce(val) is False

    def test_coerce_int(self):
        from config import _coerce
        assert _coerce("42") == 42
        assert _coerce("-7") == -7

    def test_coerce_float(self):
        from config import _coerce
        assert _coerce("3.14") == 3.14
        assert _coerce("-0.5") == -0.5

    def test_coerce_string_fallback(self):
        from config import _coerce
        assert _coerce("hello world") == "hello world"
        assert _coerce("") == ""


class TestDeepMerge:
    """Test _deep_merge."""

    def test_deep_merge_shallow(self):
        from config import _deep_merge
        base = {"a": 1, "b": 2}
        override = {"b": 99, "c": 3}
        result = _deep_merge(base, override)
        assert result["a"] == 1
        assert result["b"] == 99
        assert result["c"] == 3

    def test_deep_merge_nested(self):
        from config import _deep_merge
        base = {"llm": {"model": "old", "timeout": 60}}
        override = {"llm": {"model": "new"}}
        result = _deep_merge(base, override)
        assert result["llm"]["model"] == "new"
        assert result["llm"]["timeout"] == 60  # preserved

    def test_deep_merge_replaces_non_dict(self):
        from config import _deep_merge
        base = {"key": "string"}
        override = {"key": {"nested": True}}
        result = _deep_merge(base, override)
        assert result["key"] == {"nested": True}


class TestGetViaEnv:
    """Test _get_via_env."""

    def test_get_via_env_matches_dotted_key(self):
        from config import _get_via_env
        with patch.dict(os.environ, {"RV_LLM__MODEL": "gpt-4"}):
            result = _get_via_env("llm.model")
            assert result == "gpt-4"

    def test_get_via_env_nested(self):
        from config import _get_via_env
        with patch.dict(os.environ, {"RV_TOOL_TIMEOUT": "30"}):
            result = _get_via_env("tool_timeout")
            assert result == 30

    def test_get_via_env_not_found(self):
        from config import _get_via_env
        result = _get_via_env("nonexistent.key")
        assert result is None


class TestEnvOverride:
    """Test _env_override with realistic precedence scenarios."""

    def test_env_override_basic(self):
        from config import _env_override
        data = {"llm": {"model": "MiniMax-M2.7", "timeout": 120}}
        with patch.dict(os.environ, {"RV_LLM__MODEL": "gpt-5"}):
            result = _env_override(data)
            assert result["llm"]["model"] == "gpt-5"
            assert result["llm"]["timeout"] == 120

    def test_env_override_nested_double_underscore(self):
        from config import _env_override
        data = {"memory": {"api": {"url": "http://old"}}}
        with patch.dict(os.environ, {"RV_MEMORY__API__URL": "http://new"}):
            result = _env_override(data)
            assert result["memory"]["api"]["url"] == "http://new"

    def test_env_override_creates_missing_keys(self):
        from config import _env_override
        data = {}
        with patch.dict(os.environ, {"RV_NEW__SECTION__KEY": "value"}):
            result = _env_override(data)
            assert result["new"]["section"]["key"] == "value"

    def test_env_override_bool_coercion(self):
        from config import _env_override
        data = {"debug": True}
        with patch.dict(os.environ, {"RV_DEBUG": "false"}):
            result = _env_override(data)
            assert result["debug"] is False

    def test_env_override_int_coercion(self):
        from config import _env_override
        data = {"timeout": 60}
        with patch.dict(os.environ, {"RV_TIMEOUT": "90"}):
            result = _env_override(data)
            assert result["timeout"] == 90


class TestConfigSingleton:
    """Test _Config class."""

    @patch("config._load_yaml")
    @patch("config._find_project_root")
    def test_register_adds_paths(self, mock_root, mock_load):
        from config import _Config
        mock_root.return_value = "/fake"
        c = _Config()
        c.register("config.yaml")
        assert "/fake/config.yaml" in c._search_paths

    @patch("config._load_yaml")
    def test_load_sets_loaded_flag(self, mock_load):
        from config import _Config
        mock_load.return_value = {"key": "val"}
        c = _Config()
        c.register("config.yaml")
        c.load()
        assert c._loaded is True

    @patch("config._load_yaml")
    def test_load_idempotent(self, mock_load):
        from config import _Config
        mock_load.return_value = {"key": "val"}
        c = _Config()
        c.register("config.yaml")
        c.load()
        c.load()  # second call should be no-op
        assert mock_load.call_count == 1

    @patch("config._load_yaml")
    def test_get_returns_loaded_value(self, mock_load):
        from config import _Config
        mock_load.return_value = {"model": "gpt-4"}
        c = _Config()
        c.register("config.yaml")
        assert c.get("model") == "gpt-4"

    @patch("config._load_yaml")
    def test_get_with_default(self, mock_load):
        from config import _Config
        mock_load.return_value = {}
        c = _Config()
        c.register("config.yaml")
        assert c.get("missing", "default_val") == "default_val"

    @patch("config._load_yaml")
    def test_get_deep_key(self, mock_load):
        from config import _Config
        mock_load.return_value = {"llm": {"model": "gpt-4"}}
        c = _Config()
        c.register("config.yaml")
        assert c.get("llm.model") == "gpt-4"

    @patch("config._load_yaml")
    def test_get_all_returns_copy(self, mock_load):
        from config import _Config
        mock_load.return_value = {"key": "val"}
        c = _Config()
        c.register("config.yaml")
        all_cfg = c.get_all()
        all_cfg["key"] = "mutated"
        assert c._merged["key"] == "val"  # original not mutated

    @patch("config._load_yaml")
    def test_reload_resets_and_reloads(self, mock_load):
        from config import _Config
        mock_load.return_value = {"version": 1}
        c = _Config()
        c.register("config.yaml")
        c.load()
        assert c.get("version") == 1

        mock_load.return_value = {"version": 2}
        c.reload()
        assert c.get("version") == 2

    def test_get_via_env_wins_over_yaml(self):
        """Env var should override loaded YAML values."""
        import config as cfg_module
        with patch("config._load_yaml", return_value={"model": "yaml-model"}):
            with patch.dict(os.environ, {"RV_MODEL": "env-model"}):
                cfg_module.config.register("config.yaml")
                cfg_module.config.load()
                assert cfg_module.config.get("model") == "env-model"


class TestGetLlMConfig:
    """Test get_llm_config convenience function."""

    def test_get_llm_config_returns_dict(self):
        """get_llm_config returns a merged dict with url and model from config."""
        import config as cfg_module
        # Reset state
        cfg_module.config._loaded = True
        cfg_module.config._merged = {
            "llm": {
                "primary": {
                    "url": "http://localhost:8000/v1",
                    "model": "test-model",
                }
            }
        }

        result = cfg_module.get_llm_config("primary")
        assert isinstance(result, dict)
        assert result["url"] == "http://localhost:8000/v1"
        assert result["model"] == "test-model"

    @patch("config._load_yaml")
    def test_get_llm_config_missing_url_raises(self, mock_load):
        import config as cfg_module
        cfg_module.config._loaded = True
        cfg_module.config._merged = {"llm": {"primary": {"model": "test"}}}
        with pytest.raises(ValueError, match="missing 'url'"):
            cfg_module.get_llm_config("primary")

    @patch("config._load_yaml")
    def test_get_llm_config_sets_defaults(self, mock_load):
        import config as cfg_module
        cfg_module.config._loaded = True
        cfg_module.config._merged = {
            "llm": {"primary": {"url": "http://localhost:8000/v1"}}
        }
        result = cfg_module.get_llm_config("primary")
        assert result["model"] == "MiniMax-M2.7"
        assert result["api_key"] == "sk-dummy"
        assert result["timeout"] == 120

    @patch("config._load_yaml")
    def test_get_llm_config_env_override(self, mock_load):
        import config as cfg_module
        cfg_module.config._loaded = True
        cfg_module.config._merged = {
            "llm": {"primary": {"url": "http://localhost:8000/v1", "model": "yaml-model"}}
        }
        with patch.dict(os.environ, {"RV_LLM__PRIMARY__MODEL": "env-model"}):
            result = cfg_module.get_llm_config("primary")
            assert result["model"] == "env-model"


class TestFindProjectRoot:
    """Test find_project_root discovery logic."""

    def test_cache_returns_same_result(self):
        from config import find_project_root, clear_project_root_cache
        clear_project_root_cache()
        with patch("config._git_toplevel", return_value=None):
            with patch("config.os.path.isdir", return_value=False):
                result1 = find_project_root("/some/path")
                result2 = find_project_root("/some/path")
                assert result1 == result2

    def test_env_var_override(self, tmp_path):
        from config import find_project_root, clear_project_root_cache
        clear_project_root_cache()
        with patch.dict(os.environ, {"RV_PROJECT_ROOT": str(tmp_path)}):
            result = find_project_root("/some/path")
            assert result == str(tmp_path)

    def test_returns_none_when_no_git_no_riven(self):
        from config import find_project_root, clear_project_root_cache
        clear_project_root_cache()
        with patch("config._git_toplevel", return_value=None):
            with patch("config.os.path.isdir", return_value=False):
                result = find_project_root("/some/path")
                assert result is None
