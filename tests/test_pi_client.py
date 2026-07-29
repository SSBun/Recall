import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from recall.pi_client import PiClient, PiInvocationError, TaggingInput


def make_fake_bridge(directory: str) -> Path:
    script = Path(directory) / "model_bridge.py"
    script.write_text(
        """import json
import os
import sys
request = json.load(sys.stdin)
if os.environ.get("FAKE_BRIDGE_FAIL"):
    print(json.dumps({"version": 1, "ok": False, "error": {"message": "provider failed"}}))
    raise SystemExit(1)
print(json.dumps({"version": 1, "ok": True, "text": os.environ["FAKE_MODEL_RESPONSE"]}))
""",
        encoding="utf-8",
    )
    return script


class PiClientTests(unittest.TestCase):
    def _assert_login_session_streams_first_event(self, bridge_path: Path) -> None:
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
                self.fail(f"login-session did not emit an event in time: stdout={stdout!r} stderr={stderr!r}")

            line = holder["line"]
            if not line:
                stdout, stderr = process.communicate(timeout=5)
                self.fail(f"login-session ended before emitting an event: stdout={stdout!r} stderr={stderr!r}")

            event = json.loads(line)
            self.assertIn(event["type"], {"auth_url", "info", "progress", "device_code", "waiting"})
            process.stdin.write(json.dumps({"type": "cancel"}) + "\n")
            process.stdin.flush()
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
            self.assertNotIn("Cannot find module", line + stdout + stderr)

    def test_lists_available_models_from_bridge(self):
        client = PiClient(auth_path=Path("/tmp/recall-auth.json"))
        with patch.object(
            client,
            "_invoke_bridge",
            return_value={
                "data": {
                    "models": [
                        "openai-codex/gpt-5.4",
                        "openai-codex/gpt-5.4-mini",
                    ]
                }
            },
        ) as invoke:
            models = client.list_available_models()

        self.assertEqual(
            models,
            ["openai-codex/gpt-5.4", "openai-codex/gpt-5.4-mini"],
        )
        invoke.assert_called_once_with(
            ["model", "list", "/tmp/recall-auth.json"]
        )

    def test_packaged_bridge_starts_without_external_pi(self):
        with self.assertRaisesRegex(PiInvocationError, "模型不存在"):
            PiClient().ask("question", model="missing/model")

    def test_packaged_bridge_login_session_loader_streams_first_event(self):
        self._assert_login_session_streams_first_event(
            Path(__file__).parents[1] / "src/recall/model_bridge.mjs"
        )

    def test_packaged_bridge_loads_codex_oauth_before_prompting(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge_path = Path(__file__).parents[1] / "src/recall/model_bridge.mjs"
            result = subprocess.run(
                [
                    "node",
                    str(bridge_path),
                    "provider",
                    "login",
                    "openai-codex",
                    str(Path(directory) / "auth.json"),
                ],
                input="",
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )

        self.assertNotIn("Cannot find module", result.stdout + result.stderr)
        self.assertIn("Select OpenAI Codex login method", result.stderr)

    def test_packaged_bridge_lists_and_removes_recall_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            client = PiClient(auth_path=Path(directory) / "auth.json")

            self.assertEqual(client.provider_list(), {"providers": []})
            self.assertEqual(
                client.provider_logout("openai-codex"),
                {"provider": "openai-codex", "status": "disconnected"},
            )

    def _client(self, directory: str) -> PiClient:
        return PiClient(
            node_executable=sys.executable,
            bridge_path=make_fake_bridge(directory),
            auth_path=Path(directory) / "auth.json",
        )

    def test_validates_each_document_in_a_tagging_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            response = {
                "documents": [
                    {
                        "request_id": "req_1",
                        "category": " engineering ",
                        "tags": ["rag", "rag", " chroma "],
                        "summary": " RAG notes ",
                    },
                    {
                        "request_id": "req_2",
                        "category": "",
                        "tags": [],
                        "summary": "invalid",
                    },
                ]
            }
            inputs = [
                TaggingInput("req_1", "/one.md", "one"),
                TaggingInput("req_2", "/two.md", "two"),
            ]

            with patch.dict(
                os.environ, {"FAKE_MODEL_RESPONSE": json.dumps(response)}
            ):
                result = self._client(directory).tag_documents(
                    inputs, model="openai/tag-model"
                )

            self.assertEqual(result.tags["req_1"].category, "engineering")
            self.assertEqual(result.tags["req_1"].tags, ["rag", "chroma"])
            self.assertEqual(result.tags["req_1"].summary, "RAG notes")
            self.assertEqual(result.errors["req_2"], "TAGGING_FAILED")

    def test_rejects_malformed_request_ids_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            response = {
                "documents": [
                    {
                        "request_id": ["req_1"],
                        "category": "engineering",
                        "tags": ["rag"],
                        "summary": "summary",
                    }
                ]
            }
            inputs = [TaggingInput("req_1", "/one.md", "one")]

            with patch.dict(
                os.environ, {"FAKE_MODEL_RESPONSE": json.dumps(response)}
            ):
                result = self._client(directory).tag_documents(inputs)

            self.assertEqual(result.errors, {"req_1": "TAGGING_FAILED"})

    def test_marks_bridge_failures_as_pi_error(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs = [TaggingInput("req_1", "/one.md", "one")]

            with patch.dict(os.environ, {"FAKE_BRIDGE_FAIL": "1"}):
                result = self._client(directory).tag_documents(inputs)

            self.assertEqual(result.errors, {"req_1": "PI_ERROR"})

    def test_marks_the_whole_batch_failed_when_model_returns_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs = [TaggingInput("req_1", "/one.md", "one")]

            with patch.dict(os.environ, {"FAKE_MODEL_RESPONSE": "not-json"}):
                result = self._client(directory).tag_documents(inputs)

            self.assertEqual(result.tags, {})
            self.assertEqual(result.errors, {"req_1": "TAGGING_FAILED"})
