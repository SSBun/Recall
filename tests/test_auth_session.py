"""OAuth session manager tests with fake bridge subprocesses."""

import json
import queue
import time
import unittest

from recall.auth_session import (
    OAuthSessionConflictError,
    OAuthSessionManager,
    OAuthSessionStateError,
)


class _QueueStream:
    def __init__(self) -> None:
        self._queue: queue.Queue[str | None] = queue.Queue()
        self.closed = False

    def push(self, line: str) -> None:
        self._queue.put(line)

    def finish(self) -> None:
        self._queue.put(None)

    def close(self) -> None:
        self.closed = True
        self.finish()

    def __iter__(self):
        return self

    def __next__(self) -> str:
        value = self._queue.get(timeout=2)
        if value is None:
            raise StopIteration
        return value + "\n"


class _FakeStdin:
    def __init__(self, on_write=None) -> None:
        self.on_write = on_write
        self.writes: list[str] = []
        self.closed = False

    def write(self, data: str) -> None:
        self.writes.append(data)
        if self.on_write is not None:
            self.on_write(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, on_write=None) -> None:
        self.stdout = _QueueStream()
        self.stderr = _QueueStream()
        self.stdin = _FakeStdin(on_write=on_write)
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self._returncode = -15
        self.stdout.finish()
        self.stderr.finish()

    def kill(self) -> None:
        self._returncode = -9
        self.stdout.finish()
        self.stderr.finish()

    def wait(self, timeout=None) -> int:
        deadline = time.monotonic() + (timeout or 1)
        while self._returncode is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if self._returncode is None:
            raise TimeoutError("process still running")
        return self._returncode

    def complete(self, *events: dict[str, object]) -> None:
        for event in events:
            self.stdout.push(json.dumps(event))
        self._returncode = 0
        self.stdout.finish()
        self.stderr.finish()

    def crash(self, returncode: int = 1) -> None:
        self._returncode = returncode
        self.stdout.finish()
        self.stderr.finish()


def _wait_for_state(session, expected, timeout=2.0):
    deadline = time.monotonic() + timeout
    while session.state != expected and time.monotonic() < deadline:
        time.sleep(0.02)
    return session.state


