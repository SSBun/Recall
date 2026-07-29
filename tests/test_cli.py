import io
import json
import tempfile
import unittest
from pathlib import Path

from recall.cli import run


class FakeApp:
    def __init__(self):
        self.calls = []

    def index(self, paths, **options):
        self.calls.append(("index", paths, options))
        return {
            "concurrency": options["concurrency"],
            "indexed": [
                {"document_id": "doc_1", "path": paths[0], "status": "indexed"}
            ],
            "unchanged": [],
            "failed": [],
        }

    def search(self, query, **options):
        self.calls.append(("search", query, options))
        return [{"document_id": "doc_1", "content": "hit"}]

    def ask(self, question, **options):
        self.calls.append(("ask", question, options))
        return {"answer": "answer", "sources": []}

    def list_documents(self):
        self.calls.append(("list",))
        return []


class FakeProviderClient:
    def __init__(self):
        self.calls = []

    def provider_login(self, provider_id):
        self.calls.append(("login", provider_id))
        return {"provider": provider_id, "status": "connected"}

    def provider_logout(self, provider_id):
        self.calls.append(("logout", provider_id))
        return {"provider": provider_id, "status": "disconnected"}

    def provider_list(self):
        self.calls.append(("list",))
        return {"providers": [{"providerId": "openai-codex", "type": "oauth"}]}


