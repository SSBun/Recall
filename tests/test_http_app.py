"""HTTP API contract tests using FastAPI TestClient with fake app/provider/session manager."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from recall.auth_session import OAuthSessionManager
from recall.http_app import RuntimeSeam, build_http_app
from recall.pi_client import PiInvocationError

TOKEN = "test-token-abc123"
API_URL = "http://127.0.0.1:9999"
EXPECTED_OPENAPI_PATHS = {
    "/",
    "/dashboard/app.css",
    "/dashboard/app.js",
    "/dashboard/config.js",
    "/v1/health",
    "/v1/models",
    "/v1/documents",
    "/v1/documents/{document_id}",
    "/v1/documents/index",
    "/v1/documents/remove",
    "/v1/documents/retag",
    "/v1/search",
    "/v1/ask",
    "/v1/config",
    "/v1/providers",
    "/v1/providers/{provider_id}",
    "/v1/providers/{provider_id}/login",
    "/v1/auth-sessions/{session_id}",
    "/v1/auth-sessions/{session_id}/code",
    "/v1/daemon",
    "/v1/daemon/stop",
}


class _FakeApp:
    def __init__(self):
        self.calls: list[tuple[str, list, dict]] = []
        self.raise_internal = False
        self.partial_index = False

    def index(self, paths, **options):
        self.calls.append(("index", list(paths), dict(options)))
        if self.partial_index:
            return {
                "concurrency": options.get("concurrency", 4),
                "indexed": [{"document_id": "doc_1", "path": paths[0]}],
                "unchanged": [],
                "failed": [{"path": paths[-1], "code": "SOURCE_ERROR", "message": "missing"}],
            }
        return {
            "concurrency": options.get("concurrency", 4),
            "indexed": [{"document_id": "doc_1", "path": paths[0], "status": "indexed"}],
            "unchanged": [],
            "failed": [],
        }

    def list_documents(self):
        self.calls.append(("list", [], {}))
        return [{"document_id": "doc_1", "path": "/note.md", "chunk_count": 1}]

    def show(self, document_id):
        self.calls.append(("show", [document_id], {}))
        return {"document_id": document_id, "path": "/note.md", "chunk_count": 1}

    def remove(self, document_ids):
        self.calls.append(("remove", list(document_ids), {}))
        return {"removed": list(document_ids), "failed": []}

    def search(self, query, **options):
        self.calls.append(("search", [query], dict(options)))
        if self.raise_internal:
            raise RuntimeError("secret traceback detail")
        return [{
            "document_id": "doc_1",
            "chunk_id": "chunk_0",
            "path": "/note.md",
            "content": "hit text",
            "distance": 0.5,
            "metadata": {
                "category": "tech",
                "tags": ["ai"],
                "summary": "summary",
                "chunk_index": 0,
            },
        }]

    def ask(self, question, **options):
        self.calls.append(("ask", [question], dict(options)))
        return {
            "answer": "answer [1]",
            "used_general_knowledge": options.get("allow_general_knowledge", False),
            "sources": [{
                "reference": 1,
                "document_id": "doc_1",
                "chunk_id": "chunk_0",
                "path": "/note.md",
                "content": "hit text",
                "metadata": {
                    "category": "tech",
                    "tags": ["ai"],
                    "summary": "summary",
                    "chunk_index": 0,
                },
            }],
        }

    def retag(self, document_ids, **options):
        self.calls.append(("retag", list(document_ids), dict(options)))
        return {"updated": list(document_ids), "failed": []}


class _FakePiClient:
    def __init__(self):
        self.fail_models = False
        self.fail_providers = False
        self.fail_logout = False

    def list_available_models(self):
        if self.fail_models:
            raise PiInvocationError("model lookup failed")
        return ["openai-codex/gpt-5.4", "openai/gpt-4o-mini"]

    def provider_list(self):
        if self.fail_providers:
            raise PiInvocationError("provider list failed")
        return {"providers": [{"providerId": "openai-codex", "type": "oauth"}]}

    def provider_logout(self, provider_id):
        if self.fail_logout:
            raise PiInvocationError("logout failed")
        return {"provider": provider_id, "status": "disconnected"}


class _QueueStream:
    def __init__(self):
        import queue

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

    def __next__(self):
        value = self._queue.get(timeout=2)
        if value is None:
            raise StopIteration
        return value + "\n"


class _FakeStdin:
    def __init__(self, on_write=None):
        self.writes = []
        self.closed = False
        self._on_write = on_write

    def write(self, data):
        self.writes.append(data)
        if self._on_write is not None:
            self._on_write(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self, on_write=None):
        self.stdout = _QueueStream()
        self.stderr = _QueueStream()
        self.stdin = _FakeStdin(on_write=on_write)
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = -15
        self.stdout.finish()
        self.stderr.finish()

    def kill(self):
        self._returncode = -9
        self.stdout.finish()
        self.stderr.finish()

    def wait(self, timeout=None):
        deadline = time.monotonic() + (timeout or 1)
        while self._returncode is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if self._returncode is None:
            raise TimeoutError("process still running")
        return self._returncode

    def complete(self, *events):
        for event in events:
            self.stdout.push(json.dumps(event))
        self._returncode = 0
        self.stdout.finish()
        self.stderr.finish()


class HttpApiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "config.toml"
        self.fake_app = _FakeApp()
        self.fake_pi = _FakePiClient()
        self.seam = RuntimeSeam(
            self.fake_app,
            Path("/tmp/test-store"),
            pi_client=self.fake_pi,
            config_path=self.config_path,
        )
        self.app = build_http_app(self.seam, token=TOKEN, api_url=API_URL)
        self.client = TestClient(self.app, base_url=API_URL, raise_server_exceptions=False)

    def tearDown(self):
        import shutil

        manager = self.seam.session_manager
        if manager is not None:
            manager.cleanup_all()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _auth(self):
        return {"Authorization": f"Bearer {TOKEN}"}

    def _session_manager(self, process=None, *, timeout=2):
        if process is None:
            process = _FakeProcess()
        manager = OAuthSessionManager(bridge_factory=lambda *_args: process, timeout=timeout)
        self.seam.session_manager = manager
        return manager, process

    def test_openapi_route_set_and_security(self):
        schema = self.client.get("/openapi.json").json()
        self.assertEqual(set(schema["paths"].keys()), EXPECTED_OPENAPI_PATHS)
        self.assertIn("bearer", schema["components"]["securitySchemes"])
        self.assertNotIn("security", schema["paths"]["/"]["get"])
        self.assertNotIn("security", schema["paths"]["/dashboard/app.js"]["get"])
        self.assertEqual(schema["paths"]["/v1/health"]["get"]["security"], [{"bearer": []}])
        self.assertEqual(schema["paths"]["/v1/providers/{provider_id}/login"]["post"]["security"], [{"bearer": []}])

    def test_root_injects_bootstrap_meta_and_rejects_malicious_origin(self):
        good = self.client.get("/")
        self.assertEqual(good.status_code, 200)
        self.assertIn('<meta name="recall-api-base" content="http://127.0.0.1:9999">', good.text)
        self.assertIn('<meta name="recall-api-token" content="test-token-abc123">', good.text)
        self.assertNotIn('/dashboard/config.js', good.text)
        self.assertEqual(good.headers["cross-origin-resource-policy"], "same-origin")

        bad = self.client.get("/", headers={"Origin": "http://evil.example"})
        self.assertEqual(bad.status_code, 403)

    def test_dashboard_config_js_never_contains_token(self):
        resp = self.client.get("/dashboard/config.js")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(TOKEN, resp.text)
        self.assertIn("apiBase", resp.text)
        self.assertEqual(resp.headers["x-content-type-options"], "nosniff")
        self.assertEqual(resp.headers["cross-origin-resource-policy"], "same-origin")

    def test_security_and_validation_contract(self):
        missing_token = self.client.get("/v1/health")
        self.assertEqual(missing_token.status_code, 401)
        self.assertEqual(missing_token.json()["error"]["code"], "AUTH_ERROR")

        empty_host = self.client.get("/v1/health", headers={**self._auth(), "Host": ""})
        self.assertEqual(empty_host.status_code, 403)

        wrong_host = self.client.get(
            "/v1/health",
            headers={**self._auth(), "Host": "127.0.0.1:1111"},
        )
        self.assertEqual(wrong_host.status_code, 403)

        wrong_origin = self.client.get(
            "/v1/health",
            headers={**self._auth(), "Origin": "http://127.0.0.1:1111"},
        )
        self.assertEqual(wrong_origin.status_code, 403)

        valid_origin = self.client.get(
            "/v1/health",
            headers={**self._auth(), "Origin": API_URL},
        )
        self.assertEqual(valid_origin.status_code, 200)
        self.assertNotIn("access-control-allow-origin", valid_origin.headers)

        validation = self.client.post("/v1/search", json={}, headers=self._auth())
        self.assertEqual(validation.status_code, 400)
        self.assertEqual(validation.json()["error"]["code"], "USAGE_ERROR")
        self.assertIn("errors", validation.json()["error"]["details"])

    def test_health_models_and_models_error(self):
        health = self.client.get("/v1/health", headers=self._auth())
        self.assertEqual(health.json()["data"], {"status": "ok"})

        models = self.client.get("/v1/models", headers=self._auth())
        self.assertEqual(models.json()["data"]["models"][0], "openai-codex/gpt-5.4")

        self.fake_pi.fail_models = True
        failed = self.client.get("/v1/models", headers=self._auth())
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["error"]["code"], "PI_ERROR")

    def test_documents_show_index_remove_retag_dispatch(self):
        listed = self.client.get("/v1/documents", headers=self._auth())
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["data"]["documents"][0]["document_id"], "doc_1")

        shown = self.client.get("/v1/documents/doc_1", headers=self._auth())
        self.assertEqual(shown.json()["data"]["document_id"], "doc_1")

        indexed = self.client.post(
            "/v1/documents/index",
            json={
                "paths": ["/note.md"],
                "recursive": True,
                "document_id": "doc_1",
                "no_tag": True,
                "concurrency": 7,
            },
            headers=self._auth(),
        )
        self.assertEqual(indexed.status_code, 200)
        self.assertEqual(self.fake_app.calls[-1][0], "index")
        self.assertEqual(
            self.fake_app.calls[-1][2],
            {
                "recursive": True,
                "document_id": "doc_1",
                "no_tag": True,
                "tag_model": None,
                "concurrency": 7,
            },
        )

        removed = self.client.post(
            "/v1/documents/remove",
            json={"document_ids": ["doc_1", "doc_2"]},
            headers=self._auth(),
        )
        self.assertEqual(removed.json()["data"]["removed"], ["doc_1", "doc_2"])

        retagged = self.client.post(
            "/v1/documents/retag",
            json={"document_ids": ["doc_1"], "tag_model": "openai/tagger"},
            headers=self._auth(),
        )
        self.assertEqual(retagged.json()["data"]["updated"], ["doc_1"])
        self.assertEqual(self.fake_app.calls[-1][2], {"model": "openai/tagger"})

    def test_search_and_ask_dispatch_defaults_and_errors(self):
        searched = self.client.post(
            "/v1/search",
            json={"query": "test", "category": "tech", "tag": "ai"},
            headers=self._auth(),
        )
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(self.fake_app.calls[-1], ("search", ["test"], {"limit": 5, "category": "tech", "tag": "ai"}))

        asked = self.client.post(
            "/v1/ask",
            json={
                "question": "what?",
                "model": "openai-codex/gpt-5.4",
                "allow_general_knowledge": True,
            },
            headers=self._auth(),
        )
        self.assertEqual(asked.status_code, 200)
        ask_body = asked.json()["data"]
        self.assertEqual(ask_body["answer"], "answer [1]")
        self.assertEqual(ask_body["sources"][0]["content"], "hit text")
        self.assertTrue(ask_body["used_general_knowledge"])
        self.assertEqual(
            self.fake_app.calls[-1],
            ("ask", ["what?"], {"limit": 5, "model": "openai-codex/gpt-5.4", "allow_general_knowledge": True}),
        )

        self.fake_app.raise_internal = True
        failed = self.client.post(
            "/v1/search",
            json={"query": "boom"},
            headers=self._auth(),
        )
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["error"], {"code": "INTERNAL_ERROR", "message": "Internal server error"})
        self.assertNotIn("secret traceback detail", failed.text)

    def test_config_get_patch_and_empty_patch(self):
        config = self.client.get("/v1/config", headers=self._auth())
        self.assertEqual(config.status_code, 200)
        self.assertIn("settings", config.json()["data"])

        patched = self.client.patch(
            "/v1/config",
            json={"models_ask": "openai-codex/gpt-5.4", "search_limit": 9},
            headers=self._auth(),
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["data"]["settings"]["search.limit"], 9)
        self.assertEqual(patched.json()["data"]["settings"]["models.ask"], "openai-codex/gpt-5.4")

        empty_patch = self.client.patch("/v1/config", json={}, headers=self._auth())
        self.assertEqual(empty_patch.status_code, 200)
        self.assertIn("settings", empty_patch.json()["data"])

    def test_providers_list_logout_and_errors(self):
        listed = self.client.get("/v1/providers", headers=self._auth())
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["data"]["providers"][0]["providerId"], "openai-codex")

        logged_out = self.client.delete("/v1/providers/openai-codex", headers=self._auth())
        self.assertEqual(logged_out.json()["data"]["status"], "disconnected")

        self.fake_pi.fail_providers = True
        providers_error = self.client.get("/v1/providers", headers=self._auth())
        self.assertEqual(providers_error.status_code, 500)
        self.assertEqual(providers_error.json()["error"]["code"], "PI_ERROR")

        self.fake_pi.fail_logout = True
        logout_error = self.client.delete("/v1/providers/openai-codex", headers=self._auth())
        self.assertEqual(logout_error.status_code, 500)
        self.assertEqual(logout_error.json()["error"]["code"], "PI_ERROR")

    def test_provider_login_uses_runtime_lock_and_handles_errors(self):
        manager, process = self._session_manager()
        lock_calls = []
        original_execute_locked = self.seam.execute_locked

        def wrapped(fn):
            lock_calls.append("locked")
            return original_execute_locked(fn)

        self.seam.execute_locked = wrapped
        response = self.client.post(
            "/v1/providers/openai-codex/login",
            json={"method": "browser"},
            headers=self._auth(),
        )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(lock_calls)
        session_id = response.json()["data"]["session_id"]

        conflict = self.client.post(
            "/v1/providers/openai-codex/login",
            json={"method": "browser"},
            headers=self._auth(),
        )
        self.assertEqual(conflict.status_code, 409)

        invalid = self.client.post(
            "/v1/providers/openai-codex/login",
            json={"method": "invalid"},
            headers=self._auth(),
        )
        self.assertEqual(invalid.status_code, 400)
        manager.cancel_session(session_id)
        process.terminate()

    def test_auth_session_poll_code_cancel_and_terminal_conflict(self):
        holder = {"process": None}

        def on_write(data):
            if '"type": "code"' in data:
                holder["process"].complete({"type": "completed"})

        holder["process"] = _FakeProcess(on_write=on_write)
        holder["process"].stdout.push(json.dumps({"type": "waiting", "prompt": "Enter code"}))
        self._session_manager(holder["process"], timeout=2)

        created = self.client.post(
            "/v1/providers/openai-codex/login",
            json={"method": "browser"},
            headers=self._auth(),
        )
        session_id = created.json()["data"]["session_id"]

        deadline = time.monotonic() + 1
        poll = None
        while time.monotonic() < deadline:
            poll = self.client.get(f"/v1/auth-sessions/{session_id}", headers=self._auth())
            if poll.json()["data"]["state"] == "waiting_code":
                break
            time.sleep(0.02)
        self.assertEqual(poll.json()["data"]["state"], "waiting_code")

        code = self.client.post(
            f"/v1/auth-sessions/{session_id}/code",
            json={"code": "123456"},
            headers=self._auth(),
        )
        self.assertEqual(code.status_code, 200)

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            poll = self.client.get(f"/v1/auth-sessions/{session_id}", headers=self._auth())
            if poll.json()["data"]["state"] == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(poll.json()["data"]["state"], "completed")

        cancel_completed = self.client.delete(f"/v1/auth-sessions/{session_id}", headers=self._auth())
        self.assertEqual(cancel_completed.status_code, 409)
        self.assertEqual(cancel_completed.json()["error"]["code"], "CONFLICT")

        not_found = self.client.get("/v1/auth-sessions/missing", headers=self._auth())
        self.assertEqual(not_found.status_code, 404)

    def test_auth_session_cancel_success(self):
        manager, process = self._session_manager(timeout=2)
        created = self.client.post(
            "/v1/providers/openai-codex/login",
            json={"method": "browser"},
            headers=self._auth(),
        )
        session_id = created.json()["data"]["session_id"]

        cancelled = self.client.delete(f"/v1/auth-sessions/{session_id}", headers=self._auth())
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["data"]["status"], "cancelled")
        self.assertTrue(process.stdin.writes)
        self.assertIn('"type": "cancel"', process.stdin.writes[0])
        manager.cleanup_all()

    def test_auth_session_expired_get_returns_gone_failure_envelope(self):
        manager, _process = self._session_manager(timeout=0.05)
        created = self.client.post(
            "/v1/providers/openai-codex/login",
            json={"method": "browser"},
            headers=self._auth(),
        )
        session_id = created.json()["data"]["session_id"]

        deadline = time.monotonic() + 1
        response = None
        while time.monotonic() < deadline:
            response = self.client.get(f"/v1/auth-sessions/{session_id}", headers=self._auth())
            if response.status_code == 410:
                break
            time.sleep(0.02)
        self.assertEqual(response.status_code, 410)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "GONE")
        self.assertEqual(body["error"]["details"]["state"], "expired")

        expired_cancel = self.client.delete(f"/v1/auth-sessions/{session_id}", headers=self._auth())
        self.assertEqual(expired_cancel.status_code, 410)
        self.assertEqual(expired_cancel.json()["error"]["code"], "GONE")
        manager.expire_stale()

    def test_daemon_status_and_stop(self):
        status = self.client.get("/v1/daemon", headers=self._auth())
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["data"]["api_url"], API_URL)

        stop = self.client.post("/v1/daemon/stop", headers=self._auth())
        self.assertEqual(stop.status_code, 200)
        self.assertEqual(stop.json()["data"]["status"], "stopping")

    def test_partial_failure_envelope(self):
        self.fake_app.partial_index = True
        resp = self.client.post(
            "/v1/documents/index",
            json={"paths": ["good.md", "bad.md"], "no_tag": True},
            headers=self._auth(),
        )
        self.assertEqual(resp.status_code, 207)
        self.assertEqual(resp.json()["error"]["code"], "PARTIAL_FAILURE")
