"""Tests for core.py — the agent loop, Function descriptor, and result types."""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from core import (
    Function,
    FunctionCall,
    FunctionResult,
    Core,
)


class TestFunctionDataclass:
    """Test the Function descriptor (from_callable + properties)."""

    def test_function_basic_attributes(self):
        def my_fn(arg1: str, arg2: int = 5) -> str:
            """Do something."""
            return arg1

        func = Function.from_callable(my_fn)
        assert func.name == "my_fn"
        assert "Do something" in func.description
        assert "arg1" in func.parameters["properties"]
        assert "arg2" in func.parameters["properties"]
        assert "arg1" in func.parameters["required"]

    def test_from_callable_infers_int_type(self):
        def fn(count: int):
            pass

        func = Function.from_callable(fn)
        assert func.parameters["properties"]["count"]["type"] == "integer"

    def test_from_callable_infers_float_type(self):
        def fn(rate: float):
            pass

        func = Function.from_callable(fn)
        assert func.parameters["properties"]["rate"]["type"] == "number"

    def test_from_callable_infers_bool_type(self):
        def fn(verbose: bool):
            pass

        func = Function.from_callable(fn)
        assert func.parameters["properties"]["verbose"]["type"] == "boolean"

    def test_from_callable_uses_first_paragraph_of_docstring(self):
        def fn():
            """
            Short description.

            Long detailed description that should be ignored.
            """
            pass

        func = Function.from_callable(fn)
        assert "Long detailed" not in func.description
        assert "Short description" in func.description

    def test_from_callable_ignores_private_params(self):
        def fn(public: str, _private: str):
            pass

        func = Function.from_callable(fn)
        assert "public" in func.parameters["properties"]
        assert "_private" not in func.parameters["properties"]

    def test_from_callable_default_timeout(self):
        def fn():
            pass

        func = Function.from_callable(fn)
        assert func.timeout == 20.0

    def test_from_callable_custom_timeout(self):
        def fn():
            pass

        func = Function.from_callable(fn, timeout=60.0)
        assert func.timeout == 60.0


class TestFunctionCallDataclass:
    """Test FunctionCall result type."""

    def test_function_call_basic(self):
        call = FunctionCall(id="call_123", name="run", arguments={"command": "ls"})
        assert call.id == "call_123"
        assert call.name == "run"
        assert call.arguments == {"command": "ls"}


class TestFunctionResultDataclass:
    """Test FunctionResult result type."""

    def test_function_result_success(self):
        result = FunctionResult(call_id="call_123", name="run", content="file.txt")
        assert result.call_id == "call_123"
        assert result.name == "run"
        assert result.content == "file.txt"
        assert result.error is None

    def test_function_result_error(self):
        result = FunctionResult(call_id="call_123", name="run", content="", error="Timeout")
        assert result.error == "Timeout"


class TestCoreInit:
    """Test Core.__init__ and basic properties."""

    def test_core_init_extracts_llm_config(self):
        core = Core(
            shard={"modules": [], "system": "You are helpful."},
            llm={"url": "http://localhost:8000/v1", "model": "test-model"},
        )
        assert core._llm_url == "http://localhost:8000/v1"
        assert core._llm_model == "test-model"

    def test_core_init_extracts_shard_settings(self):
        core = Core(
            shard={
                "modules": ["time", "file"],
                "system": "You are helpful.",
                "tool_timeout": 45.0,
                "tool_result_max_lines": 100,
            },
        )
        assert core._module_names == ["time", "file"]
        assert core._tool_timeout == 45.0
        assert core._ctx._tool_max_lines == 100

    def test_core_init_defaults_tool_timeout(self):
        core = Core(shard={"modules": [], "system": "You are helpful."})
        assert core._tool_timeout == 20.0

    def test_core_init_respects_explicit_tool_timeout(self):
        core = Core(
            shard={"modules": [], "system": "You are helpful."},
            tool_timeout=90.0,
        )
        assert core._tool_timeout == 90.0


