"""In-memory OAuth session manager for async provider login via the HTTP API."""

import json
import secrets
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 15 * 60
TERMINAL_RETENTION_SECONDS = 60
CANCEL_GRACE_SECONDS = 0.2
WAIT_HEARTBEAT_SECONDS = 1.0
WAIT_PROCESS_POLL_SECONDS = 0.1
TERMINAL_STATES = {"completed", "error", "cancelled", "expired"}
LIVE_STATES = {"pending", "waiting_code"}


class OAuthSessionError(RuntimeError):
    pass


class OAuthSessionConflictError(OAuthSessionError):
    pass


class OAuthSessionNotFoundError(OAuthSessionError):
    pass


class OAuthSessionExpiredError(OAuthSessionError):
    pass


class OAuthSessionStateError(OAuthSessionError):
    pass


@dataclass
class OAuthEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class OAuthSession:
    session_id: str
    provider_id: str
    method: str
    expires_at: int
    deadline_monotonic: float
    state: str = "pending"
    events: list[OAuthEvent] = field(default_factory=list)
    error: str | None = None
    terminal_cleanup_at: float | None = None
    _process: subprocess.Popen | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _code_ready: threading.Event = field(default_factory=threading.Event, repr=False)
    _submitted_code: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider_id": self.provider_id,
            "method": self.method,
            "state": self.state,
            "error": self.error,
            "expires_at": self.expires_at,
            "events": [{"type": event.type, "data": event.data} for event in self.events[-20:]],
        }

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def push_event(self, event: OAuthEvent) -> None:
        with self._lock:
            self.events.append(event)

    def latest_auth_url(self) -> str | None:
        with self._lock:
            for event in reversed(self.events):
                if event.type == "auth_url":
                    return event.data.get("url")
                if event.type == "device_code":
                    return event.data.get("verification_uri")
        return None

    def latest_device_code(self) -> dict[str, Any] | None:
        with self._lock:
            for event in reversed(self.events):
                if event.type == "device_code":
                    return event.data
        return None

    def submit_code(self, code: str) -> None:
        with self._lock:
            self._submitted_code = code
        self._code_ready.set()

    def wait_for_code(
        self,
        *,
        heartbeat: Callable[[], None] | None = None,
        process_poll: Callable[[], int | None] | None = None,
    ) -> str | None:
        next_heartbeat = time.monotonic()
        while True:
            with self._lock:
                if self._submitted_code is not None:
                    code = self._submitted_code
                    self._submitted_code = None
                    self._code_ready.clear()
                    return code
                if self.state in TERMINAL_STATES:
                    self._code_ready.clear()
                    return None
            if process_poll is not None and process_poll() is not None:
                self._code_ready.clear()
                return None
            now = time.monotonic()
            remaining = self.deadline_monotonic - now
            if remaining <= 0:
                self._code_ready.clear()
                return None
            if heartbeat is not None and now >= next_heartbeat:
                heartbeat()
                next_heartbeat = now + WAIT_HEARTBEAT_SECONDS
            wait_timeout = min(
                WAIT_PROCESS_POLL_SECONDS,
                remaining,
                max(next_heartbeat - now, 0.0),
            )
            if self._code_ready.wait(timeout=wait_timeout):
                continue

    def wake(self) -> None:
        self._code_ready.set()


