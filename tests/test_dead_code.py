"""Tests for ContextDB and ContextManager.

Verifies:
- ContextDB CRUD operations (add, get_history, delete_session)
- ContextManager message processing (sanitize, truncate, reorder)
- Token counting
"""

import pytest
import sys
import os
import tempfile
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestContextDB:
    """ContextDB CRUD operations."""

    def test_add_and_get_history(self):
        """Messages stored via add() are retrievable via get_history()."""
        from db import ContextDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = ContextDB(db_path=os.path.join(tmpdir, "test.db"))
            db.add("user", "hello world", session="s1")
            db.add("assistant", "hi there", session="s1")
            db.add("tool", "(no output)", session="s1", tool_call_id="call_1", function="read_file")

            history = db.get_history(session="s1")

        assert len(history) == 3
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "hello world"
        assert history[0]["token_count"] > 0
        assert history[1]["role"] == "assistant"
        assert history[2]["role"] == "tool"
        assert history[2]["tool_call_id"] == "call_1"
        assert history[2]["function"] == "read_file"

    def test_get_history_is_ordered_by_created_at(self):
        """Messages are returned in ascending created_at order."""
        from db import ContextDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = ContextDB(db_path=os.path.join(tmpdir, "test.db"))
            db.add("assistant", "second", session="s1")
            db.add("user", "first", session="s1")

            history = db.get_history(session="s1")

        assert len(history) == 2
        contents = [m["content"] for m in history]
        assert "first" in contents
        assert "second" in contents
        # Ascending order: first's created_at <= second's created_at
        assert history[0]["created_at"] <= history[1]["created_at"]

    def test_get_history_isolation_between_sessions(self):
        """Messages from one session don't leak into another."""
        from db import ContextDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = ContextDB(db_path=os.path.join(tmpdir, "test.db"))
            db.add("user", "s2 message", session="s2")
            db.add("user", "s1 message", session="s1")

            history_s1 = db.get_history(session="s1")
            history_s2 = db.get_history(session="s2")

        assert len(history_s1) == 1
        assert history_s1[0]["content"] == "s1 message"
        assert len(history_s2) == 1
        assert history_s2[0]["content"] == "s2 message"

    def test_delete_session(self):
        """delete_session removes all messages for that session."""
        from db import ContextDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = ContextDB(db_path=os.path.join(tmpdir, "test.db"))
            db.add("user", "msg1", session="s1")
            db.add("user", "msg2", session="s1")
            db.add("user", "msg3", session="s2")

            rows = db.delete_session(session="s1")
            history_s1 = db.get_history(session="s1")
            history_s2 = db.get_history(session="s2")

        assert rows == 2
        assert len(history_s1) == 0
        assert len(history_s2) == 1

    def test_session_stats(self):
        """session_stats returns count and total tokens."""
        from db import ContextDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = ContextDB(db_path=os.path.join(tmpdir, "test.db"))
            db.add("user", "short", session="s1")
            db.add("user", "a" * 200, session="s1")

            stats = db.session_stats(session="s1")

        assert stats["count"] == 2
        assert stats["tokens"] > 0

    def test_token_count_fallback(self):
        """Token count uses rough fallback when tiktoken unavailable."""
        from db.context_db import _count_tokens

        tokens = _count_tokens("hello world this is a test")
        assert tokens > 0


class TestContextManagerSanitize:
    """ContextManager message sanitization."""

    def test_sanitize_does_not_extract_name_from_content_with_colon(self):
        """Tool messages with colon in content and name already set should not be modified."""
        from context import ContextManager

        messages = [
            {
                "role": "tool",
                "content": "C:\\Users\\test\\file.py: line 42",
                "tool_call_id": "call_abc123",
                "name": "read_file",
            }
        ]

        ctx = ContextManager()
        result = ctx.sanitize_messages_for_llm(messages)

        assert result[0]["name"] == "read_file"
        assert result[0]["content"] == "C:\\Users\\test\\file.py: line 42"

    def test_sanitize_does_not_split_content_with_colon_when_name_is_set(self):
        """Legacy 'func_name: result' parsing does not fire when name is set."""
        from context import ContextManager

        messages = [
            {
                "role": "tool",
                "content": "read_file: some result content",
                "tool_call_id": "call_abc",
                "name": "some_other_name",
            }
        ]

        ctx = ContextManager()
        result = ctx.sanitize_messages_for_llm(messages)

        assert result[0]["name"] == "some_other_name"
        assert result[0]["content"] == "read_file: some result content"

    def test_sanitize_fixes_none_content(self):
        """Messages with None content are fixed to '(no output)'."""
        from context import ContextManager

        messages = [{"role": "user", "content": None}]

        ctx = ContextManager()
        result = ctx.sanitize_messages_for_llm(messages)

        assert result[0]["content"] == "(no output)"

    def test_sanitize_fixes_empty_content(self):
        """Messages with empty string content are fixed to '(no output)'."""
        from context import ContextManager

        messages = [{"role": "assistant", "content": ""}]

        ctx = ContextManager()
        result = ctx.sanitize_messages_for_llm(messages)

        assert result[0]["content"] == "(no output)"


class TestContextManagerPrepare:
    """ContextManager.prepare_messages_for_llm behavior."""

    def test_truncated_tool_message_has_no_original_len_field(self):
        """Truncated tool messages should not have original_len in output."""
        from context import ContextManager

        long_content = "\n".join([f"line {i}: {'x' * 100}" for i in range(300)])

        history = [
            {
                "role": "tool",
                "content": long_content,
                "tool_call_id": "call_abc123",
                "function": "read_file",
            }
        ]

        ctx = ContextManager(
            tool_result_max_lines=200,
            tool_result_char_per_line=150,
        )

        with MagicMock() as mock_registry:
            messages, _ = ctx.prepare_messages_for_llm(history, "", mock_registry)

        tool_msg = messages[0]
        assert "original_len" not in tool_msg
        assert tool_msg["role"] == "tool"
        assert "[TRUNCATED" in tool_msg["content"]

    def test_prepare_filters_internal_fields(self):
        """Internal fields (id, created_at) are stripped from history messages."""
        from context import ContextManager

        history = [
            {
                "id": 42,
                "session_id": "s1",
                "role": "user",
                "content": "hello",
                "created_at": "2025-01-01T00:00:00Z",
                "token_count": 5,
            }
        ]

        ctx = ContextManager()
        with MagicMock() as mock_registry:
            messages, _ = ctx.prepare_messages_for_llm(history, "", mock_registry)

        assert "id" not in messages[0]
        assert "created_at" not in messages[0]
        assert "token_count" not in messages[0]
        assert messages[0]["content"] == "hello"

    def test_prepare_inserts_system_prompt(self):
        """System prompt is prepended as a system message."""
        from context import ContextManager

        history = [{"role": "user", "content": "hi"}]
        system_template = "You are a helpful assistant."

        ctx = ContextManager()
        with MagicMock() as mock_registry:
            mock_registry.build_context.return_value = {}
            messages, system = ctx.prepare_messages_for_llm(history, system_template, mock_registry)

        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."