class OAuthSessionManagerTests(unittest.TestCase):
    def test_browser_flow_completes(self):
        process = _FakeProcess()
        process.complete(
            {"type": "auth_url", "url": "https://example.com/auth"},
            {"type": "completed"},
        )
        manager = OAuthSessionManager(bridge_factory=lambda *_args: process)
        session = manager.create_session("openai-codex", "browser")

        self.assertEqual(_wait_for_state(session, "completed"), "completed")
        self.assertEqual(session.latest_auth_url(), "https://example.com/auth")

    def test_device_code_preserves_interval_and_expiry(self):
        process = _FakeProcess()
        process.complete(
            {
                "type": "device_code",
                "verification_uri": "https://example.com/device",
                "user_code": "ABC-123",
                "interval_seconds": 5,
                "expires_in_seconds": 900,
            },
            {"type": "completed"},
        )
        manager = OAuthSessionManager(bridge_factory=lambda *_args: process)
        session = manager.create_session("openai-codex", "device_code")

        self.assertEqual(_wait_for_state(session, "completed"), "completed")
        device_code = session.latest_device_code()
        self.assertEqual(device_code["user_code"], "ABC-123")
        self.assertEqual(device_code["interval_seconds"], 5)
        self.assertEqual(device_code["expires_in_seconds"], 900)

    def test_manual_code_waits_for_submit_and_completes(self):
        holder = {"process": None}

        def on_write(data: str) -> None:
            if '"type": "code"' in data:
                holder["process"].complete({"type": "completed"})

        holder["process"] = _FakeProcess(on_write=on_write)
        holder["process"].stdout.push(json.dumps({"type": "waiting", "prompt": "Enter code"}))
        manager = OAuthSessionManager(bridge_factory=lambda *_args: holder["process"], timeout=2)
        process = holder["process"]
        session = manager.create_session("openai-codex", "browser")

        self.assertEqual(_wait_for_state(session, "waiting_code"), "waiting_code")
        manager.submit_code(session.session_id, "123456")
        self.assertEqual(_wait_for_state(session, "completed"), "completed")
        self.assertTrue(any('"code": "123456"' in write for write in process.stdin.writes))

    def test_waiting_code_becomes_error_immediately_when_bridge_exits(self):
        process = _FakeProcess()
        process.stdout.push(json.dumps({"type": "waiting", "prompt": "Enter code"}))
        manager = OAuthSessionManager(bridge_factory=lambda *_args: process, timeout=5)
        session = manager.create_session("openai-codex", "browser")

        self.assertEqual(_wait_for_state(session, "waiting_code"), "waiting_code")
        process.crash()
        self.assertEqual(_wait_for_state(session, "error"), "error")
        self.assertEqual(session.error, "OAuth bridge failed")
        self.assertFalse(any(event.type == "cancelled" for event in session.events))

    def test_provider_conflict_uses_typed_exception(self):
        process = _FakeProcess()
        manager = OAuthSessionManager(bridge_factory=lambda *_args: process, timeout=5)
        first = manager.create_session("openai-codex", "browser")

        with self.assertRaises(OAuthSessionConflictError):
            manager.create_session("openai-codex", "browser")

        manager.cancel_session(first.session_id)

    def test_cancel_notifies_bridge_before_terminate(self):
        process = _FakeProcess()
        manager = OAuthSessionManager(bridge_factory=lambda *_args: process, timeout=5)
        session = manager.create_session("openai-codex", "browser")

        manager.cancel_session(session.session_id)

        self.assertEqual(session.state, "cancelled")
        self.assertTrue(process.stdin.writes)
        self.assertIn('"type": "cancel"', process.stdin.writes[0])

    def test_cancel_completed_session_raises_state_error_without_cancel_event(self):
        process = _FakeProcess()
        process.complete({"type": "completed"})
        manager = OAuthSessionManager(bridge_factory=lambda *_args: process, timeout=5)
        session = manager.create_session("openai-codex", "browser")

        self.assertEqual(_wait_for_state(session, "completed"), "completed")
        with self.assertRaises(OAuthSessionStateError):
            manager.cancel_session(session.session_id)

        self.assertEqual(session.state, "completed")
        self.assertFalse(any(event.type == "cancelled" for event in session.events))

    def test_terminal_session_does_not_get_overridden_by_expiry(self):
        process = _FakeProcess()
        process.complete({"type": "completed"})
        manager = OAuthSessionManager(bridge_factory=lambda *_args: process, timeout=0.05)
        session = manager.create_session("openai-codex", "browser")

        self.assertEqual(_wait_for_state(session, "completed"), "completed")
        time.sleep(0.08)
        self.assertEqual(session.state, "completed")

    def test_timeout_marks_session_expired_and_then_collects_it(self):
        process = _FakeProcess()
        manager = OAuthSessionManager(
            bridge_factory=lambda *_args: process,
            timeout=0.05,
            terminal_retention=0.05,
        )
        session = manager.create_session("openai-codex", "browser")

        self.assertEqual(_wait_for_state(session, "expired"), "expired")
        self.assertLessEqual(session.expires_at, int(time.time()) + 1)
        time.sleep(0.08)
        self.assertIsNone(manager.get_session(session.session_id))

    def test_session_to_dict_uses_epoch_expiry(self):
        process = _FakeProcess()
        process.complete({"type": "completed"})
        manager = OAuthSessionManager(bridge_factory=lambda *_args: process)
        session = manager.create_session("openai-codex", "browser")

        self.assertEqual(_wait_for_state(session, "completed"), "completed")
        payload = session.to_dict()
        self.assertIsInstance(payload["expires_at"], int)
        self.assertIn("events", payload)
