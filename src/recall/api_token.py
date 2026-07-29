"""Global API token management for the Recall HTTP API."""

import fcntl
import os
import secrets
import tempfile
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH

DEFAULT_TOKEN_PATH = DEFAULT_CONFIG_PATH.with_name("api-token")


def get_or_create_token(path: Path = DEFAULT_TOKEN_PATH) -> str:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lock_path = path.parent / f".{path.name}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        token = _read_token(path)
        if token:
            return token
        token = secrets.token_urlsafe(32)
        _atomic_write(path, token)
        return token


def _read_token(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _atomic_write(path: Path, token: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(token)
            temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        os.chmod(path, 0o600)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