class OAuthSessionManager:
    def __init__(
        self,
        *,
        bridge_factory: Callable[[str, str, str, str], subprocess.Popen] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        terminal_retention: float = TERMINAL_RETENTION_SECONDS,
        on_activity: Callable[[], None] | None = None,
    ) -> None:
        self._sessions: dict[str, OAuthSession] = {}
        self._active_by_provider: dict[str, str] = {}
        self._lock = threading.Lock()
        self._bridge_factory = bridge_factory
        self._timeout = timeout
        self._terminal_retention = terminal_retention
        self._on_activity = on_activity or (lambda: None)

    def create_session(
        self,
        provider_id: str,
        method: str,
        *,
        auth_path: Path | str | None = None,
    ) -> OAuthSession:
        if method not in {"browser", "device_code"}:
            raise ValueError(f"Invalid OAuth method: {method}")

        self._maintain()
        session_id = secrets.token_urlsafe(16)
        session = OAuthSession(
            session_id=session_id,
            provider_id=provider_id,
            method=method,
            expires_at=int(time.time() + self._timeout),
            deadline_monotonic=time.monotonic() + self._timeout,
        )
        with self._lock:
            existing_id = self._active_by_provider.get(provider_id)
            existing = self._sessions.get(existing_id) if existing_id else None
            if existing is not None and existing.state in LIVE_STATES:
                raise OAuthSessionConflictError(
                    f"Active session already exists for {provider_id}"
                )
            self._sessions[session_id] = session
            self._active_by_provider[provider_id] = session_id

        try:
            process = self._spawn_bridge(session, provider_id, method, auth_path)
        except Exception:
            with self._lock:
                self._sessions.pop(session_id, None)
                self._active_by_provider.pop(provider_id, None)
            raise

        session._process = process
        self._on_activity()
        threading.Thread(target=self._drive, args=(session, process), daemon=True).start()
        threading.Thread(
            target=self._expire_when_due,
            args=(session.session_id,),
            daemon=True,
        ).start()
        return session

    def get_session(self, session_id: str) -> OAuthSession | None:
        self._maintain()
        return self._sessions.get(session_id)

    def submit_code(self, session_id: str, code: str) -> OAuthSession:
        self._maintain()
        session = self._sessions.get(session_id)
        if session is None:
            raise OAuthSessionNotFoundError(f"Session not found: {session_id}")
        if session.state == "expired":
            raise OAuthSessionExpiredError(f"Session expired: {session_id}")
        if session.state != "waiting_code":
            raise OAuthSessionStateError(
                f"Session is not waiting for a code: {session_id}"
            )
        session.submit_code(code)
        self._on_activity()
        return session

    def cancel_session(self, session_id: str) -> OAuthSession:
        self._maintain()
        session = self._sessions.get(session_id)
        if session is None:
            raise OAuthSessionNotFoundError(f"Session not found: {session_id}")
        if session.state == "expired":
            raise OAuthSessionExpiredError(f"Session expired: {session_id}")
        if session.state == "cancelled":
            return session
        if session.state in {"completed", "error"}:
            raise OAuthSessionStateError(
                f"Cannot cancel session in state {session.state}: {session_id}"
            )
        self._finish_session(session, "cancelled")
        session.push_event(OAuthEvent("cancelled", {}))
        session.wake()
        process = session._process
        self._write_control(process, {"type": "cancel"})
        deadline = time.monotonic() + CANCEL_GRACE_SECONDS
        while process is not None and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except Exception:  # noqa: S110, BLE001
                pass
        self._on_activity()
        return session

    def cleanup_all(self) -> None:
        with self._lock:
            session_ids = list(self._sessions)
        for session_id in session_ids:
            try:
                self.cancel_session(session_id)
            except OAuthSessionError:
                continue
        self._maintain()

    def expire_stale(self) -> None:
        self._maintain()

    def _maintain(self) -> None:
        now = time.monotonic()
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if session.state in LIVE_STATES and now >= session.deadline_monotonic:
                self._expire_session(session)
        with self._lock:
            for provider_id, session_id in list(self._active_by_provider.items()):
                session = self._sessions.get(session_id)
                if session is None or session.is_terminal():
                    self._active_by_provider.pop(provider_id, None)
            for session_id, session in list(self._sessions.items()):
                if (
                    session.terminal_cleanup_at is not None
                    and now >= session.terminal_cleanup_at
                ):
                    self._sessions.pop(session_id, None)

    def _expire_session(self, session: OAuthSession) -> None:
        if session.state not in LIVE_STATES:
            return
        self._finish_session(session, "expired", "Session expired")
        session.wake()
        process = session._process
        self._write_control(process, {"type": "cancel"})
        deadline = time.monotonic() + CANCEL_GRACE_SECONDS
        while process is not None and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except Exception:  # noqa: S110, BLE001
                pass

    def _expire_when_due(self, session_id: str) -> None:
        while True:
            session = self._sessions.get(session_id)
            if session is None or session.is_terminal():
                return
            remaining = session.deadline_monotonic - time.monotonic()
            if remaining <= 0:
                self._expire_session(session)
                self._maintain()
                return
            time.sleep(min(WAIT_HEARTBEAT_SECONDS, remaining))

    def _spawn_bridge(
        self,
        session: OAuthSession,
        provider_id: str,
        method: str,
        auth_path: Path | str | None,
    ) -> subprocess.Popen:
        if self._bridge_factory is not None:
            return self._bridge_factory(
                provider_id,
                method,
                str(auth_path or ""),
                session.session_id,
            )

        from .pi_client import PiClient

        client = PiClient()
        return subprocess.Popen(
            [
                client.node_executable,
                str(client.bridge_path),
                "provider",
                "login-session",
                provider_id,
                str(auth_path or client.auth_path),
                method,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _drive(self, session: OAuthSession, process: subprocess.Popen) -> None:
        stderr_capture: list[str] = []
        terminal_event = False

        def read_stderr() -> None:
            stream = process.stderr
            if stream is None:
                return
            stderr_capture.extend(list(stream))

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        try:
            stream = process.stdout
            if stream is not None:
                for raw_line in stream:
                    self._on_activity()
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue

                    event_type = payload.get("type")
                    if not isinstance(event_type, str):
                        continue
                    data = {key: value for key, value in payload.items() if key != "type"}

                    if event_type == "waiting":
                        with session._lock:
                            if session.state in TERMINAL_STATES:
                                break
                            session.state = "waiting_code"
                        session.push_event(OAuthEvent("waiting", data))
                        code = session.wait_for_code(
                            heartbeat=self._on_activity,
                            process_poll=process.poll,
                        )
                        if code is None:
                            if process.poll() is not None and session.state == "waiting_code":
                                self._finish_session(
                                    session,
                                    "error",
                                    self._process_failure_message(process, stderr_capture),
                                )
                                terminal_event = True
                                break
                            continue
                        if not self._write_control(process, {"type": "code", "code": code}):
                            self._finish_session(session, "error", "OAuth bridge failed")
                            terminal_event = True
                            break
                        continue

                    if event_type == "completed":
                        session.push_event(OAuthEvent("completed", data))
                        self._finish_session(session, "completed")
                        terminal_event = True
                        break
                    if event_type == "cancelled":
                        session.push_event(OAuthEvent("cancelled", data))
                        self._finish_session(session, "cancelled")
                        terminal_event = True
                        break
                    if event_type == "error":
                        session.push_event(OAuthEvent("error", data))
                        self._finish_session(
                            session,
                            "error",
                            str(data.get("message") or "OAuth error"),
                        )
                        terminal_event = True
                        break

                    session.push_event(OAuthEvent(event_type, data))
        except Exception as error:  # noqa: BLE001
            self._finish_session(session, "error", str(error))
            terminal_event = True
        finally:
            try:
                stderr_thread.join(timeout=1)
            finally:
                self._cleanup_process(process)
            if not terminal_event:
                if session.state in {"cancelled", "expired"}:
                    pass
                elif time.monotonic() >= session.deadline_monotonic:
                    self._expire_session(session)
                else:
                    self._finish_session(
                        session,
                        "error",
                        self._process_failure_message(process, stderr_capture),
                    )
            self._maintain()

    def _finish_session(
        self,
        session: OAuthSession,
        state: str,
        error: str | None = None,
    ) -> None:
        with session._lock:
            if session.state in TERMINAL_STATES and session.state != state:
                return
            session.state = state
            session.error = error
            session.terminal_cleanup_at = time.monotonic() + self._terminal_retention
            session._submitted_code = None
        session.wake()
        with self._lock:
            if self._active_by_provider.get(session.provider_id) == session.session_id:
                self._active_by_provider.pop(session.provider_id, None)

    def _write_control(
        self, process: subprocess.Popen | None, payload: dict[str, Any]
    ) -> bool:
        if process is None:
            return False
        stream = process.stdin
        if stream is None or getattr(stream, "closed", False):
            return False
        try:
            stream.write(json.dumps(payload) + "\n")
            stream.flush()
        except Exception:  # noqa: BLE001
            return False
        return True

    def _cleanup_process(self, process: subprocess.Popen) -> None:
        poll = getattr(process, "poll", None)
        terminate = getattr(process, "terminate", None)
        kill = getattr(process, "kill", None)
        wait = getattr(process, "wait", None)
        try:
            if callable(poll) and poll() is None and callable(terminate):
                try:
                    terminate()
                except Exception:  # noqa: S110, BLE001
                    pass
                if callable(wait):
                    try:
                        wait(timeout=CANCEL_GRACE_SECONDS)
                    except Exception:  # noqa: S110, BLE001
                        pass
                if callable(poll) and poll() is None and callable(kill):
                    try:
                        kill()
                    except Exception:  # noqa: S110, BLE001
                        pass
        finally:
            for stream_name in ("stdin", "stdout", "stderr"):
                stream = getattr(process, stream_name, None)
                if stream is None or getattr(stream, "closed", False):
                    continue
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:  # noqa: S110, BLE001
                        pass

    def _process_failure_message(
        self, process: subprocess.Popen, stderr_capture: list[str]
    ) -> str:
        if process.poll() == 0:
            return "OAuth bridge ended unexpectedly"
        return "OAuth bridge failed"
