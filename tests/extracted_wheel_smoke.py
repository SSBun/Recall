import json
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path


def _first_wheel() -> Path:
    wheels = sorted(Path("dist").glob("recall_rag-*.whl"))
    if not wheels:
        raise SystemExit("No built wheel found under dist/")
    return wheels[-1]


def _assert_login_session_streams_first_event(bridge_path: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        auth_path = Path(directory) / "auth.json"
        process = subprocess.Popen(
            [
                "node",
                str(bridge_path),
                "provider",
                "login-session",
                "openai-codex",
                str(auth_path),
                "browser",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        holder: dict[str, str | None] = {"line": None}

        def read_first_line() -> None:
            holder["line"] = process.stdout.readline() if process.stdout is not None else None

        thread = threading.Thread(target=read_first_line, daemon=True)
        thread.start()
        thread.join(timeout=20)
        if thread.is_alive():
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            raise RuntimeError(f"login-session did not emit an event in time: stdout={stdout!r} stderr={stderr!r}")

        line = holder["line"]
        if not line:
            stdout, stderr = process.communicate(timeout=5)
            raise RuntimeError(f"login-session ended before emitting an event: stdout={stdout!r} stderr={stderr!r}")

        event = json.loads(line)
        if event.get("type") not in {"auth_url", "info", "progress", "device_code", "waiting"}:
            raise RuntimeError(f"unexpected login-session event: {event!r}")
        process.stdin.write(json.dumps({"type": "cancel"}) + "\n")
        process.stdin.flush()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
        if "Cannot find module" in line + stdout + stderr:
            raise RuntimeError(f"packaged login-session hit loader failure: {stderr}")
        return {"firstEvent": event.get("type"), "returncode": process.returncode}


def main() -> int:
    wheel = Path(sys.argv[1]) if len(sys.argv) > 1 else _first_wheel()
    with tempfile.TemporaryDirectory() as directory:
        extract_root = Path(directory) / "wheel"
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(extract_root)
        sys.path.insert(0, str(extract_root))

        from fastapi.testclient import TestClient

        from recall.http_app import RuntimeSeam, build_http_app

        class FakeApp:
            def list_documents(self):
                return []

            def show(self, document_id):
                return {"document_id": document_id, "path": "/tmp/note.md", "chunk_count": 1}

            def index(self, paths, **options):
                return {"concurrency": options.get("concurrency", 4), "indexed": [], "unchanged": [], "failed": []}

            def remove(self, document_ids):
                return {"removed": list(document_ids), "failed": []}

            def retag(self, document_ids, **options):
                return {"updated": list(document_ids), "failed": []}

            def search(self, query, **options):
                return [{
                    "document_id": "doc_1",
                    "chunk_id": "chunk_0",
                    "path": "/tmp/note.md",
                    "content": "wheel hit",
                    "distance": 0.1,
                    "metadata": {"category": "test", "tags": ["wheel"], "summary": "wheel summary", "chunk_index": 0},
                }]

            def ask(self, question, **options):
                return {"answer": "wheel answer", "used_general_knowledge": False, "sources": []}

        bridge_path = extract_root / "recall" / "model_bridge.mjs"
        dashboard_html = extract_root / "recall" / "dashboard" / "index.html"
        dashboard_js = extract_root / "recall" / "dashboard" / "app.js"
        dashboard_css = extract_root / "recall" / "dashboard" / "app.css"
        assert bridge_path.exists(), bridge_path
        assert dashboard_html.exists(), dashboard_html
        assert dashboard_js.exists(), dashboard_js
        assert dashboard_css.exists(), dashboard_css

        app = build_http_app(
            RuntimeSeam(FakeApp(), Path("/tmp/store")),
            token="wheel-token",
            api_url="http://127.0.0.1:9123",
        )
        client = TestClient(app, base_url="http://127.0.0.1:9123", raise_server_exceptions=False)
        root = client.get("/")
        health = client.get("/v1/health", headers={"Authorization": "Bearer wheel-token"})
        search = client.post(
            "/v1/search",
            json={"query": "wheel"},
            headers={"Authorization": "Bearer wheel-token"},
        )
        bridge = _assert_login_session_streams_first_event(bridge_path)
        print(json.dumps({
            "wheel": str(wheel),
            "rootStatus": root.status_code,
            "health": health.json(),
            "search": search.json(),
            "bridge": bridge,
            "assets": [bridge_path.name, dashboard_html.name, dashboard_js.name, dashboard_css.name],
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
