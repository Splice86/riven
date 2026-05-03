"""Extended tests for context.py — error paths and edge cases."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# _json_safe()
# =============================================================================

class TestJsonSafe:
    """Test _json_safe() type conversion."""

    def test_none(self):
        from context import _json_safe
        assert _json_safe(None) is None

    def test_primitives_pass_through(self):
        from context import _json_safe

        assert _json_safe("hello") == "hello"
        assert _json_safe(42) == 42
        assert _json_safe(3.14) == 3.14
        assert _json_safe(True) is True

    def test_list_recursive(self):
        from context import _json_safe
        result = _json_safe(["a", 1, True])
        assert result == ["a", 1, True]

    def test_dict_recursive(self):
        from context import _json_safe
        result = _json_safe({"key": "value", "num": 123})
        assert result == {"key": "value", "num": 123}

    def test_pydantic_undefined(self):
        from context import _json_safe

        try:
            from pydantic import Undefined
            assert _json_safe(Undefined) is None
        except ImportError:
            pytest.skip("pydantic not available")

    def test_pydantic_model_dump(self):
        from context import _json_safe

        class FakeModel:
            def model_dump(self):
                return {"field": "value"}

        assert _json_safe(FakeModel()) == {"field": "value"}

    def test_fallback_to_str(self):
        from context import _json_safe

        # Use __slots__ to suppress __dict__ so we hit the str() fallback
        class WeirdObject:
            __slots__ = []
            def __str__(self):
                return "its a weird object"

        assert _json_safe(WeirdObject()) == "its a weird object"


# =============================================================================
# ContextManager — build_context_from_modules
# =============================================================================

class TestBuildContextFromModules:
    """Test build_context_from_modules() registry integration."""

    def test_passes_registry_to_build_context(self):
        from context import ContextManager

        ctx = ContextManager()
        mock_registry = MagicMock()
        mock_registry.build_context.return_value = {"tag1": "content1"}

        result = ctx.build_context_from_modules(mock_registry)

        assert result == {"tag1": "content1"}
        mock_registry.build_context.assert_called_once()


# =============================================================================
# ContextManager — reorder_messages (tool_calls parsing from content)
# =============================================================================

class TestReorderMessages:
    """Test message reordering and embedded tool_calls parsing."""

    def test_empty_list(self):
        from context import ContextManager
        assert ContextManager.reorder_messages([]) == []

    def test_no_tool_messages(self):
        from context import ContextManager
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = ContextManager.reorder_messages(msgs)
        assert len(result) == 2

    def test_parse_embedded_tool_calls(self):
        from context import ContextManager

        tool_calls = [{"id": "call_123", "function": {"name": "read_file", "arguments": "{}"}}]
        msgs = [
            {
                "role": "assistant",
                "content": "Let me read that file.[tool_calls]" + json.dumps(tool_calls) + "[/tool_calls]",
            },
            {"role": "tool", "tool_call_id": "call_123", "content": "file contents"},
        ]

        result = ContextManager.reorder_messages(msgs)

        # Should extract tool_calls into the message dict
        assistant = result[0]
        assert "tool_calls" in assistant
        assert assistant["tool_calls"][0]["id"] == "call_123"
        # Should strip the [tool_calls]...[/tool_calls] from content
        assert "[tool_calls]" not in assistant["content"]

    def test_parse_embedded_tool_calls_json_decode_error(self):
        """JSON parse failure should leave content intact."""
        from context import ContextManager

        msgs = [
            {
                "role": "assistant",
                "content": "[tool_calls]not valid json[/tool_calls] regular content",
            },
        ]

        result = ContextManager.reorder_messages(msgs)
        # Content should remain unchanged (parsing failed gracefully)
        assert "[tool_calls]" in result[0]["content"]

    def test_tool_result_without_tool_call_id_appended(self):
        """Tool message without tool_call_id should be appended at end."""
        from context import ContextManager

        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "result without id"},  # no tool_call_id
        ]

        result = ContextManager.reorder_messages(msgs)
        # Should append at end (no matching possible)
        assert result[-1]["content"] == "result without id"

    def test_tool_result_matched_to_assistant(self):
        """Tool result with matching tool_call_id should be inserted after assistant."""
        from context import ContextManager

        msgs = [
            {"role": "assistant", "tool_calls": [{"id": "call_abc"}]},
            {"role": "user", "content": "something"},
            {"role": "tool", "tool_call_id": "call_abc", "content": "tool result"},
        ]

        result = ContextManager.reorder_messages(msgs)

        # Tool result should be inserted right after the matching assistant message
        tool_result_idx = next(i for i, m in enumerate(result) if m["role"] == "tool")
        assistant_idx = next(i for i, m in enumerate(result) if m["role"] == "assistant")
        assert tool_result_idx == assistant_idx + 1

    def test_tool_result_with_empty_content_after_parse(self):
        """Assistant message with tool_calls but empty content after parsing should stay."""
        from context import ContextManager

        tool_calls = [{"id": "call_x", "function": {"name": "test", "arguments": "{}"}}]
        msgs = [
            {
                "role": "assistant",
                "content": "[tool_calls]" + json.dumps(tool_calls) + "[/tool_calls]",
            },
            {"role": "tool", "tool_call_id": "call_x", "content": "result"},
        ]

        result = ContextManager.reorder_messages(msgs)
        # Content should be empty string, not deleted — MiniMax needs the field
        assert "content" in result[0]


# =============================================================================
# ContextManager — truncate_tool_result
# =============================================================================

class TestTruncateToolResult:
    """Test tool result truncation logic."""

    def test_empty_content(self):
        from context import ContextManager
        result = ContextManager.truncate_tool_result("", 200, 150)
        assert result == ""

    def test_short_content_unchanged(self):
        from context import ContextManager
        content = "short\ncontent"
        result = ContextManager.truncate_tool_result(content, 200, 150)
        assert result == content

    def test_truncate_multiline(self):
        from context import ContextManager
        content = "\n".join([f"line {i}" for i in range(300)])
        result = ContextManager.truncate_tool_result(content, 200, 150)
        lines = result.split("\n")
        # Truncation adds a "[TRUNCATED: original had N lines]" separator line,
        # so the result has 200 data lines + 1 separator = 201 total lines
        assert len(lines) == 201
        assert "[TRUNCATED" in result
        assert "300" in result

    def test_truncate_single_line_by_chars(self):
        """Single-line content is not truncated — no newlines means no char-based truncation."""
        from context import ContextManager
        content = "x" * 500
        result = ContextManager.truncate_tool_result(content, 200, 150)
        # No newlines in content, so char-based truncation is NOT applied
        assert result == content


# =============================================================================
# ContextManager — sanitize_messages_for_llm
# =============================================================================

class TestSanitizeMessages:
    """Test message sanitization for LLM API compatibility."""

    def test_none_content_fixed(self):
        from context import ContextManager

        ctx = ContextManager()
        msgs = [{"role": "user", "content": None}]
        result = ctx.sanitize_messages_for_llm(msgs)
        assert result[0]["content"] == "(no output)"

    def test_empty_content_fixed(self):
        from context import ContextManager

        ctx = ContextManager()
        msgs = [{"role": "assistant", "content": ""}]
        result = ctx.sanitize_messages_for_llm(msgs)
        assert result[0]["content"] == "(no output)"

    def test_non_string_content_converted_to_string(self):
        from context import ContextManager

        ctx = ContextManager()
        msgs = [{"role": "user", "content": ["list", "content"]}]
        result = ctx.sanitize_messages_for_llm(msgs)
        assert result[0]["content"] == "['list', 'content']"
        assert isinstance(result[0]["content"], str)

    def test_tool_function_to_name_migration(self):
        """'function' property should be renamed to 'name' on tool messages."""
        from context import ContextManager

        ctx = ContextManager()
        msgs = [{
            "role": "tool",
            "content": "read result",
            "tool_call_id": "call_1",
            "function": "read_file",  # Old storage format
        }]
        result = ctx.sanitize_messages_for_llm(msgs)
        assert result[0]["name"] == "read_file"
        assert "function" not in result[0]

    def test_ok_content_unchanged(self):
        from context import ContextManager

        ctx = ContextManager()
        msgs = [{"role": "user", "content": "normal content"}]
        result = ctx.sanitize_messages_for_llm(msgs)
        assert result[0]["content"] == "normal content"


# =============================================================================
# ContextManager — build_system_prompt
# =============================================================================

class TestBuildSystemPrompt:
    """Test system prompt template replacement."""

    def test_replaces_all_matching_placeholders(self):
        from context import ContextManager

        ctx = ContextManager()
        mock_registry = MagicMock()
        mock_registry.build_context.return_value = {
            "time": "2025-01-01 12:00",
            "file": "open files here",
        }

        template = "System prompt with {time} and {file} placeholders."
        result = ctx.build_system_prompt(template, mock_registry)

        assert "{time}" not in result
        assert "{file}" not in result
        assert "2025-01-01 12:00" in result
        assert "open files here" in result

    def test_unreplaced_placeholders_logged(self):
        from context import ContextManager

        ctx = ContextManager()
        mock_registry = MagicMock()
        mock_registry.build_context.return_value = {"time": "now"}

        template = "Prompt with {time} and {nonexistent_tag} placeholder"
        with patch("context._debug"):
            result = ctx.build_system_prompt(template, mock_registry)
            # The {nonexistent_tag} should remain since no context provides it
            assert "{nonexistent_tag}" in result


# =============================================================================
# ContextManager — prepare_messages_for_llm
# =============================================================================

class TestPrepareMessages:
    """Test prepare_messages_for_llm() end-to-end."""

    def test_filters_internal_fields(self):
        from context import ContextManager

        ctx = ContextManager()
        history = [{
            "id": 999,
            "session_id": "s1",
            "role": "user",
            "content": "hello",
            "created_at": "2025-01-01T00:00:00Z",
            "token_count": 5,
        }]

        with patch.object(ctx, "build_system_prompt", return_value=""):
            messages, system = ctx.prepare_messages_for_llm(history, "", MagicMock())

        assert "id" not in messages[0]
        assert "session_id" not in messages[0]
        assert "created_at" not in messages[0]
        assert "token_count" not in messages[0]
        assert messages[0]["content"] == "hello"

    def test_system_prompt_prepended(self):
        from context import ContextManager

        ctx = ContextManager()
        history = [{"role": "user", "content": "hello"}]

        with patch.object(ctx, "build_system_prompt", return_value="You are helpful."):
            messages, system = ctx.prepare_messages_for_llm(history, "", MagicMock())

        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful."
