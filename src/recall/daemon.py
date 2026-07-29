import argparse
import fcntl
import hashlib
import io
import json
import os
import signal
import socket
import socketserver
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 1
IDLE_TIMEOUT_SECONDS = 30 * 60
START_TIMEOUT_SECONDS = 10
MAX_REQUEST_BYTES = 1024 * 1024


class DaemonError(RuntimeError):
    pass


class _ConnectError(DaemonError):
    pass


@dataclass(frozen=True)
class DaemonPaths:
    socket: Path
    lock: Path
    pid: Path
    log: Path


def default_runtime_root() -> Path:
    configured = os.environ.get("RECALL_DAEMON_RUNTIME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".local" / "state" / "recall" / "daemons"


def daemon_paths(store: Path, runtime_root: Path | None = None) -> DaemonPaths:
    store_id = hashlib.sha256(str(store.expanduser().resolve()).encode()).hexdigest()[:16]
    root = (runtime_root or default_runtime_root()).expanduser().resolve()
    return DaemonPaths(
        socket=root / f"{store_id}.sock",
        lock=root / f"{store_id}.lock",
        pid=root / f"{store_id}.pid",
        log=root / f"{store_id}.log",
    )


class DaemonClient:
    def __init__(
        self,
        store: Path,
        *,
        runtime_root: Path | None = None,
        python_executable: str = sys.executable,
    ) -> None:
        self.store = store.expanduser().resolve()
        self.runtime_root = (runtime_root or default_runtime_root()).resolve()
        self.paths = daemon_paths(self.store, self.runtime_root)
        self.python_executable = python_executable

    def request(self, argv: list[str]) -> dict[str, Any]:
        payload = {
            "version": PROTOCOL_VERSION,
            "operation": "run",
            "argv": argv,
            "environment": dict(os.environ),
        }
        try:
            response = self._send(payload)
        except _ConnectError:
            self._start()
            response = self._send(payload)
        return _response_data(response)

    def status(self) -> dict[str, Any]:
        try:
            return _response_data(
                self._send({"version": PROTOCOL_VERSION, "operation": "status"})
            )
        except _ConnectError:
            return {"store": str(self.store), "status": "stopped"}

    def stop(self) -> dict[str, Any]:
        try:
            data = _response_data(
                self._send({"version": PROTOCOL_VERSION, "operation": "stop"})
            )
        except _ConnectError:
            return {"store": str(self.store), "status": "stopped"}
        deadline = time.monotonic() + 2
        while self.paths.socket.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        return data

    def _start(self) -> None:
        _prepare_runtime_root(self.runtime_root)
        log_fd = os.open(
            self.paths.log,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        null_fd = os.open(os.devnull, os.O_RDONLY)
        os.chmod(self.paths.log, 0o600)
        arguments = [
            self.python_executable,
            "-m",
            "recall.daemon",
            "--store",
            str(self.store),
            "--runtime-root",
            str(self.runtime_root),
        ]
        try:
            os.posix_spawn(
                self.python_executable,
                arguments,
                os.environ.copy(),
                file_actions=[
                    (os.POSIX_SPAWN_DUP2, null_fd, 0),
                    (os.POSIX_SPAWN_DUP2, log_fd, 1),
                    (os.POSIX_SPAWN_DUP2, log_fd, 2),
                ],
                setsid=True,
            )
        finally:
            os.close(null_fd)
            os.close(log_fd)

        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                self._send({"version": PROTOCOL_VERSION, "operation": "status"})
                return
            except _ConnectError:
                time.sleep(0.05)
        raise DaemonError(f"daemon 启动超时；日志: {self.paths.log}")

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.connect(str(self.paths.socket))
        except OSError as error:
            connection.close()
            raise _ConnectError(str(error)) from error

        try:
            connection.sendall(
                (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            )
            with connection.makefile("r", encoding="utf-8") as reader:
                line = reader.readline()
        except OSError as error:
            raise DaemonError(f"daemon 通信失败: {error}") from error
        finally:
            connection.close()
        if not line:
            raise DaemonError("daemon 未返回响应")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as error:
            raise DaemonError("daemon 返回无效 JSON") from error
        if not isinstance(response, dict) or response.get("version") != PROTOCOL_VERSION:
            raise DaemonError("daemon 协议版本不匹配")
        return response


class _RecallServer(socketserver.UnixStreamServer):
    def __init__(self, socket_path: Path, store: Path, app: Any) -> None:
        self.store = store
        self.app = app
        self.last_activity = time.monotonic()
        self.stopping = False
        super().__init__(str(socket_path), _RequestHandler)

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        operation = request.get("operation")
        if operation == "status":
            return _success(
                {
                    "store": str(self.store),
                    "status": "running",
                    "pid": os.getpid(),
                }
            )
        if operation == "stop":
            self.stopping = True
            return _success({"store": str(self.store), "status": "stopped"})
        if operation != "run":
            return _failure("USAGE_ERROR", "未知 daemon 操作")
        argv = request.get("argv")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            return _failure("USAGE_ERROR", "daemon argv 必须是字符串数组")
        if not argv or argv[0] in {"provider", "daemon"}:
            return _failure("USAGE_ERROR", "daemon 只接受 RAG 命令")
        environment = request.get("environment")
        if not isinstance(environment, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in environment.items()
        ):
            return _failure("USAGE_ERROR", "daemon environment 必须是字符串映射")
        return self._run(argv, environment)

    def _run(self, argv: list[str], environment: dict[str, str]) -> dict[str, Any]:
        from .cli import run

        stdout = io.StringIO()
        with _request_environment(environment):
            run(
                [*argv, "--store", str(self.store), "--json"],
                app_factory=lambda _store: self.app,
                use_daemon=False,
                stdout=stdout,
                stderr=io.StringIO(),
            )
        try:
            response = json.loads(stdout.getvalue())
        except json.JSONDecodeError:
            return _failure("DAEMON_ERROR", "daemon 内部命令未返回有效 JSON")
        return response if isinstance(response, dict) else _failure(
            "DAEMON_ERROR", "daemon 内部命令响应无效"
        )


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if not line or len(line) > MAX_REQUEST_BYTES:
            response = _failure("USAGE_ERROR", "daemon 请求为空或过大")
        else:
            try:
                request = json.loads(line)
                if (
                    not isinstance(request, dict)
                    or request.get("version") != PROTOCOL_VERSION
                ):
                    raise ValueError
                response = self.server.execute(request)  # type: ignore[attr-defined]
            except (json.JSONDecodeError, ValueError):
                response = _failure("USAGE_ERROR", "daemon 请求无效")
        self.wfile.write(
            (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
        )
        self.server.last_activity = time.monotonic()  # type: ignore[attr-defined]


def serve(
    store: Path,
    *,
    runtime_root: Path | None = None,
    idle_timeout: float = IDLE_TIMEOUT_SECONDS,
    app_factory: Callable[[Path], Any] | None = None,
) -> int:
    store = store.expanduser().resolve()
    root = (runtime_root or default_runtime_root()).expanduser().resolve()
    paths = daemon_paths(store, root)
    _prepare_runtime_root(root)
    paths.lock.touch(exist_ok=True, mode=0o600)
    paths.lock.chmod(0o600)

    with paths.lock.open("r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        paths.socket.unlink(missing_ok=True)
        if len(os.fsencode(paths.socket)) >= 104:
            raise DaemonError(f"daemon socket 路径过长: {paths.socket}")

        if app_factory is None:
            from .cli import _create_app

            app_factory = _create_app
        app = app_factory(store)
        server = _RecallServer(paths.socket, store, app)
        os.chmod(paths.socket, 0o600)
        _write_pid(paths.pid, store)
        server.timeout = min(0.25, max(idle_timeout, 0.01))

        previous_handler: Any = None
        if threading.current_thread() is threading.main_thread():
            previous_handler = signal.signal(
                signal.SIGTERM,
                lambda _signum, _frame: setattr(server, "stopping", True),
            )
        try:
            while (
                not server.stopping
                and time.monotonic() - server.last_activity < idle_timeout
            ):
                server.handle_request()
        finally:
            if previous_handler is not None:
                signal.signal(signal.SIGTERM, previous_handler)
            server.server_close()
            paths.socket.unlink(missing_ok=True)
            paths.pid.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recall.daemon")
    parser.add_argument("--store", required=True)
    parser.add_argument("--runtime-root", required=True)
    args = parser.parse_args(argv)
    return serve(Path(args.store), runtime_root=Path(args.runtime_root))


@contextmanager
def _request_environment(environment: dict[str, str]) -> Iterator[None]:
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(environment)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def _prepare_runtime_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)


def _write_pid(path: Path, store: Path) -> None:
    path.touch(exist_ok=True, mode=0o600)
    path.chmod(0o600)
    path.write_text(
        json.dumps({"version": PROTOCOL_VERSION, "pid": os.getpid(), "store": str(store)}),
        encoding="utf-8",
    )


def _success(data: dict[str, Any]) -> dict[str, Any]:
    return {"version": PROTOCOL_VERSION, "ok": True, "data": data}


def _failure(code: str, message: str) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def _response_data(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("ok") is True and isinstance(response.get("data"), dict):
        return response["data"]
    error = response.get("error")
    code = error.get("code") if isinstance(error, dict) else "DAEMON_ERROR"
    message = error.get("message") if isinstance(error, dict) else "daemon 请求失败"
    details = {
        key: value
        for key, value in (error.items() if isinstance(error, dict) else [])
        if key not in {"code", "message"}
    }
    if code == "PARTIAL_FAILURE" and isinstance(details.get("details"), dict):
        return details["details"]
    from .service import RecallError

    raise RecallError(str(code), str(message), **details)


if __name__ == "__main__":
    raise SystemExit(main())
