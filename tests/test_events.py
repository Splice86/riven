"""Tests for events.py — pub/sub event bus."""

"""Tests for events.py — pub/sub event bus."""

import asyncio
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

import events as evt_module


@pytest.fixture(autouse=True)
def clean_events_state():
    """Reset global _handlers and _locks between tests."""
    evt_module._handlers.clear()
    evt_module._locks.clear()
    yield
    evt_module._handlers.clear()
    evt_module._locks.clear()


class TestSubscribe:
    """Test subscribe() registration."""

    def test_subscribe_adds_handler(self):
        def handler(**kwargs):
            pass

        evt_module.subscribe("my_event", handler)
        assert "my_event" in evt_module._handlers
        assert len(evt_module._handlers["my_event"]) == 1

    def test_subscribe_same_event_multiple(self):
        def handler1(**kwargs):
            pass

        def handler2(**kwargs):
            pass

        evt_module.subscribe("my_event", handler1)
        evt_module.subscribe("my_event", handler2)
        assert len(evt_module._handlers["my_event"]) == 2

    def test_subscribe_duplicate_allowed(self):
        def handler(**kwargs):
            pass

        evt_module.subscribe("my_event", handler)
        evt_module.subscribe("my_event", handler)
        assert len(evt_module._handlers["my_event"]) == 2


class TestUnsubscribe:
    """Test unsubscribe() removal."""

    def test_unsubscribe_removes_handler(self):
        def handler(**kwargs):
            pass

        evt_module.subscribe("my_event", handler)
        evt_module.unsubscribe("my_event", handler)
        assert "my_event" not in evt_module._handlers

    def test_unsubscribe_unknown_handler_no_crash(self):
        def handler(**kwargs):
            pass

        evt_module.subscribe("my_event", handler)
        evt_module.unsubscribe("my_event", lambda **kw: None)  # different handler
        assert len(evt_module._handlers["my_event"]) == 1

    def test_unsubscribe_unknown_event_no_crash(self):
        evt_module.unsubscribe("never_registered", lambda **kw: None)
        # Should not raise

    def test_unsubscribe_only_removes_matching_handler(self):
        def handler1(**kwargs):
            pass

        def handler2(**kwargs):
            pass

        evt_module.subscribe("my_event", handler1)
        evt_module.subscribe("my_event", handler2)
        evt_module.unsubscribe("my_event", handler1)
        assert len(evt_module._handlers["my_event"]) == 1
        assert evt_module._handlers["my_event"][0][0] is handler2


class TestPublish:
    """Test publish() dispatching."""

    def test_publish_calls_sync_handler(self):
        received = {}

        def handler(**kwargs):
            received.update(kwargs)

        evt_module.subscribe("my_event", handler)
        evt_module.publish("my_event", path="file.txt", content="hello")
        assert received["path"] == "file.txt"
        assert received["content"] == "hello"

    def test_publish_no_handlers_no_crash(self):
        evt_module.publish("never_registered", key="value")  # should not raise

    def test_publish_swallows_handler_exception(self):
        def bad_handler(**kwargs):
            raise ValueError("oops!")

        evt_module.subscribe("my_event", bad_handler)
        # Should not raise
        evt_module.publish("my_event", key="value")

    def test_publish_multiple_handlers(self):
        results = []

        def handler1(**kwargs):
            results.append("h1")

        def handler2(**kwargs):
            results.append("h2")

        evt_module.subscribe("my_event", handler1)
        evt_module.subscribe("my_event", handler2)
        evt_module.publish("my_event")
        assert results == ["h1", "h2"]

    def test_publish_passes_no_args(self):
        called = []

        def handler(**kwargs):
            called.append(True)

        evt_module.subscribe("my_event", handler)
        evt_module.publish("my_event")
        assert called == [True]


class TestPublishAsync:
    """Test publish() with async handlers."""

    @pytest.mark.asyncio
    async def test_publish_calls_async_handler(self):
        received = []

        async def handler(**kwargs):
            received.append(kwargs)

        evt_module.subscribe("my_event", handler)
        evt_module.publish("my_event", path="file.txt")
        # Give the fire-and-forget task a moment to run
        await asyncio.sleep(0.05)
        assert len(received) == 1
        assert received[0]["path"] == "file.txt"

    @pytest.mark.asyncio
    async def test_publish_async_handlers_fire_and_forget(self):
        start = asyncio.get_event_loop().time()

        async def slow_handler(**kwargs):
            await asyncio.sleep(0.1)

        evt_module.subscribe("my_event", slow_handler)
        # publish() should return immediately, not block
        publish_start = asyncio.get_event_loop().time()
        evt_module.publish("my_event")
        elapsed = asyncio.get_event_loop().time() - publish_start
        assert elapsed < 0.05  # returned almost instantly


