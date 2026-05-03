"""Tests for events.py — pub/sub event bus."""

import asyncio
import pytest
import events as evt_module


@pytest.fixture(autouse=True)
def clear_handlers():
    """Reset global _handlers between tests."""
    evt_module._handlers.clear()
    yield
    evt_module._handlers.clear()


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