class CliTests(unittest.TestCase):
    def test_rag_command_uses_store_daemon(self):
        class FakeDaemon:
            def __init__(self):
                self.calls = []

            def request(self, arguments):
                self.calls.append(arguments)
                return {"documents": []}

        daemon = FakeDaemon()
        stdout = io.StringIO()

        exit_code = run(
            ["list", "--store", "/tmp/recall-store", "--json"],
            daemon_factory=lambda _store: daemon,
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            daemon.calls,
            [["list", "--store", "/tmp/recall-store", "--json"]],
        )
        self.assertEqual(json.loads(stdout.getvalue())["data"], {"documents": []})

    def test_config_list_and_set_are_direct_and_scriptable(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            stdout = io.StringIO()

            exit_code = run(
                ["config", "set", "search.limit", "8", "--json"],
                config_path=config_path,
                app_factory=lambda _store: self.fail("config created RAG app"),
                daemon_factory=lambda _store: self.fail("config started daemon"),
                stdout=stdout,
                stderr=io.StringIO(),
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["data"]["settings"]["search.limit"], 8)

            stdout = io.StringIO()
            self.assertEqual(
                run(
                    ["config", "list"],
                    config_path=config_path,
                    stdout=stdout,
                    stderr=io.StringIO(),
                ),
                0,
            )
            self.assertIn(f"Configuration: {config_path}", stdout.getvalue())
            self.assertIn("search.limit = 8", stdout.getvalue())

    def test_pure_config_runs_interactive_prompt(self):
        calls = []

        def run_prompt(config_path, stdin, stdout):
            calls.append((config_path, stdin, stdout))
            return 0

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            stdin = io.StringIO()
            stdout = io.StringIO()
            exit_code = run(
                ["config"],
                config_path=config_path,
                config_prompt_runner=run_prompt,
                daemon_factory=lambda _store: self.fail("config started daemon"),
                stdin=stdin,
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [(config_path, stdin, stdout)])

    def test_search_and_ask_use_configured_default_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text("[search]\nlimit = 7\n", encoding="utf-8")
            app = FakeApp()

            self.assertEqual(
                run(
                    ["search", "query"],
                    config_path=config_path,
                    app_factory=lambda _store: app,
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual(
                run(
                    ["ask", "question"],
                    config_path=config_path,
                    app_factory=lambda _store: app,
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )

        self.assertEqual(app.calls[0][2]["limit"], 7)
        self.assertEqual(app.calls[1][2]["limit"], 7)

    def test_daemon_status_and_stop_have_human_and_json_output(self):
        class FakeDaemon:
            def status(self):
                return {"store": "/tmp/store", "status": "running", "pid": 42}

            def stop(self):
                return {"store": "/tmp/store", "status": "stopped"}

        daemon = FakeDaemon()
        stdout = io.StringIO()
        self.assertEqual(
            run(
                ["daemon", "status", "--store", "/tmp/store"],
                daemon_factory=lambda _store: daemon,
                stdout=stdout,
                stderr=io.StringIO(),
            ),
            0,
        )
        self.assertEqual(stdout.getvalue(), "/tmp/store: 运行中 (PID 42)\n")

        stdout = io.StringIO()
        self.assertEqual(
            run(
                ["daemon", "stop", "--store", "/tmp/store", "--json"],
                daemon_factory=lambda _store: daemon,
                stdout=stdout,
                stderr=io.StringIO(),
            ),
            0,
        )
        self.assertEqual(json.loads(stdout.getvalue())["data"]["status"], "stopped")

    def test_index_json_exposes_machine_envelope_and_confirmed_options(self):
        app = FakeApp()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "note.md")
            exit_code = run(
                [
                    "index",
                    path,
                    "--no-tag",
                    "--concurrency",
                    "3",
                    "--store",
                    str(Path(directory) / "db"),
                    "--json",
                ],
                app_factory=lambda _store: app,
                stdout=stdout,
                stderr=stderr,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["version"], 1)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["concurrency"], 3)
        self.assertTrue(app.calls[0][2]["no_tag"])
        self.assertEqual(stderr.getvalue(), "")

    def test_shell_command_is_not_exposed(self):
        stderr = io.StringIO()

        exit_code = run(["shell"], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 2)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_search_json_wraps_results(self):
        app = FakeApp()
        stdout = io.StringIO()
        exit_code = run(
            ["search", "vector database", "--limit", "3", "--json"],
            app_factory=lambda _store: app,
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue())["data"]["results"][0]["content"], "hit"
        )
        self.assertEqual(app.calls[0][2]["limit"], 3)

    def test_ask_human_displays_answer_and_sources_without_json(self):
        class SourceApp(FakeApp):
            def ask(self, question, **options):
                return {
                    "answer": "答案 [1]",
                    "used_general_knowledge": False,
                    "sources": [{"reference": 1, "path": "/notes/one.md"}],
                }

        stdout = io.StringIO()
        exit_code = run(
            ["ask", "question"],
            app_factory=lambda _store: SourceApp(),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "答案 [1]\n\n来源：\n[1] /notes/one.md\n")
        self.assertNotIn("{", stdout.getvalue())

    def test_ask_passes_explicit_provider_model(self):
        app = FakeApp()
        stdout = io.StringIO()
        exit_code = run(
            ["ask", "question", "--model", "anthropic/test-model", "--json"],
            app_factory=lambda _store: app,
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(app.calls[0][2]["model"], "anthropic/test-model")
        self.assertEqual(json.loads(stdout.getvalue())["data"]["answer"], "answer")

    def test_missing_provider_command_displays_provider_help(self):
        stderr = io.StringIO()

        exit_code = run(["provider"], stdout=io.StringIO(), stderr=stderr)

        self.assertEqual(exit_code, 2)
        self.assertIn("usage: recall provider", stderr.getvalue())
        self.assertIn("login", stderr.getvalue())
        self.assertIn("USAGE_ERROR", stderr.getvalue())

    def test_provider_login_without_id_uses_interactive_selector(self):
        client = FakeProviderClient()

        exit_code = run(
            ["provider", "login"],
            provider_factory=lambda: client,
            provider_selector=lambda: "openai-codex",
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, [("login", "openai-codex")])

    def test_provider_login_without_id_rejects_json_mode(self):
        stdout = io.StringIO()

        exit_code = run(
            ["provider", "login", "--json"],
            provider_factory=FakeProviderClient,
            stdout=stdout,
            stderr=io.StringIO(),
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["code"], "USAGE_ERROR")

    def test_provider_login_uses_auth_client_without_creating_rag_app(self):
        client = FakeProviderClient()
        stdout = io.StringIO()

        exit_code = run(
            ["provider", "login", "openai-codex", "--json"],
            app_factory=lambda _store: self.fail("provider command created RAG app"),
            provider_factory=lambda: client,
            daemon_factory=lambda _store: self.fail("provider command started daemon"),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, [("login", "openai-codex")])
        self.assertEqual(
            json.loads(stdout.getvalue())["data"]["status"], "connected"
        )

    def test_provider_list_human_displays_connection_status(self):
        cases = [
            ([{"providerId": "openai-codex", "type": "oauth"}], "已连接"),
            ([], "未连接"),
        ]

        for providers, expected_status in cases:
            with self.subTest(status=expected_status):
                client = FakeProviderClient()
                client.provider_list = lambda providers=providers: {
                    "providers": providers
                }
                stdout = io.StringIO()

                exit_code = run(
                    ["provider", "list"],
                    provider_factory=lambda client=client: client,
                    stdout=stdout,
                    stderr=io.StringIO(),
                )

                self.assertEqual(exit_code, 0)
                self.assertEqual(
                    stdout.getvalue(),
                    f"OpenAI Codex（ChatGPT Plus/Pro OAuth）: {expected_status}\n",
                )
                self.assertNotIn("providerId", stdout.getvalue())
                self.assertNotIn("{", stdout.getvalue())

    def test_provider_list_never_returns_credentials(self):
        client = FakeProviderClient()
        stdout = io.StringIO()

        exit_code = run(
            ["provider", "list", "--json"],
            provider_factory=lambda: client,
            stdout=stdout,
            stderr=io.StringIO(),
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            payload["data"]["providers"],
            [{"providerId": "openai-codex", "type": "oauth"}],
        )
        self.assertNotIn("access", stdout.getvalue())
        self.assertNotIn("refresh", stdout.getvalue())

    def test_partial_index_failure_returns_nonzero_error_envelope(self):
        class PartialApp(FakeApp):
            def index(self, paths, **options):
                return {
                    "concurrency": options["concurrency"],
                    "indexed": [{"document_id": "doc_1", "path": paths[0]}],
                    "unchanged": [],
                    "failed": [{"path": paths[1], "code": "TAGGING_FAILED"}],
                }

        stdout = io.StringIO()
        exit_code = run(
            ["index", "good.md", "bad.md", "--json"],
            app_factory=lambda _store: PartialApp(),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "PARTIAL_FAILURE")
        self.assertEqual(
            payload["error"]["details"]["indexed"][0]["document_id"], "doc_1"
        )

    def test_invalid_tagging_options_return_json_usage_error(self):
        stdout = io.StringIO()
        exit_code = run(
            ["index", "note.md", "--no-tag", "--tag-model", "model", "--json"],
            app_factory=lambda _store: FakeApp(),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "USAGE_ERROR")
        self.assertIn("usage: recall index", payload["error"]["help"])