class TestClear:
    """Test clear() removal."""

    def test_clear_specific_event(self):
        def handler(**kwargs):
            pass

        evt_module.subscribe("event1", handler)
        evt_module.subscribe("event2", handler)
        evt_module.clear("event1")
        assert "event1" not in evt_module._handlers
        assert "event2" in evt_module._handlers

    def test_clear_all_events(self):
        def handler(**kwargs):
            pass

        evt_module.subscribe("event1", handler)
        evt_module.subscribe("event2", handler)
        evt_module.clear()
        assert evt_module._handlers == {}

    def test_clear_nonexistent_event(self):
        evt_module.clear("never_registered")  # should not raise


class TestRunAsync:
    """Test _run_async fallback to thread when no running loop."""

    def test_run_async_no_loop_spawns_thread(self):
        received = []

        async def async_handler(**kwargs):
            received.append("ran")

        # Call _run_async directly — this should fall back to a thread
        evt_module._run_async(async_handler, "test_event", {})
        # Give thread time to start and run
        import time
        time.sleep(0.1)
        assert received == ["ran"]


class TestRegisterHandlerAlias:
    """Test that register_handler / unregister_handler are aliases for subscribe / unsubscribe."""

    def test_register_handler_is_subscribe(self):
        def handler(**kwargs):
            pass

        evt_module.register_handler("alias_event", handler)
        assert "alias_event" in evt_module._handlers
        assert len(evt_module._handlers["alias_event"]) == 1

    def test_unregister_handler_is_unsubscribe(self):
        def handler(**kwargs):
            pass

        evt_module.register_handler("alias_event", handler)
        evt_module.unregister_handler("alias_event", handler)
        assert "alias_event" not in evt_module._handlers


# =============================================================================
# Lock Registry Tests
# =============================================================================

class TestGetLockState:
    """Test get_lock_state() queries."""

    def test_get_lock_state_unlocked_returns_none(self):
        assert evt_module.get_lock_state("/unlocked/file.py") is None

    @pytest.mark.asyncio
    async def test_get_lock_state_locked_returns_lock_info(self):
        async with evt_module.acquire_lock("/locked/file.py", "holder-1", timeout=5.0, context="test"):
            state = evt_module.get_lock_state("/locked/file.py")
            assert state is not None
            assert state.holder == "holder-1"
            assert state.context == "test"

    @pytest.mark.asyncio
    async def test_get_lock_state_returns_none_after_release(self):
        async with evt_module.acquire_lock("/tmp/file.py", "holder-x", timeout=5.0, context="test"):
            assert evt_module.get_lock_state("/tmp/file.py") is not None
        # lock auto-released here
        assert evt_module.get_lock_state("/tmp/file.py") is None


class TestAcquireLock:
    """Test acquire_lock() semantics."""

    @pytest.mark.asyncio
    async def test_acquire_lock_returns_lock_info(self):
        async with evt_module.acquire_lock("/file.py", "alice", timeout=5.0, context="replace_text"):
            pass  # lock acquired and released cleanly
        # verify lock is released
        assert evt_module.get_lock_state("/file.py") is None

    @pytest.mark.asyncio
    async def test_acquire_lock_fires_lock_acquired_event(self):
        received = []

        def handler(path=None, holder=None, context=None, **kw):
            received.append({"path": path, "holder": holder, "context": context})

        evt_module.register_handler("lock_acquired", handler)

        async with evt_module.acquire_lock("/event/file.py", "bob", timeout=5.0, context="batch_edit"):
            pass

        assert len(received) == 1
        assert received[0]["path"] == "/event/file.py"
        assert received[0]["holder"] == "bob"
        assert received[0]["context"] == "batch_edit"

    @pytest.mark.asyncio
    async def test_acquire_lock_blocks_other_holder(self):
        """A second holder trying to acquire the same lock should timeout."""
        async with evt_module.acquire_lock("/contested.py", "holder-1", timeout=5.0, context="test"):
            try:
                async with evt_module.acquire_lock("/contested.py", "holder-2", timeout=0.1, context="test"):
                    assert False, "Expected TimeoutError"
            except asyncio.TimeoutError:
                pass  # expected

    @pytest.mark.asyncio
    async def test_acquire_lock_same_holder_reentrant(self):
        """Same holder re-acquiring the same path returns the same LockInfo (not a
        new wait). This is the idempotent re-acquire pattern that editor.py uses
        for batch_edit then replace_text on the same session.
        """
        # Manually step through __aenter__ / __aexit__ to test re-entrancy without
        # the outer context manager releasing the lock prematurely.
        cm1 = evt_module.acquire_lock("/reentrant.py", "session-abc", timeout=5.0, context="replace_text")
        result1 = await cm1.__aenter__()
        cm2 = evt_module.acquire_lock("/reentrant.py", "session-abc", timeout=5.0, context="replace_text")
        result2 = await cm2.__aenter__()
        assert result1 is result2  # same LockInfo, re-entrant
        await cm2.__aexit__(None, None, None)
        await cm1.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_acquire_lock_fires_on_waiter_timeout(self):
        """Waiters should receive a TimeoutError with holder info."""
        async with evt_module.acquire_lock("/timeout.py", "holder-1", timeout=5.0, context="test"):
            try:
                async with evt_module.acquire_lock("/timeout.py", "holder-2", timeout=0.05, context="test"):
                    pass
            except asyncio.TimeoutError as e:
                assert "timeout" in str(e).lower()
                assert "holder-1" in str(e) or "/timeout.py" in str(e)


