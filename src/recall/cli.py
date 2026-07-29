import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from .config import (
    CONFIG_KEYS,
    DEFAULT_CONFIG_PATH,
    ConfigError,
    get_config_settings,
    resolve_concurrency,
    resolve_model,
    resolve_search_limit,
    resolve_store,
    set_config_value,
)
from .service import RecallApp, RecallError
from .store import StoreError

API_VERSION = 1


class RecallArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise RecallError("USAGE_ERROR", message, help=self.format_help())


def build_parser() -> argparse.ArgumentParser:
    parser = RecallArgumentParser(
        prog="recall", description="Local personal knowledge base RAG CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    index = subparsers.add_parser("index", help="Add or update documents")
    index.add_argument("paths", nargs="+")
    index.add_argument("--recursive", action="store_true")
    index.add_argument("--document-id")
    tagging = index.add_mutually_exclusive_group()
    tagging.add_argument("--no-tag", action="store_true")
    tagging.add_argument("--tag-model")
    index.add_argument("--concurrency", type=int)
    _add_common_options(index)

    remove = subparsers.add_parser("remove", help="Remove documents")
    remove.add_argument("document_ids", nargs="+")
    _add_common_options(remove)

    list_parser = subparsers.add_parser("list", help="List documents")
    _add_common_options(list_parser)

    show = subparsers.add_parser("show", help="Show document details")
    show.add_argument("document_id")
    _add_common_options(show)

    search = subparsers.add_parser("search", help="Search document chunks")
    search.add_argument("query")
    search.add_argument("--limit", type=int)
    search.add_argument("--category")
    search.add_argument("--tag")
    _add_common_options(search)

    ask = subparsers.add_parser("ask", help="Answer using retrieved knowledge")
    ask.add_argument("question")
    ask.add_argument("--limit", type=int)
    ask.add_argument("--model")
    ask.add_argument("--allow-general-knowledge", action="store_true")
    _add_common_options(ask)

    retag = subparsers.add_parser("retag", help="Regenerate document tags")
    retag.add_argument("document_ids", nargs="+")
    retag.add_argument("--tag-model")
    _add_common_options(retag)

    provider = subparsers.add_parser(
        "provider", help="Manage model provider authentication"
    )
    provider_commands = provider.add_subparsers(dest="provider_command", required=True)
    login = provider_commands.add_parser(
        "login", help="Log in to an OAuth provider"
    )
    login.add_argument("provider_id", nargs="?")
    login.add_argument("--json", action="store_true")
    logout = provider_commands.add_parser(
        "logout", help="Remove provider credentials"
    )
    logout.add_argument("provider_id")
    logout.add_argument("--json", action="store_true")
    provider_list = provider_commands.add_parser(
        "list", help="List saved provider credentials"
    )
    provider_list.add_argument("--json", action="store_true")

    config = subparsers.add_parser(
        "config", help="Manage Recall configuration"
    )
    config_commands = config.add_subparsers(dest="config_command")
    config_list = config_commands.add_parser(
        "list", help="List configuration values"
    )
    config_list.add_argument("--json", action="store_true")
    config_set = config_commands.add_parser(
        "set", help="Set a configuration value"
    )
    config_set.add_argument("key", choices=CONFIG_KEYS)
    config_set.add_argument("value")
    config_set.add_argument("--json", action="store_true")

    daemon = subparsers.add_parser(
        "daemon", help="Manage the daemon for a store"
    )
    daemon_commands = daemon.add_subparsers(dest="daemon_command", required=True)
    daemon_help = {"status": "Show daemon status", "stop": "Stop the daemon"}
    for command, help_text in daemon_help.items():
        daemon_command = daemon_commands.add_parser(command, help=help_text)
        daemon_command.add_argument("--store")
        daemon_command.add_argument("--json", action="store_true")

    dashboard = subparsers.add_parser(
        "dashboard", help="Open the web dashboard for a store"
    )
    dashboard.add_argument("--store")
    dashboard.add_argument("--json", action="store_true")

    return parser


def run(
    argv: list[str] | None = None,
    *,
    app_factory: Callable[[Path], RecallApp] | None = None,
    provider_factory: Callable[[], Any] | None = None,
    provider_selector: Callable[[], str] | None = None,
    daemon_factory: Callable[[Path], Any] | None = None,
    config_prompt_runner: Callable[[Path, TextIO, TextIO], int] | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    use_daemon: bool = True,
    browser_opener: Callable[[str], None] | None = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in arguments

    try:
        args = build_parser().parse_args(arguments)
        if args.command == "config":
            if args.config_command is None:
                runner = config_prompt_runner or _run_config_prompt
                return runner(config_path, stdin, stdout)
            data = _dispatch_config(args, config_path)
        elif args.command == "provider":
            data = _dispatch_provider(
                (provider_factory or _create_pi_client)(),
                args,
                provider_selector,
            )
        elif args.command == "daemon":
            store_path = resolve_store(args.store)
            data = _dispatch_daemon(
                (daemon_factory or _create_daemon_client)(store_path), args
            )
        elif args.command == "dashboard":
            store_path = resolve_store(args.store)
            data = _dispatch_dashboard(
                (daemon_factory or _create_daemon_client)(store_path), args
            )
        else:
            store_path = resolve_store(args.store)
            if use_daemon and app_factory is None:
                data = (daemon_factory or _create_daemon_client)(store_path).request(
                    arguments
                )
            else:
                app = (app_factory or _create_app)(store_path)
                data = _dispatch(app, args, config_path)
        if isinstance(data, dict) and data.get("failed"):
            return _emit_partial(data, json_mode, stdout, stderr)
        if (
            args.command == "provider"
            and args.provider_command == "list"
            and not json_mode
        ):
            _emit_provider_statuses(data, stdout)
        elif args.command == "ask" and not json_mode:
            _emit_answer(data, stdout)
        elif args.command == "daemon" and not json_mode:
            _emit_daemon_status(data, stdout)
        elif args.command == "dashboard" and not json_mode:
            _emit_dashboard(data, stdout, browser_opener)
        elif args.command == "config" and not json_mode:
            _emit_config_settings(data, stdout)
        else:
            _emit_success(data, json_mode, stdout)
        return 0
    except ConfigError as error:
        return _emit_error("USAGE_ERROR", str(error), 2, json_mode, stdout, stderr)
    except RecallError as error:
        exit_code = 2 if error.code == "USAGE_ERROR" else 1
        return _emit_error(
            error.code,
            error.message,
            exit_code,
            json_mode,
            stdout,
            stderr,
            error.details,
        )
    except StoreError as error:
        return _emit_error("STORE_ERROR", str(error), 1, json_mode, stdout, stderr)
    # CLI 边界必须把未预期错误转换成稳定机器协议，而不是泄漏 traceback。
    except Exception as error:  # noqa: BLE001
        from .daemon import DaemonError

        code = "DAEMON_ERROR" if isinstance(error, DaemonError) else "INTERNAL_ERROR"
        return _emit_error(code, str(error), 1, json_mode, stdout, stderr)


def main() -> int:
    return run()


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store")
    parser.add_argument("--json", action="store_true")


def _create_app(store_path: Path) -> RecallApp:
    from .embedding import QwenEmbedder
    from .store import ChromaStore

    return RecallApp(ChromaStore(store_path), QwenEmbedder(), _create_pi_client())


def _create_pi_client() -> Any:
    from .pi_client import PiClient

    return PiClient()


def _create_daemon_client(store_path: Path) -> Any:
    from .daemon import DaemonClient

    return DaemonClient(store_path)


def _run_config_prompt(config_path: Path, stdin: TextIO, stdout: TextIO) -> int:
    from .config_prompt import run_config_prompt

    return run_config_prompt(config_path, stdin, stdout)


def _dispatch(
    app: RecallApp,
    args: argparse.Namespace,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Any:
    if args.command == "index":
        concurrency = resolve_concurrency(args.concurrency, config_path)
        return app.index(
            args.paths,
            recursive=args.recursive,
            document_id=args.document_id,
            no_tag=args.no_tag,
            tag_model=(
                None
                if args.no_tag
                else resolve_model(args.tag_model, "tag", config_path)
            ),
            concurrency=concurrency,
        )
    if args.command == "remove":
        return app.remove(args.document_ids)
    if args.command == "list":
        return {"documents": app.list_documents()}
    if args.command == "show":
        return app.show(args.document_id)
    if args.command == "search":
        return {
            "results": app.search(
                args.query,
                limit=resolve_search_limit(args.limit, config_path),
                category=args.category,
                tag=args.tag,
            )
        }
    if args.command == "ask":
        return app.ask(
            args.question,
            limit=resolve_search_limit(args.limit, config_path),
            model=resolve_model(args.model, "ask", config_path),
            allow_general_knowledge=args.allow_general_knowledge,
        )
    if args.command == "retag":
        return app.retag(
            args.document_ids,
            model=resolve_model(args.tag_model, "tag", config_path),
        )
    raise RecallError("USAGE_ERROR", f"未知命令: {args.command}")


def _dispatch_config(
    args: argparse.Namespace,
    config_path: Path,
) -> dict[str, object]:
    if args.config_command == "list":
        settings = get_config_settings(config_path)
    elif args.config_command == "set":
        settings = set_config_value(args.key, args.value, config_path)
    else:
        raise RecallError("USAGE_ERROR", f"未知 config 命令: {args.config_command}")
    return {"path": str(config_path), "settings": settings}


def _dispatch_provider(
    client: Any,
    args: argparse.Namespace,
    provider_selector: Callable[[], str] | None,
) -> dict[str, object]:
    from .pi_client import PiInvocationError

    try:
        if args.provider_command == "login":
            provider_id = args.provider_id
            if provider_id is None:
                if args.json:
                    raise RecallError(
                        "USAGE_ERROR",
                        "--json 模式必须显式指定 provider_id",
                    )
                from .provider_prompt import select_provider

                provider_id = (provider_selector or select_provider)()
            return client.provider_login(provider_id)
        if args.provider_command == "logout":
            return client.provider_logout(args.provider_id)
        if args.provider_command == "list":
            return client.provider_list()
    except PiInvocationError as error:
        raise RecallError("PI_ERROR", str(error)) from error
    raise RecallError("USAGE_ERROR", f"未知 provider 命令: {args.provider_command}")


def _dispatch_daemon(client: Any, args: argparse.Namespace) -> dict[str, object]:
    if args.daemon_command == "status":
        return client.status()
    if args.daemon_command == "stop":
        return client.stop()
    raise RecallError("USAGE_ERROR", f"未知 daemon 命令: {args.daemon_command}")


def _dispatch_dashboard(client: Any, args: argparse.Namespace) -> dict[str, object]:
    # Ensure daemon is running (auto-start if needed)
    status = client.ensure_running()
    api_url = status.get("api_url", "")
    dashboard_url = api_url + "/" if api_url else ""
    return {
        "store": str(status.get("store", "")),
        "dashboard_url": dashboard_url,
        "api_url": api_url,
    }


def _emit_provider_statuses(data: dict[str, Any], stdout: TextIO) -> None:
    from .provider_prompt import PROVIDER_OPTIONS

    connected = {provider["providerId"] for provider in data["providers"]}
    for provider_id, label in PROVIDER_OPTIONS:
        status = "已连接" if provider_id in connected else "未连接"
        print(f"{label}: {status}", file=stdout)


def _emit_answer(data: dict[str, Any], stdout: TextIO) -> None:
    print(data["answer"], file=stdout)
    if data["sources"]:
        print("\n来源：", file=stdout)
        for source in data["sources"]:
            print(f"[{source['reference']}] {source['path']}", file=stdout)


def _emit_daemon_status(data: dict[str, Any], stdout: TextIO) -> None:
    status = "运行中" if data["status"] == "running" else "已停止"
    pid = f" (PID {data['pid']})" if "pid" in data else ""
    print(f"{data['store']}: {status}{pid}", file=stdout)


def _emit_dashboard(
    data: dict[str, Any], stdout: TextIO, browser_opener: Callable[[str], None] | None
) -> None:
    url = data.get("dashboard_url") or data.get("api_url", "")
    if url:
        opener = browser_opener
        if opener is None:
            import webbrowser

            opener = webbrowser.open
        opener(url)
        print(f"Dashboard: {url}", file=stdout)
    else:
        print("Dashboard unavailable: daemon has no API URL", file=stdout)


def _emit_config_settings(data: dict[str, Any], stdout: TextIO) -> None:
    print(f"Configuration: {data['path']}", file=stdout)
    settings = data["settings"]
    for key in CONFIG_KEYS:
        print(f"{key} = {settings[key]}", file=stdout)


def _emit_success(data: Any, json_mode: bool, stdout: TextIO) -> None:
    if json_mode:
        print(
            json.dumps(
                {"version": API_VERSION, "ok": True, "data": data},
                ensure_ascii=False,
            ),
            file=stdout,
        )
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2), file=stdout)


def _emit_partial(
    data: dict[str, Any],
    json_mode: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    message = f"{len(data['failed'])} 项处理失败"
    if json_mode:
        print(
            json.dumps(
                {
                    "version": API_VERSION,
                    "ok": False,
                    "error": {
                        "code": "PARTIAL_FAILURE",
                        "message": message,
                        "details": data,
                    },
                },
                ensure_ascii=False,
            ),
            file=stdout,
        )
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2), file=stdout)
        print(message, file=stderr)
    return 1


def _emit_error(
    code: str,
    message: str,
    exit_code: int,
    json_mode: bool,
    stdout: TextIO,
    stderr: TextIO,
    details: dict[str, Any] | None = None,
) -> int:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error.update(details)
    if json_mode:
        print(
            json.dumps(
                {"version": API_VERSION, "ok": False, "error": error},
                ensure_ascii=False,
            ),
            file=stdout,
        )
    else:
        help_text = details.get("help") if details else None
        if isinstance(help_text, str):
            print(help_text.rstrip(), file=stderr)
        print(f"{code}: {message}", file=stderr)
    return exit_code
