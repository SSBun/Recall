import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cmd2

from recall.config import get_config_settings
from recall.config_prompt import _select, _select_model, run_config_prompt


class ConfigPromptTests(unittest.TestCase):
    def test_menu_edits_settings_and_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            stdin = io.StringIO(
                "1\n6\n"
                "2\n1\n"
                "3\n2\n"
                "4\n"
            )
            stdout = io.StringIO()
            available_models = [
                "openai-codex/gpt-5.4-mini",
                "openai-codex/gpt-5.4",
            ]

            exit_code = run_config_prompt(
                config_path,
                stdin,
                stdout,
                model_lister=lambda: available_models,
            )

            self.assertEqual(exit_code, 0)
            settings = get_config_settings(config_path)
            self.assertEqual(settings["search.limit"], 6)
            self.assertEqual(
                settings["models.tag"], "openai-codex/gpt-5.4-mini"
            )
            self.assertEqual(settings["models.ask"], "openai-codex/gpt-5.4")
            output = stdout.getvalue()
            self.assertIn("┌  Recall setup", output)
            self.assertIn("◆  Configuration:", output)
            self.assertIn("● Edit search limit (5)", output)
            self.assertIn("○ Edit tagging model", output)
            self.assertIn("◆  Select tagging model:", output)
            self.assertIn("◆  Select ask model:", output)
            for model in available_models:
                self.assertIn(model, output)
            self.assertTrue(output.rstrip().endswith("└"))

    def test_tty_menu_uses_interactive_selector(self):
        stdin = io.StringIO()
        stdout = io.StringIO()
        prompt = cmd2.Cmd(stdin=stdin, stdout=stdout, allow_cli_args=False)
        options = [("search.limit", "Edit search limit (5)"), ("exit", "Exit")]

        with (
            patch("recall.config_prompt._is_tty", return_value=True),
            patch.object(prompt, "select", return_value="search.limit") as select,
        ):
            selected = _select(prompt, options, stdin, stdout)

        self.assertEqual(selected, "search.limit")
        select.assert_called_once_with(options, prompt="◆  Configuration:")

    def test_tty_model_menu_lists_all_available_models(self):
        stdin = io.StringIO()
        stdout = io.StringIO()
        prompt = cmd2.Cmd(stdin=stdin, stdout=stdout, allow_cli_args=False)
        models = ["provider/model-b", "provider/model-a"]

        with (
            patch("recall.config_prompt._is_tty", return_value=True),
            patch.object(prompt, "select", return_value=models[1]) as select,
        ):
            selected = _select_model(
                prompt,
                "models.ask",
                models[0],
                lambda: models,
                stdin,
                stdout,
            )

        self.assertEqual(selected, models[1])
        self.assertEqual(
            select.call_args.args[0],
            [
                (models[0], f"{models[0]} (current)"),
                (models[1], models[1]),
                (None, "Back"),
            ],
        )
        self.assertEqual(
            select.call_args.kwargs["prompt"], "◆  Select ask model:"
        )

    def test_model_menu_explains_when_no_provider_is_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()

            exit_code = run_config_prompt(
                Path(directory) / "config.toml",
                io.StringIO("2\n4\n"),
                stdout,
                model_lister=list,
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("No available models", stdout.getvalue())

    def test_menu_rejects_non_menu_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()

            exit_code = run_config_prompt(
                Path(directory) / "config.toml",
                io.StringIO("shell\n4\n"),
                stdout,
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("Invalid selection", stdout.getvalue())
