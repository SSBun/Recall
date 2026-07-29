"""Dashboard command tests."""

import io
import json
import unittest
from unittest.mock import patch

from recall.cli import run


class DashboardCliTests(unittest.TestCase):
    def test_dashboard_help_is_english(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "recall", "dashboard", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("dashboard", result.stdout)
        self.assertNotIn("中文", result.stdout)

    def test_dashboard_json_returns_url_without_browser(self):
        class FakeDaemon:
            def ensure_running(self):
                return {
                    "store": "/tmp/store",
                    "status": "running",
                    "pid": 42,
                    "api_url": "http://127.0.0.1:8080",
                }

        stdout = io.StringIO()
        exit_code = run(
            ["dashboard", "--json"],
            daemon_factory=lambda _store: FakeDaemon(),
            stdout=stdout,
            stderr=io.StringIO(),
        )
        self.assertEqual(exit_code, 0)
        body = json.loads(stdout.getvalue())
        self.assertEqual(body["data"]["dashboard_url"], "http://127.0.0.1:8080/")
        self.assertEqual(body["data"]["api_url"], "http://127.0.0.1:8080")

    def test_dashboard_human_mode_uses_stdlib_webbrowser_by_default(self):
        class FakeDaemon:
            def ensure_running(self):
                return {
                    "store": "/tmp/store",
                    "status": "running",
                    "pid": 42,
                    "api_url": "http://127.0.0.1:8080",
                }

        stdout = io.StringIO()
        with patch("webbrowser.open") as open_browser:
            exit_code = run(
                ["dashboard"],
                daemon_factory=lambda _store: FakeDaemon(),
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 0)
        open_browser.assert_called_once_with("http://127.0.0.1:8080/")
        self.assertIn("http://127.0.0.1:8080", stdout.getvalue())

    def test_dashboard_human_mode_injected_opener_is_for_tests(self):
        class FakeDaemon:
            def ensure_running(self):
                return {
                    "store": "/tmp/store",
                    "status": "running",
                    "pid": 42,
                    "api_url": "http://127.0.0.1:8080",
                }

        opened = []
        exit_code = run(
            ["dashboard"],
            daemon_factory=lambda _store: FakeDaemon(),
            browser_opener=lambda url: opened.append(url),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(opened, ["http://127.0.0.1:8080/"])

    def test_dashboard_json_does_not_open_browser(self):
        class FakeDaemon:
            def ensure_running(self):
                return {
                    "store": "/tmp/store",
                    "status": "running",
                    "pid": 42,
                    "api_url": "http://127.0.0.1:8080",
                }

        with patch("webbrowser.open") as open_browser:
            run(
                ["dashboard", "--json"],
                daemon_factory=lambda _store: FakeDaemon(),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        open_browser.assert_not_called()

    def test_dashboard_command_appears_in_top_level_help(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "recall", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("dashboard", result.stdout)
        self.assertIn("Open the web dashboard", result.stdout)