class TestReleaseLock:
    """Test release_lock() semantics."""

    @pytest.mark.asyncio
    async def test_release_lock_returns_true_on_success(self):
        async with evt_module.acquire_lock("/release.py", "holder-1", timeout=5.0, context="test"):
            result = await evt_module.release_lock("/release.py", "holder-1")
            assert result is True
        # lock was already released, so double-release should be False
        assert await evt_module.release_lock("/release.py", "holder-1") is False

    @pytest.mark.asyncio
    async def test_release_lock_fires_lock_released_event(self):
        received = []

        def handler(path=None, holder=None, context=None, **kw):
            received.append({"path": path, "holder": holder, "context": context})

        # Register before acquiring so we capture the lock_acquired event too
        evt_module.register_handler("lock_acquired", lambda **kw: None)
        evt_module.register_handler("lock_released", handler)

        async with evt_module.acquire_lock("/released.py", "charlie", timeout=5.0, context="delete_file"):
            received.clear()  # clear lock_acquired so we only check lock_released

        assert len(received) == 1
        assert received[0]["path"] == "/released.py"
        assert received[0]["holder"] == "charlie"
        assert received[0]["context"] == "delete_file"

    @pytest.mark.asyncio
    async def test_release_lock_wrong_holder_returns_false(self):
        async with evt_module.acquire_lock("/locked.py", "alice", timeout=5.0, context="test"):
            result = await evt_module.release_lock("/locked.py", "bob")  # wrong holder
            assert result is False
            # Lock should still be held by alice
            assert evt_module.get_lock_state("/locked.py") is not None

    @pytest.mark.asyncio
    async def test_release_lock_nonexistent_returns_false(self):
        result = await evt_module.release_lock("/never/existed.py", "nobody")
        assert result is False


class TestGetAllLocks:
    """Test get_all_locks()."""

    def test_get_all_locks_empty_at_start(self):
        assert evt_module.get_all_locks() == {}

    @pytest.mark.asyncio
    async def test_get_all_locks_returns_all_held_locks(self):
        async with evt_module.acquire_lock("/file1.py", "holder-1", timeout=5.0, context="test"):
            async with evt_module.acquire_lock("/file2.py", "holder-2", timeout=5.0, context="test"):
                all_locks = evt_module.get_all_locks()
                assert "/file1.py" in all_locks
                assert "/file2.py" in all_locks
                assert all_locks["/file1.py"].holder == "holder-1"
                assert all_locks["/file2.py"].holder == "holder-2"


class TestClearLocksAndHandlers:
    """Test clear() removes locks as well as handlers."""

    @pytest.mark.asyncio
    async def test_clear_removes_locks(self):
        async with evt_module.acquire_lock("/clearme.py", "alice", timeout=5.0, context="test"):
            assert evt_module.get_lock_state("/clearme.py") is not None
            evt_module.clear()
            assert evt_module.get_lock_state("/clearme.py") is None

    @pytest.mark.asyncio
    async def test_clear_specific_event_does_not_remove_locks(self):
        def handler(**kwargs):
            pass

        evt_module.register_handler("some_event", handler)
        async with evt_module.acquire_lock("/keepme.py", "alice", timeout=5.0, context="test"):
            evt_module.clear("some_event")
            # Lock should still be held
            assert evt_module.get_lock_state("/keepme.py") is not None


