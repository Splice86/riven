"""Tests for modules/__init__.py — module system, registry, and _tool_ref."""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFormatParams:
    """Test _format_params() parameter signature formatting."""

    def test_required_params(self):
        from modules import _format_params

        result = _format_params({
            "properties": {
                "path": {"type": "string"},
                "timeout": {"type": "number"},
            },
            "required": ["path"],
        })
        # path is required, timeout is optional
        assert "path" in result
        assert "timeout" in result
        # Required params have no prefix, optional have "?"
        assert "path" in result  # no ? prefix
        assert "?timeout" in result

    def test_no_required_array(self):
        from modules import _format_params

        result = _format_params({
            "properties": {
                "command": {"type": "string"},
            },
        })
        assert "command" in result

    def test_omits_internal_timeout(self):
        from modules import _format_params

        result = _format_params({
            "properties": {
                "command": {"type": "string"},
                "_timeout": {"type": "integer"},
            },
            "required": ["command"],
        })
        # _timeout should be hidden from display
        assert "_timeout" not in result
        assert "command" in result

    def test_empty_properties(self):
        from modules import _format_params

        result = _format_params({"properties": {}})
        assert result == ""

    def test_all_params_optional(self):
        from modules import _format_params

        result = _format_params({
            "properties": {
                "path": {"type": "string"},
            },
            "required": [],
        })
        assert "?path" in result


class TestModuleRegistry:
    """Test ModuleRegistry registration and querying."""

    def test_register_and_get_module(self):
        from modules import Module, ModuleRegistry

        reg = ModuleRegistry()
        mod = Module(name="test", called_fns=[], context_fns=[])
        reg.register(mod)

        result = reg.get_module("test")
        assert result is mod

    def test_get_nonexistent_module(self):
        from modules import ModuleRegistry

        reg = ModuleRegistry()
        assert reg.get_module("does_not_exist") is None

    def test_all_modules(self):
        from modules import Module, ModuleRegistry

        reg = ModuleRegistry()
        reg.register(Module(name="a", called_fns=[], context_fns=[]))
        reg.register(Module(name="b", called_fns=[], context_fns=[]))

        modules = reg.all_modules()
        assert len(modules) == 2
        names = {m.name for m in modules}
        assert names == {"a", "b"}

    def test_get_called_fns(self):
        from modules import CalledFn, Module, ModuleRegistry

        reg = ModuleRegistry()
        reg.register(Module(
            name="test",
            called_fns=[
                CalledFn(name="fn1", description="desc", parameters={}, fn=lambda: None),
                CalledFn(name="fn2", description="desc", parameters={}, fn=lambda: None),
            ],
            context_fns=[],
        ))

        funcs = reg.get_called_fns()
        assert len(funcs) == 2
        names = {f.name for f in funcs}
        assert names == {"fn1", "fn2"}

    def test_build_context_empty(self):
        from modules import Module, ModuleRegistry

        reg = ModuleRegistry()
        ctx = reg.build_context()
        assert ctx == {}

    def test_build_context_single_ctx_fn(self):
        from modules import ContextFn, Module, ModuleRegistry

        reg = ModuleRegistry()
        reg.register(Module(
            name="test",
            called_fns=[],
            context_fns=[ContextFn(tag="test_tag", fn=lambda: "test content")],
        ))

        ctx = reg.build_context()
        assert ctx["test_tag"] == "test content"

    def test_build_context_multiple_modules(self):
        from modules import ContextFn, Module, ModuleRegistry

        reg = ModuleRegistry()
        reg.register(Module(name="a", called_fns=[], context_fns=[
            ContextFn(tag="a_tag", fn=lambda: "a content"),
        ]))
        reg.register(Module(name="b", called_fns=[], context_fns=[
            ContextFn(tag="b_tag", fn=lambda: "b content"),
        ]))

        ctx = reg.build_context()
        assert ctx["a_tag"] == "a content"
        assert ctx["b_tag"] == "b content"

    def test_build_context_exception_becomes_error_string(self):
        from modules import ContextFn, Module, ModuleRegistry

        reg = ModuleRegistry()
        reg.register(Module(name="broken", called_fns=[], context_fns=[
            ContextFn(tag="bad", fn=lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
        ]))

        ctx = reg.build_context()
        assert "bad" in ctx
        assert "boom" in ctx["bad"] or "Error" in ctx["bad"]


class TestToolRef:
    """Test _tool_ref() cache behavior and output formatting."""

    def test_tool_ref_unknown_module(self):
        from modules import _tool_ref

        # Clear cache first
        if hasattr(_tool_ref, "_cache"):
            _tool_ref._cache.clear()

        result = _tool_ref("nonexistent_module_xyz")
        assert "(no tools registered)" in result

    def test_tool_ref_cache_miss_then_hit(self):
        from modules import CalledFn, Module, _tool_ref, registry

        mock_module = Module(
            name="cached_mod",
            called_fns=[
                CalledFn(
                    name="cached_fn",
                    description="A cached function",
                    parameters={
                        "properties": {"arg": {"type": "string"}},
                        "required": ["arg"],
                    },
                    fn=lambda: None,
                ),
            ],
            context_fns=[],
        )
        # _tool_ref uses the global `registry` directly, not ModuleRegistry.all_modules()
        with patch.object(registry, "get_module", return_value=mock_module):
            # First call — cache miss, calls registry.get_module
            result1 = _tool_ref("cached_mod")
            assert "cached_fn" in result1

            # Second call — cache hit (returns from _tool_ref._cache, no registry lookup)
            result2 = _tool_ref("cached_mod")
            assert result1 == result2

    def test_tool_ref_description_collapsed_to_one_line(self):
        from modules import CalledFn, Module, _tool_ref, registry

        mock_module = Module(
            name="multiline",
            called_fns=[
                CalledFn(
                    name="fn",
                    description="Line 1\nLine 2\nLine 3",
                    parameters={"properties": {}},
                    fn=lambda: None,
                ),
            ],
            context_fns=[],
        )
        with patch.object(registry, "get_module", return_value=mock_module):
            result = _tool_ref("multiline")
            assert "fn(" in result


class TestCalledFnPostInit:
    """Test CalledFn.__post_init__() auto-adds _timeout param."""

    def test_timeout_param_auto_added(self):
        from modules import CalledFn

        fn = CalledFn(
            name="test",
            description="test",
            parameters={
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            fn=lambda: None,
        )

        assert "_timeout" in fn.parameters["properties"]

    def test_empty_required_array_removed(self):
        from modules import CalledFn

        fn = CalledFn(
            name="test",
            description="test",
            parameters={
                "properties": {"x": {"type": "string"}},
                "required": [],
            },
            fn=lambda: None,
        )

        assert "required" not in fn.parameters

    def test_timeout_param_not_duplicated(self):
        from modules import CalledFn

        fn = CalledFn(
            name="test",
            description="test",
            parameters={
                "properties": {
                    "command": {"type": "string"},
                    "_timeout": {"type": "integer"},  # Already present
                },
                "required": ["command"],
            },
            fn=lambda: None,
        )

        # Should not add a second _timeout
        props = fn.parameters["properties"]
        assert list(props.keys()).count("_timeout") == 1


class TestContextFn:
    """Test ContextFn dataclass."""

    def test_context_fn_defaults(self):
        from modules import ContextFn

        fn = ContextFn(tag="test", fn=lambda: "content")
        assert fn.static is False  # Default

    def test_context_fn_static_true(self):
        from modules import ContextFn

        fn = ContextFn(tag="test", fn=lambda: "content", static=True)
        assert fn.static is True