class TestCoreParseCalls:
    """Test Core._parse_calls tool call extraction."""

    def test_parse_single_tool_call(self):
        core = Core(shard={"modules": [], "system": ""})
        msg = {
            "tool_calls": [
                {
                    "id": "call_abc",
                    "function": {"name": "run", "arguments": '{"command": "ls"}'},
                }
            ]
        }
        calls = core._parse_calls(msg)
        assert len(calls) == 1
        assert calls[0].id == "call_abc"
        assert calls[0].name == "run"
        assert calls[0].arguments == {"command": "ls"}

    def test_parse_multiple_tool_calls(self):
        core = Core(shard={"modules": [], "system": ""})
        msg = {
            "tool_calls": [
                {"id": "call_1", "function": {"name": "run", "arguments": "{}"}},
                {"id": "call_2", "function": {"name": "read", "arguments": "{}"}},
            ]
        }
        calls = core._parse_calls(msg)
        assert len(calls) == 2
        assert calls[0].name == "run"
        assert calls[1].name == "read"

    def test_parse_handles_dict_arguments(self):
        core = Core(shard={"modules": [], "system": ""})
        msg = {
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "read", "arguments": {"path": "main.py"}},
                }
            ]
        }
        calls = core._parse_calls(msg)
        assert calls[0].arguments == {"path": "main.py"}

    def test_parse_empty_tool_calls(self):
        core = Core(shard={"modules": [], "system": ""})
        calls = core._parse_calls({})
        assert calls == []

    def test_parse_none_tool_calls(self):
        core = Core(shard={"modules": [], "system": ""})
        calls = core._parse_calls({"tool_calls": None})
        assert calls == []


class TestCoreGetDB:
    """Test Core._get_db lazy initialization."""

    @patch("core.ContextDB")
    def test_get_db_creates_once(self, mock_db_cls):
        mock_instance = MagicMock()
        mock_db_cls.return_value = mock_instance
        core = Core(shard={"modules": [], "system": ""})
        db1 = core._get_db()
        db2 = core._get_db()
        assert db1 is db2
        assert mock_db_cls.call_count == 1


class TestCoreCancel:
    """Test Core.cancel()."""

    def test_cancel_sets_flag(self):
        core = Core(shard={"modules": [], "system": ""})
        assert core._cancelled is False
        core.cancel()
        assert core._cancelled is True


class TestCoreDiscoverModules:
    """Test Core._discover_modules directory scanning."""

    def test_discover_finds_time_module(self, tmp_path):
        """_discover_modules should resolve time module to its __init__.py."""
        # Create the actual module structure: modules/<name>/__init__.py
        time_init = tmp_path / "modules" / "time" / "__init__.py"
        time_init.parent.mkdir(parents=True)
        time_init.write_text("get_module = lambda: None")

        # Patch _folder_has_get_module to avoid importlib in tests
        core = Core(shard={"modules": [], "system": ""})
        core._module_names = ["time"]
        with patch.object(core, "_folder_has_get_module", return_value=True):
            with patch("core.os.path.dirname", return_value=str(tmp_path)):
                resolved = core._discover_modules()
                assert "time" in resolved

    def test_discover_returns_empty_when_no_modules(self):
        """_discover_modules returns [] when no modules specified."""
        core = Core(shard={"modules": [], "system": ""})
        core._module_names = []
        assert core._discover_modules() == []


class TestCoreGetFunctions:
    """Test Core._get_functions builds Function list from registry."""

    @patch("core.registry")
    def test_get_functions_empty_registry(self, mock_registry):
        mock_registry._modules = {}
        mock_registry.all_modules.return_value = []
        mock_registry._modules = {}

        core = Core(shard={"modules": [], "system": ""})
        funcs = core._get_functions()
        assert funcs == []

    @patch("core.registry")
    def test_get_functions_from_module(self, mock_registry):
        mock_module = MagicMock()
        mock_cf = MagicMock()
        mock_cf.name = "test_fn"
        mock_cf.description = "A test function"
        mock_cf.parameters = {"type": "object", "properties": {}}
        mock_cf.fn = lambda: "result"
        mock_cf.timeout = None
        mock_module.called_fns = [mock_cf]
        mock_registry._modules = {"test_module": mock_module}
        mock_registry.all_modules.return_value = [mock_module]

        core = Core(shard={"modules": [], "system": ""})
        core._tool_timeout = 30.0
        funcs = core._get_functions()
        assert len(funcs) == 1
        assert funcs[0].name == "test_fn"
        assert funcs[0].timeout == 30.0  # uses shard/tool_timeout when cf.timeout is None

    @patch("core.registry")
    def test_get_functions_uses_cf_timeout_when_set(self, mock_registry):
        mock_module = MagicMock()
        mock_cf = MagicMock()
        mock_cf.name = "slow_fn"
        mock_cf.description = ""
        mock_cf.parameters = {"type": "object", "properties": {}}
        mock_cf.fn = lambda: "result"
        mock_cf.timeout = 120.0
        mock_module.called_fns = [mock_cf]
        mock_registry._modules = {"test": mock_module}
        mock_registry.all_modules.return_value = [mock_module]

        core = Core(shard={"modules": [], "system": ""})
        core._tool_timeout = 20.0
        funcs = core._get_functions()
        assert funcs[0].timeout == 120.0  # cf.timeout wins