class TestBrowserLockIntegration:
    """Test cross-system interaction between browser editor and Riven file tools.

    The browser editor holds locks with holder IDs starting with 'ed-' (e.g. 'ed-abc12345').
    Riven's file tools must refuse to edit a browser-locked file, but should still be able
    to edit files locked by Riven itself.
    """

    @pytest.mark.asyncio
    async def test_is_browser_lock_true_for_ed_prefix(self):
        """Locks with 'ed-' holders are identified as browser locks."""
        async with evt_module.acquire_lock("/browser/file.py", "ed-abc12345",
                                          timeout=5.0, context="browser editing"):
            state = evt_module.get_lock_state("/browser/file.py")
            assert state is not None
            assert evt_module.is_browser_lock(state) is True

    @pytest.mark.asyncio
    async def test_is_browser_lock_false_for_riven_session(self):
        """Locks with non-'ed-' holders are NOT browser locks (Riven's own sessions)."""
        async with evt_module.acquire_lock("/riven/file.py", "sess-abc-def-123",
                                          timeout=5.0, context="riven editing"):
            state = evt_module.get_lock_state("/riven/file.py")
            assert state is not None
            assert evt_module.is_browser_lock(state) is False

    @pytest.mark.asyncio
    async def test_is_browser_lock_false_for_generic_holder(self):
        """Generic holder IDs don't trigger the browser-lock check."""
        async with evt_module.acquire_lock("/generic/file.py", "alice", timeout=5.0, context="test"):
            state = evt_module.get_lock_state("/generic/file.py")
            assert state is not None
            assert evt_module.is_browser_lock(state) is False

    @pytest.mark.asyncio
    async def test_browser_lock_prevents_riven_edit(self):
        """When the browser holds a lock on a file, Riven's guard raises BrowserLockError."""
        # Simulate browser acquiring the lock
        async with evt_module.acquire_lock("/blocked.py", "ed-xyz789",
                                          timeout=5.0, context="browser editing"):
            # Import the guard function from the file editor module
            from modules.file.editor import (
                _require_no_browser_lock,
                BrowserLockError,
            )

            # Riven tries to edit — should be blocked
            with pytest.raises(BrowserLockError) as exc_info:
                _require_no_browser_lock("/blocked.py")

            assert exc_info.value.holder == "ed-xyz789"
            assert "browser editor" in str(exc_info.value).lower()
            assert "wait" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_browser_lock_not_prevented_after_release(self):
        """Once the browser releases the lock, Riven's guard passes without error."""
        # Acquire as browser, then release
        async with evt_module.acquire_lock("/allowed.py", "ed-abc000",
                                          timeout=5.0, context="browser editing"):
            pass  # lock auto-released

        # Now no lock exists — guard should pass silently
        from modules.file.editor import _require_no_browser_lock

        _require_no_browser_lock("/allowed.py")  # should not raise

    @pytest.mark.asyncio
    async def test_riven_own_lock_allows_edit(self):
        """Riven holding its own lock should NOT block its own edits (is_browser_lock returns False)."""
        from modules.file.editor import is_browser_lock

        async with evt_module.acquire_lock("/riven-owned.py", "sess-riven-001",
                                          timeout=5.0, context="riven batch_edit"):
            state = evt_module.get_lock_state("/riven-owned.py")
            assert state is not None
            # Riven's own lock is NOT a browser lock
            assert evt_module.is_browser_lock(state) is False
            # Therefore Riven can freely edit its own file
            from modules.file.editor import _require_no_browser_lock
            _require_no_browser_lock("/riven-owned.py")  # should not raise

    @pytest.mark.asyncio
    async def test_mixed_holders_riven_locked_by_browser(self):
        """Riven can't edit a file the browser has locked, even while Riven has other locks."""
        from modules.file.editor import (
            _require_no_browser_lock,
            BrowserLockError,
        )

        # Riven holds its own file fine
        async with evt_module.acquire_lock("/riven-own.py", "sess-riven-002",
                                          timeout=5.0, context="riven replace_text"):
            _require_no_browser_lock("/riven-own.py")  # allowed

            # Browser locks a different file
            async with evt_module.acquire_lock("/browser-own.md", "ed-def456",
                                              timeout=5.0, context="browser editing"):
                # Riven tries the browser-locked file — blocked
                with pytest.raises(BrowserLockError) as exc_info:
                    _require_no_browser_lock("/browser-own.md")
                assert "browser editor" in str(exc_info.value).lower()

                # Riven's own file still accessible
                _require_no_browser_lock("/riven-own.py")  # still allowed
