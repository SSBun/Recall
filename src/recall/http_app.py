"""FastAPI HTTP application for the Recall per-store daemon."""

import io
import json
import os
import secrets
import threading
import time
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from .config import DEFAULT_CONFIG_PATH
from .service import RecallError

API_VERSION = 1
DASHBOARD_DIR = Path(__file__).parent / "dashboard"
CSP_HEADER = (
    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def _ok(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"version": API_VERSION, "ok": True, "data": data},
    )


def _fail(
    code: str,
    message: str,
    status: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JSONResponse(
        status_code=status,
        content={"version": API_VERSION, "ok": False, "error": error},
    )


def _partial(data: dict[str, Any]) -> JSONResponse:
    failed = data.get("failed", [])
    return _fail(
        "PARTIAL_FAILURE",
        f"{len(failed)} item(s) failed",
        207,
        details=data,
    )


def _dashboard_headers(*, cache_control: str = "no-store") -> dict[str, str]:
    return {
        "Content-Security-Policy": CSP_HEADER,
        "Cache-Control": cache_control,
        "Cross-Origin-Resource-Policy": "same-origin",
    }


def _dashboard_bootstrap_meta(token: str, base_url: str) -> str:
    return (
        f'<meta name="recall-api-base" content="{escape(base_url, quote=True)}">\n'
        f'<meta name="recall-api-token" content="{escape(token, quote=True)}">'
    )


class RuntimeSeam:
    def __init__(
        self,
        app: Any,
        store: Path,
        *,
        pi_client: Any | None = None,
        session_manager: Any | None = None,
        config_path: Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.app = app
        self.store = store
        self.pi_client = pi_client
        self.session_manager = session_manager
        self.config_path = config_path
        self._lock = threading.RLock()
        self._stop_callback: Callable[[], None] | None = None
        self._last_activity = time.monotonic()
        self._activity_lock = threading.Lock()

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    @property
    def last_activity(self) -> float:
        with self._activity_lock:
            return self._last_activity

    def touch(self) -> None:
        with self._activity_lock:
            self._last_activity = time.monotonic()

    def execute_locked(self, fn: Callable[[], Any]) -> Any:
        with self._lock:
            return fn()

    def request_stop(self) -> None:
        if self._stop_callback is not None:
            self._stop_callback()

    def set_stop_callback(self, callback: Callable[[], None]) -> None:
        self._stop_callback = callback

    def run_cli(self, argv: list[str]) -> dict[str, Any]:
        stdout_holder: list[str] = []
        needs_store = not argv or argv[0] not in {"config", "provider"}
        cli_argv = [*argv]
        if needs_store:
            cli_argv.extend(["--store", str(self.store)])
        cli_argv.append("--json")

        def _run() -> None:
            from .cli import run

            stdout = io.StringIO()
            try:
                run(
                    cli_argv,
                    app_factory=lambda _store: self.app,
                    use_daemon=False,
                    config_path=self.config_path,
                    stdout=stdout,
                    stderr=io.StringIO(),
                )
            except SystemExit:
                pass
            stdout_holder.append(stdout.getvalue())

        self.execute_locked(_run)
        try:
            return json.loads(stdout_holder[0])
        except (IndexError, json.JSONDecodeError):
            return {
                "version": API_VERSION,
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Internal server error",
                },
            }


class SearchRequest(BaseModel):
    query: str
    limit: int | None = None
    category: str | None = None
    tag: str | None = None


class AskRequest(BaseModel):
    question: str
    limit: int | None = None
    model: str | None = None
    allow_general_knowledge: bool = False


class IndexRequest(BaseModel):
    paths: list[str]
    recursive: bool = False
    document_id: str | None = None
    no_tag: bool = False
    tag_model: str | None = None
    concurrency: int | None = None


class RemoveRequest(BaseModel):
    document_ids: list[str]


class RetagRequest(BaseModel):
    document_ids: list[str]
    tag_model: str | None = None


class ConfigPatch(BaseModel):
    models_tag: str | None = None
    models_ask: str | None = None
    search_limit: int | None = None


class ProviderLoginRequest(BaseModel):
    method: str = "browser"


class AuthCodeRequest(BaseModel):
    code: str


class _HTTPError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


_CODE_TO_STATUS = {
    "USAGE_ERROR": 400,
    "AUTH_ERROR": 401,
    "FORBIDDEN": 403,
    "DOCUMENT_NOT_FOUND": 404,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "GONE": 410,
    "PARTIAL_FAILURE": 207,
    "DAEMON_STOPPING": 503,
    "SOURCE_ERROR": 400,
    "STORE_ERROR": 500,
    "EMBEDDING_FAILED": 500,
    "PI_ERROR": 500,
    "TAGGING_FAILED": 500,
    "DAEMON_ERROR": 500,
    "INTERNAL_ERROR": 500,
}


_STATUS_TO_CODE = {
    400: "USAGE_ERROR",
    401: "AUTH_ERROR",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    410: "GONE",
    503: "DAEMON_STOPPING",
    500: "INTERNAL_ERROR",
}


def _error_to_status(code: str) -> int:
    return _CODE_TO_STATUS.get(code, 500)


def _public_error_message(code: str, message: str) -> str:
    if code in {"INTERNAL_ERROR", "DAEMON_ERROR"}:
        return "Internal server error"
    return message


def build_http_app(seam: RuntimeSeam, *, token: str, api_url: str = "") -> FastAPI:
    app = FastAPI(
        title="Recall API",
        version=str(API_VERSION),
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.seam = seam
    app.state.token = token
    app.state.api_url = api_url.rstrip("/")
    parsed = urlsplit(app.state.api_url) if app.state.api_url else None
    app.state.api_host = parsed.netloc if parsed else ""
    app.state.api_origin = app.state.api_url if parsed else ""

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        host = request.headers.get("host", "")
        if not host:
            response = _fail("FORBIDDEN", "Host not allowed", 403)
        else:
            expected_host = app.state.api_host
            if expected_host:
                host_allowed = host == expected_host
            else:
                host_allowed = host == "127.0.0.1" or host.startswith("127.0.0.1:")
            if not host_allowed:
                response = _fail("FORBIDDEN", "Host not allowed", 403)
            else:
                origin = request.headers.get("origin", "")
                expected_origin = app.state.api_origin or f"{request.url.scheme}://{host}"
                if origin and origin.rstrip("/") != expected_origin:
                    response = _fail("FORBIDDEN", "Origin not allowed", 403)
                else:
                    response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response

    @app.middleware("http")
    async def activity_middleware(request: Request, call_next):
        seam.touch()
        response = await call_next(request)
        seam.touch()
        return response

    @app.exception_handler(_HTTPError)
    def http_error_handler(_request: Request, exc: _HTTPError):
        return _fail(exc.code, exc.message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    def validation_error_handler(_request: Request, exc: RequestValidationError):
        return _fail(
            "USAGE_ERROR",
            "Invalid request.",
            400,
            details={"errors": exc.errors()},
        )

    @app.exception_handler(HTTPException)
    def fastapi_http_error_handler(_request: Request, exc: HTTPException):
        code = _STATUS_TO_CODE.get(exc.status_code, "INTERNAL_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _fail(code, _public_error_message(code, message), exc.status_code)

    @app.exception_handler(Exception)
    def unhandled_error_handler(_request: Request, exc: Exception):
        if isinstance(exc, RecallError):
            code = exc.code
            return _fail(
                code,
                _public_error_message(code, exc.message),
                _error_to_status(code),
                exc.details or None,
            )
        return _fail("INTERNAL_ERROR", "Internal server error", 500)

    def require_token(request: Request) -> None:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            raise _HTTPError(401, "AUTH_ERROR", "Missing bearer token")
        if not secrets.compare_digest(auth_header[7:], token):
            raise _HTTPError(401, "AUTH_ERROR", "Invalid token")

    def run_envelope(argv: list[str]) -> JSONResponse:
        response = seam.run_cli(argv)
        if response.get("ok") is False:
            error = response.get("error", {})
            code = str(error.get("code", "INTERNAL_ERROR"))
            message = _public_error_message(
                code,
                str(error.get("message", "Internal server error")),
            )
            details = error.get("details")
            return _fail(code, message, _error_to_status(code), details)
        data = response.get("data")
        if isinstance(data, dict) and data.get("failed"):
            return _partial(data)
        return _ok(data)

    def session_response(session: Any) -> JSONResponse:
        data = session.to_dict()
        auth_url = session.latest_auth_url()
        if auth_url:
            data["auth_url"] = auth_url
        device_code = session.latest_device_code()
        if device_code:
            data["device_code"] = device_code
        if session.state == "expired":
            return _fail("GONE", "Session expired", 410, details=data)
        return _ok(data)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = FastAPI.openapi(app)
        schema.setdefault("components", {}).setdefault("securitySchemes", {})[
            "bearer"
        ] = {"type": "http", "scheme": "bearer"}
        for path, operations in schema.get("paths", {}).items():
            if not path.startswith("/v1/"):
                continue
            for method, operation in operations.items():
                if method in {"get", "put", "post", "patch", "delete", "options", "head"}:
                    operation["security"] = [{"bearer": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi

    @app.get("/")
    def root(request: Request) -> HTMLResponse:
        base_url = app.state.api_url or str(request.base_url).rstrip("/")
        html = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace(
            "<!-- RECALL_DASHBOARD_BOOTSTRAP -->",
            _dashboard_bootstrap_meta(token, base_url),
            1,
        )
        return HTMLResponse(html, headers=_dashboard_headers())

    @app.get("/dashboard/app.css")
    def dashboard_css() -> PlainTextResponse:
        return PlainTextResponse(
            (DASHBOARD_DIR / "app.css").read_text(encoding="utf-8"),
            media_type="text/css",
            headers=_dashboard_headers(),
        )

    @app.get("/dashboard/app.js")
    def dashboard_js() -> PlainTextResponse:
        return PlainTextResponse(
            (DASHBOARD_DIR / "app.js").read_text(encoding="utf-8"),
            media_type="application/javascript",
            headers=_dashboard_headers(),
        )

    @app.get("/dashboard/config.js")
    def dashboard_config(request: Request) -> PlainTextResponse:
        base_url = app.state.api_url or str(request.base_url).rstrip("/")
        script = (
            "window.__RECALL_DASHBOARD__ = "
            + json.dumps({"apiBase": base_url}, ensure_ascii=False)
            + ";\n"
        )
        return PlainTextResponse(
            script,
            media_type="application/javascript",
            headers=_dashboard_headers(),
        )

    @app.get("/v1/health")
    def v1_health(request: Request) -> JSONResponse:
        require_token(request)
        return _ok({"status": "ok"})

    @app.get("/v1/models")
    def v1_models(request: Request) -> JSONResponse:
        require_token(request)
        from .pi_client import PiInvocationError

        try:
            models = seam.execute_locked(
                lambda: seam.pi_client.list_available_models()
                if seam.pi_client is not None
                else _get_models(seam)
            )
        except PiInvocationError as error:
            return _fail("PI_ERROR", str(error), 500)
        return _ok({"models": models})

    @app.get("/v1/documents")
    def v1_documents(request: Request) -> JSONResponse:
        require_token(request)
        return run_envelope(["list"])

    @app.get("/v1/documents/{document_id}")
    def v1_document(document_id: str, request: Request) -> JSONResponse:
        require_token(request)
        return run_envelope(["show", document_id])

    @app.post("/v1/documents/index")
    def v1_index(body: IndexRequest, request: Request) -> JSONResponse:
        require_token(request)
        argv = ["index", *body.paths]
        if body.recursive:
            argv.append("--recursive")
        if body.document_id:
            argv.extend(["--document-id", body.document_id])
        if body.no_tag:
            argv.append("--no-tag")
        if body.tag_model:
            argv.extend(["--tag-model", body.tag_model])
        if body.concurrency is not None:
            argv.extend(["--concurrency", str(body.concurrency)])
        return run_envelope(argv)

    @app.post("/v1/documents/remove")
    def v1_remove(body: RemoveRequest, request: Request) -> JSONResponse:
        require_token(request)
        return run_envelope(["remove", *body.document_ids])

    @app.post("/v1/documents/retag")
    def v1_retag(body: RetagRequest, request: Request) -> JSONResponse:
        require_token(request)
        argv = ["retag", *body.document_ids]
        if body.tag_model:
            argv.extend(["--tag-model", body.tag_model])
        return run_envelope(argv)

    @app.post("/v1/search")
    def v1_search(body: SearchRequest, request: Request) -> JSONResponse:
        require_token(request)
        argv = ["search", body.query]
        if body.limit is not None:
            argv.extend(["--limit", str(body.limit)])
        if body.category:
            argv.extend(["--category", body.category])
        if body.tag:
            argv.extend(["--tag", body.tag])
        return run_envelope(argv)

    @app.post("/v1/ask")
    def v1_ask(body: AskRequest, request: Request) -> JSONResponse:
        require_token(request)
        argv = ["ask", body.question]
        if body.limit is not None:
            argv.extend(["--limit", str(body.limit)])
        if body.model:
            argv.extend(["--model", body.model])
        if body.allow_general_knowledge:
            argv.append("--allow-general-knowledge")
        return run_envelope(argv)

    @app.get("/v1/config")
    def v1_config_get(request: Request) -> JSONResponse:
        require_token(request)
        return run_envelope(["config", "list"])

    @app.patch("/v1/config")
    def v1_config_patch(body: ConfigPatch, request: Request) -> JSONResponse:
        require_token(request)
        from .config import set_config_value

        settings: dict[str, str] = {}
        if body.models_tag is not None:
            settings["models.tag"] = body.models_tag
        if body.models_ask is not None:
            settings["models.ask"] = body.models_ask
        if body.search_limit is not None:
            settings["search.limit"] = str(body.search_limit)
        if not settings:
            return _ok({"path": str(seam.config_path), "settings": _get_config(seam)})

        def apply_settings() -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in settings.items():
                result = set_config_value(key, value, seam.config_path)
            return result

        try:
            result = seam.execute_locked(apply_settings)
        except Exception as error:  # noqa: BLE001
            return _fail("USAGE_ERROR", str(error), 400)
        return _ok({"path": str(seam.config_path), "settings": result})

    @app.get("/v1/providers")
    def v1_providers(request: Request) -> JSONResponse:
        require_token(request)
        from .pi_client import PiInvocationError

        try:
            result = seam.execute_locked(
                lambda: seam.pi_client.provider_list()
                if seam.pi_client is not None
                else {"providers": []}
            )
        except PiInvocationError as error:
            return _fail("PI_ERROR", str(error), 500)
        return _ok(result)

    @app.post("/v1/providers/{provider_id}/login")
    def v1_provider_login(
        provider_id: str,
        body: ProviderLoginRequest,
        request: Request,
    ) -> JSONResponse:
        require_token(request)
        if seam.session_manager is None:
            return _fail("INTERNAL_ERROR", "OAuth sessions not available", 500)
        from .auth_session import OAuthSessionConflictError

        try:
            session = seam.execute_locked(
                lambda: seam.session_manager.create_session(provider_id, body.method)
            )
        except OAuthSessionConflictError as error:
            return _fail("CONFLICT", str(error), 409)
        except ValueError as error:
            return _fail("USAGE_ERROR", str(error), 400)
        return _ok(
            {
                "session_id": session.session_id,
                "provider": provider_id,
                "method": body.method,
            },
            status=202,
        )

    @app.delete("/v1/providers/{provider_id}")
    def v1_provider_logout(provider_id: str, request: Request) -> JSONResponse:
        require_token(request)
        from .pi_client import PiInvocationError

        try:
            result = seam.execute_locked(
                lambda: seam.pi_client.provider_logout(provider_id)
                if seam.pi_client is not None
                else {"provider": provider_id, "status": "disconnected"}
            )
        except PiInvocationError as error:
            return _fail("PI_ERROR", str(error), 500)
        return _ok(result)

    @app.get("/v1/auth-sessions/{session_id}")
    def v1_auth_session(session_id: str, request: Request) -> JSONResponse:
        require_token(request)
        if seam.session_manager is None:
            return _fail("NOT_FOUND", "OAuth sessions not available", 404)
        session = seam.session_manager.get_session(session_id)
        if session is None:
            return _fail("NOT_FOUND", f"Session not found: {session_id}", 404)
        return session_response(session)

    @app.post("/v1/auth-sessions/{session_id}/code")
    def v1_auth_code(
        session_id: str,
        body: AuthCodeRequest,
        request: Request,
    ) -> JSONResponse:
        require_token(request)
        if seam.session_manager is None:
            return _fail("NOT_FOUND", "OAuth sessions not available", 404)
        from .auth_session import (
            OAuthSessionExpiredError,
            OAuthSessionNotFoundError,
            OAuthSessionStateError,
        )

        try:
            seam.session_manager.submit_code(session_id, body.code)
        except OAuthSessionNotFoundError as error:
            return _fail("NOT_FOUND", str(error), 404)
        except OAuthSessionExpiredError as error:
            return _fail("GONE", str(error), 410)
        except OAuthSessionStateError as error:
            return _fail("USAGE_ERROR", str(error), 400)
        return _ok({"session_id": session_id, "status": "code_submitted"})

    @app.delete("/v1/auth-sessions/{session_id}")
    def v1_auth_cancel(session_id: str, request: Request) -> JSONResponse:
        require_token(request)
        if seam.session_manager is None:
            return _fail("NOT_FOUND", "OAuth sessions not available", 404)
        from .auth_session import (
            OAuthSessionExpiredError,
            OAuthSessionNotFoundError,
            OAuthSessionStateError,
        )

        try:
            seam.session_manager.cancel_session(session_id)
        except OAuthSessionNotFoundError as error:
            return _fail("NOT_FOUND", str(error), 404)
        except OAuthSessionExpiredError as error:
            return _fail("GONE", str(error), 410)
        except OAuthSessionStateError as error:
            return _fail("CONFLICT", str(error), 409)
        return _ok({"session_id": session_id, "status": "cancelled"})

    @app.get("/v1/daemon")
    def v1_daemon_status(request: Request) -> JSONResponse:
        require_token(request)
        return _ok(
            {
                "store": str(seam.store),
                "status": "running",
                "pid": os.getpid(),
                "api_url": app.state.api_url,
            }
        )

    @app.post("/v1/daemon/stop")
    def v1_daemon_stop(request: Request) -> JSONResponse:
        require_token(request)

        def stop_later() -> None:
            time.sleep(0.1)
            seam.request_stop()

        threading.Thread(target=stop_later, daemon=True).start()
        return _ok({"store": str(seam.store), "status": "stopping"})

    return app


def _get_models(_seam: RuntimeSeam) -> list[str]:
    from .pi_client import PiClient

    return PiClient().list_available_models()


def _get_config(seam: RuntimeSeam) -> dict[str, Any]:
    from .config import get_config_settings

    return get_config_settings(seam.config_path)
