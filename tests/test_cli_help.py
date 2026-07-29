import re
import subprocess
import sys
import unittest


class CliHelpTests(unittest.TestCase):
    def test_all_help_is_english(self):
        command_paths = [
            [],
            ["index"],
            ["remove"],
            ["list"],
            ["show"],
            ["search"],
            ["ask"],
            ["retag"],
            ["provider"],
            ["provider", "login"],
            ["provider", "logout"],
            ["provider", "list"],
            ["daemon"],
            ["daemon", "status"],
            ["daemon", "stop"],
            ["dashboard"],
            ["config"],
            ["config", "list"],
            ["config", "set"],
        ]

        for command_path in command_paths:
            with self.subTest(command=" ".join(command_path) or "recall"):
                result = subprocess.run(
                    [sys.executable, "-m", "recall", *command_path, "--help"],
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsNone(re.search(r"[\u3400-\u9fff]", result.stdout))
                self.assertEqual(result.stderr, "")

    def test_missing_command_errors_include_english_help(self):
        for command_path in ([], ["provider"], ["daemon"]):
            with self.subTest(command=" ".join(command_path) or "recall"):
                result = subprocess.run(
                    [sys.executable, "-m", "recall", *command_path],
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 2)
                self.assertIn("USAGE_ERROR", result.stderr)
                self.assertIsNone(re.search(r"[\u3400-\u9fff]", result.stderr))
