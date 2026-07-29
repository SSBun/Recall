import json
import os
import re
import tempfile
import tomllib
from pathlib import Path

DEFAULT_CONCURRENCY = 4
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "recall" / "config.toml"
DEFAULT_STORE_PATH = Path.home() / ".local" / "share" / "recall" / "db"
DEFAULT_TAG_MODEL = "openai/gpt-4o-mini"
DEFAULT_ASK_MODEL = "openai/gpt-4o-mini"
CONFIG_KEYS = ("models.tag", "models.ask", "search.limit")


class ConfigError(ValueError):
    pass


def _positive_int(value: object, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConfigError(f"{source} 必须是正整数")
    try:
        parsed = int(value)
    except ValueError as error:
        raise ConfigError(f"{source} 必须是正整数") from error
    if parsed < 1:
        raise ConfigError(f"{source} 必须是正整数")
    return parsed


def _model_reference(value: object, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source} 必须是 provider/model")
    provider, separator, model = value.strip().partition("/")
    if not separator or not provider.strip() or not model.strip():
        raise ConfigError(f"{source} 必须是 provider/model")
    return f"{provider.strip()}/{model.strip()}"


def resolve_concurrency(
    cli_value: int | None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> int:
    if cli_value is not None:
        return _positive_int(cli_value, "--concurrency")

    environment_value = os.environ.get("RECALL_INDEX_CONCURRENCY")
    if environment_value is not None:
        return _positive_int(environment_value, "RECALL_INDEX_CONCURRENCY")

    value = _config_value(
        config_path, "index", "concurrency", DEFAULT_CONCURRENCY
    )
    return _positive_int(value, "index.concurrency")


def resolve_search_limit(
    cli_value: int | None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> int:
    if cli_value is not None:
        return _positive_int(cli_value, "--limit")
    value = _config_value(config_path, "search", "limit", DEFAULT_SEARCH_LIMIT)
    return _positive_int(value, "search.limit")


def resolve_model(
    cli_value: str | None,
    purpose: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> str:
    if purpose not in {"tag", "ask"}:
        raise ValueError(f"未知模型用途: {purpose}")
    environment_name = f"RECALL_{purpose.upper()}_MODEL"
    default = DEFAULT_TAG_MODEL if purpose == "tag" else DEFAULT_ASK_MODEL
    environment_value = os.environ.get(environment_name)
    if cli_value is not None:
        value = cli_value
    elif environment_value is not None:
        value = environment_value
    else:
        value = _config_value(config_path, "models", purpose, default)
    return _model_reference(value, f"models.{purpose}")


def resolve_store(cli_value: str | None) -> Path:
    value = cli_value or os.environ.get("RECALL_STORE")
    return Path(value).expanduser().resolve() if value else DEFAULT_STORE_PATH


def get_config_settings(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> dict[str, str | int]:
    return {
        "models.tag": _model_reference(
            _config_value(config_path, "models", "tag", DEFAULT_TAG_MODEL),
            "models.tag",
        ),
        "models.ask": _model_reference(
            _config_value(config_path, "models", "ask", DEFAULT_ASK_MODEL),
            "models.ask",
        ),
        "search.limit": _positive_int(
            _config_value(config_path, "search", "limit", DEFAULT_SEARCH_LIMIT),
            "search.limit",
        ),
    }


def set_config_value(
    name: str,
    value: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> dict[str, str | int]:
    if name not in CONFIG_KEYS:
        raise ConfigError(f"不支持的配置项: {name}")
    if name == "search.limit":
        normalized: str | int = _positive_int(value, name)
    else:
        normalized = _model_reference(value, name)

    get_config_settings(config_path)
    section, key = name.split(".", 1)
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    updated = _update_toml(text, section, key, normalized)
    _write_config(config_path, updated)
    return get_config_settings(config_path)


def _config_value(
    config_path: Path,
    section: str,
    key: str,
    default: object,
) -> object:
    value = _read_config(config_path).get(section, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{section}] 必须是配置表")
    return value.get(key, default)


def _read_config(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        return {}
    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"无法读取配置文件 {config_path}: {error}") from error


def _update_toml(
    text: str,
    section: str,
    key: str,
    value: str | int,
) -> str:
    lines = text.splitlines()
    assignment = f"{key} = {json.dumps(value, ensure_ascii=False)}"
    header = re.compile(rf"^\s*\[{re.escape(section)}\]\s*(?:#.*)?$")
    next_header = re.compile(r"^\s*\[\[?.+\]\]?\s*(?:#.*)?$")
    key_line = re.compile(rf"^\s*{re.escape(key)}\s*=")
    start = next((index for index, line in enumerate(lines) if header.match(line)), None)

    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend((f"[{section}]", assignment))
    else:
        end = next(
            (
                index
                for index in range(start + 1, len(lines))
                if next_header.match(lines[index])
            ),
            len(lines),
        )
        existing = next(
            (
                index
                for index in range(start + 1, end)
                if key_line.match(lines[index])
            ),
            None,
        )
        if existing is None:
            insert_at = end
            while insert_at > start + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, assignment)
        else:
            lines[existing] = assignment

    return "\n".join(lines).rstrip() + "\n"


def _write_config(config_path: Path, text: str) -> None:
    is_symlink = config_path.is_symlink()
    if is_symlink:
        config_path = config_path.resolve()
    parent_existed = config_path.parent.exists()
    config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not is_symlink or not parent_existed:
        os.chmod(config_path.parent, 0o700)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(text)
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, 0o600)
        temporary_path.replace(config_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
