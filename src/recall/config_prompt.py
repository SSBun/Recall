from collections.abc import Callable
from pathlib import Path
from typing import TextIO

import cmd2

from .config import ConfigError, get_config_settings, set_config_value
from .pi_client import PiClient, PiInvocationError

_PROMPT_KEYS = ("search.limit", "models.tag", "models.ask")
_LABELS = {
    "search.limit": "Edit search limit",
    "models.tag": "Edit tagging model",
    "models.ask": "Edit ask model",
}
_VALUE_LABELS = {
    "search.limit": "search limit",
    "models.tag": "tagging model",
    "models.ask": "ask model",
}


def run_config_prompt(
    config_path: Path,
    stdin: TextIO,
    stdout: TextIO,
    *,
    model_lister: Callable[[], list[str]] | None = None,
) -> int:
    prompt = cmd2.Cmd(
        stdin=stdin,
        stdout=stdout,
        allow_cli_args=False,
        allow_clipboard=False,
        allow_redirection=False,
        auto_suggest=False,
        include_ipy=False,
        include_py=False,
        persistent_history_file="",
        shortcuts={},
    )
    print("┌  Recall setup", file=stdout)
    print("│", file=stdout)

    try:
        while True:
            settings = get_config_settings(config_path)
            options = [
                (key, f"{_LABELS[key]} ({settings[key]})")
                for key in _PROMPT_KEYS
            ]
            options.append(("exit", "Exit"))
            selected = _select(prompt, options, stdin, stdout)
            if selected == "exit":
                print("└", file=stdout)
                return 0

            if selected.startswith("models."):
                value = _select_model(
                    prompt,
                    selected,
                    str(settings[selected]),
                    model_lister or PiClient().list_available_models,
                    stdin,
                    stdout,
                )
                if value is None:
                    print("│", file=stdout)
                    continue
            else:
                value = _read_value(
                    prompt,
                    f"New {_VALUE_LABELS[selected]}",
                    str(settings[selected]),
                    stdin,
                    stdout,
                )
                if value is None:
                    print("└", file=stdout)
                    return 0
            try:
                updated = set_config_value(selected, value, config_path)
            except ConfigError as error:
                print(f"│  ERROR: {error}", file=stdout)
            else:
                print(f"│  Updated {selected} = {updated[selected]}", file=stdout)
            print("│", file=stdout)
    except KeyboardInterrupt:
        print("\n└", file=stdout)
        return 130


def _select_model(
    prompt: cmd2.Cmd,
    key: str,
    current: str,
    model_lister: Callable[[], list[str]],
    stdin: TextIO,
    stdout: TextIO,
) -> str | None:
    try:
        models = list(dict.fromkeys(model_lister()))
    except PiInvocationError as error:
        print(f"│  ERROR: {error}", file=stdout)
        return None
    if not models:
        print("│  ERROR: No available models. Configure provider credentials first.", file=stdout)
        return None
    if current in models:
        models.insert(0, models.pop(models.index(current)))
    options: list[tuple[str | None, str]] = [
        (model, f"{model} (current)" if model == current else model)
        for model in models
    ]
    options.append((None, "Back"))
    return _select(
        prompt,
        options,
        stdin,
        stdout,
        heading=f"◆  Select {_VALUE_LABELS[key]}:",
    )


def _select(
    prompt: cmd2.Cmd,
    options: list[tuple[str | None, str]],
    stdin: TextIO,
    stdout: TextIO,
    *,
    heading: str = "◆  Configuration:",
) -> str | None:
    if _is_tty(stdin, stdout):
        return prompt.select(options, prompt=heading)

    print(heading, file=stdout)
    for index, (_, label) in enumerate(options, start=1):
        marker = "●" if index == 1 else "○"
        print(f"│  {marker} {label}", file=stdout)
    while True:
        stdout.write(f"│  Select [1-{len(options)}]: ")
        stdout.flush()
        response = stdin.readline()
        if not response:
            return options[-1][0]
        try:
            index = int(response.strip()) - 1
            if not 0 <= index < len(options):
                raise IndexError
            return options[index][0]
        except (ValueError, IndexError):
            print("│  Invalid selection", file=stdout)


def _read_value(
    prompt: cmd2.Cmd,
    label: str,
    current: str,
    stdin: TextIO,
    stdout: TextIO,
) -> str | None:
    message = f"◆  {label} [{current}]: "
    if _is_tty(stdin, stdout):
        try:
            value = prompt.read_input(message)
        except EOFError:
            return None
    else:
        stdout.write(message)
        stdout.flush()
        value = stdin.readline()
        if not value:
            return None
        value = value.rstrip("\n")
    return value.strip() or current


def _is_tty(stdin: TextIO, stdout: TextIO) -> bool:
    return bool(
        getattr(stdin, "isatty", lambda: False)()
        and getattr(stdout, "isatty", lambda: False)()
    )