class TestCoreExecute:
    """Test Core._execute function invocation."""

    @pytest.mark.asyncio
    @patch("core.asyncio.wait_for")
    async def test_execute_success(self, mock_wait_for):
        mock_wait_for.return_value = "hello world"
        core = Core(shard={"modules": [], "system": ""})
        func_index = {"greet": MagicMock(fn=AsyncMock(return_value="hello world"))}
        call = FunctionCall(id="c1", name="greet", arguments={"who": "world"})

        result = await core._execute(call, func_index)

        assert result.content == "hello world"
        assert result.error is None
        assert result.call_id == "c1"

    @pytest.mark.asyncio
    @patch("core.asyncio.wait_for")
    async def test_execute_unknown_function(self, mock_wait_for):
        core = Core(shard={"modules": [], "system": ""})
        func_index = {}
        call = FunctionCall(id="c1", name="unknown_fn", arguments={})

        result = await core._execute(call, func_index)

        assert result.content == ""
        assert "Unknown function" in result.error

    @pytest.mark.asyncio
    @patch("core.asyncio.wait_for")
    async def test_execute_timeout(self, mock_wait_for):
        import asyncio
        mock_wait_for.side_effect = asyncio.TimeoutError()
        # Use a short timeout (0.3s) so polling loop exhausts quickly:
        # 3 iterations × 0.1s chunks = natural timeout triggers on 4th TimeoutError
        core = Core(shard={"modules": [], "system": "", "tool_timeout": 0.3})
        func_index = {"fn": MagicMock(fn=AsyncMock())}
        call = FunctionCall(id="c1", name="fn", arguments={})

        result = await core._execute(call, func_index)

        assert result.content == ""
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    @patch("core.asyncio.wait_for")
    async def test_execute_exception(self, mock_wait_for):
        mock_wait_for.side_effect = ValueError("bad input")
        core = Core(shard={"modules": [], "system": ""})
        func_index = {"fn": MagicMock(fn=AsyncMock())}
        call = FunctionCall(id="c1", name="fn", arguments={})

        result = await core._execute(call, func_index)

        assert result.error == "bad input"


class TestCoreSaveLlmContext:
    """Test Core._save_llm_context snapshot saving."""

    @patch("core.get")
    def test_save_llm_context_skips_when_disabled(self, mock_get):
        """_save_llm_context returns early when debug_snapshots=False."""
        mock_get.return_value = False  # debug_snapshots = False
        core = Core(shard={"modules": [], "system": ""})
        core._llm_model = "test-model"
        core._save_llm_context([{"role": "user", "content": "hello"}], "session-123")
        mock_get.assert_called()

    @patch("core.get")
    def test_save_llm_context_saves_json(self, mock_get, tmp_path):
        """_save_llm_context writes a JSON snapshot when debug_snapshots=True."""
        debug_dir = tmp_path / "debug_logs"
        mock_get.side_effect = lambda k, d=None: {
            "debug_snapshots": True,
            "debug_dir": str(debug_dir),
        }.get(k, d)

        core = Core(shard={"modules": [], "system": ""})
        core._llm_model = "test-model"
        core._save_llm_context([{"role": "user", "content": "hello"}], "session-abc")

        assert debug_dir.exists()
        # Filename is: YYYY-MM-DD_HH-MM-SS_<16-char-truncated-session>.json
        saved = list(debug_dir.glob("*_session-abc.json"))
        assert len(saved) == 1, f"Expected 1 file matching '*_session-abc.json', got {saved}"
        data = json.loads(saved[0].read_text())
        assert data["model"] == "test-model"
        assert data["session_id"] == "session-abc"
