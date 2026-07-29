import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recall.config import (
    ConfigError,
    get_config_settings,
    resolve_concurrency,
    resolve_model,
    resolve_search_limit,
    set_config_value,
)


class ResolveConcurrencyTests(unittest.TestCase):
    def test_uses_confirmed_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text("[index]\nconcurrency = 2\n", encoding="utf-8")

            with patch.dict(os.environ, {"RECALL_INDEX_CONCURRENCY": "3"}):
                self.assertEqual(resolve_concurrency(4, config_path), 4)
                self.assertEqual(resolve_concurrency(None, config_path), 3)

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(resolve_concurrency(None, config_path), 2)
                self.assertEqual(
                    resolve_concurrency(None, Path(directory) / "missing.toml"), 4
                )

    def test_rejects_non_positive_values(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text("[index]\nconcurrency = 0\n", encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "正整数"):
                resolve_concurrency(None, config_path)

            config_path.write_text("[index]\nconcurrency = 2.5\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "正整数"):
                resolve_concurrency(None, config_path)


class ResolveSearchLimitTests(unittest.TestCase):
    def test_uses_cli_config_and_default_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text("[search]\nlimit = 8\n", encoding="utf-8")

            self.assertEqual(resolve_search_limit(3, config_path), 3)
            self.assertEqual(resolve_search_limit(None, config_path), 8)
            self.assertEqual(
                resolve_search_limit(None, Path(directory) / "missing.toml"), 5
            )

    def test_rejects_non_positive_values(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text("[search]\nlimit = 0\n", encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "正整数"):
                resolve_search_limit(None, config_path)


class ConfigFileTests(unittest.TestCase):
    def test_sets_supported_values_without_rewriting_other_content(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "recall" / "config.toml"
            config_path.parent.mkdir()
            config_path.write_text(
                "# keep this comment\n[index]\nconcurrency = 7\n\n"
                "[custom]\nvalue = \"keep\"\n",
                encoding="utf-8",
            )

            set_config_value("models.tag", "openai-codex/gpt-5.4-mini", config_path)
            set_config_value("models.ask", "openai-codex/gpt-5.4", config_path)
            settings = set_config_value("search.limit", "9", config_path)

            self.assertEqual(
                settings,
                {
                    "models.tag": "openai-codex/gpt-5.4-mini",
                    "models.ask": "openai-codex/gpt-5.4",
                    "search.limit": 9,
                },
            )
            text = config_path.read_text(encoding="utf-8")
            self.assertIn("# keep this comment", text)
            self.assertIn("[index]\nconcurrency = 7", text)
            self.assertIn('[custom]\nvalue = "keep"', text)
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(get_config_settings(config_path), settings)

    def test_preserves_symlink_and_updates_its_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real.toml"
            link = root / "config.toml"
            target.write_text("[search]\nlimit = 3\n", encoding="utf-8")
            link.symlink_to(target)

            set_config_value("search.limit", "7", link)

            self.assertTrue(link.is_symlink())
            self.assertIn("limit = 7", target.read_text(encoding="utf-8"))
            self.assertEqual(get_config_settings(link)["search.limit"], 7)

    def test_inserts_missing_key_before_section_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                "[search]\n\n[models]\ntag = \"openai/gpt-4o-mini\"\n",
                encoding="utf-8",
            )

            set_config_value("search.limit", "7", config_path)

            self.assertIn(
                "[search]\nlimit = 7\n\n[models]",
                config_path.read_text(encoding="utf-8"),
            )

    def test_rejects_unknown_or_invalid_values_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text("# unchanged\n", encoding="utf-8")

            for key, value in (
                ("search.unknown", "3"),
                ("search.limit", "0"),
                ("models.ask", "missing-provider"),
            ):
                with self.subTest(key=key), self.assertRaises(ConfigError):
                    set_config_value(key, value, config_path)
                self.assertEqual(
                    config_path.read_text(encoding="utf-8"), "# unchanged\n"
                )

            config_path.write_text("[search]\nlimit = 0\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                set_config_value("models.ask", "openai/gpt-4o-mini", config_path)
            self.assertEqual(
                config_path.read_text(encoding="utf-8"),
                "[search]\nlimit = 0\n",
            )


class ResolveModelTests(unittest.TestCase):
    def test_uses_cli_environment_config_and_recall_default_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                '[models]\ntag = "anthropic/from-config"\n', encoding="utf-8"
            )

            with patch.dict(os.environ, {"RECALL_TAG_MODEL": "google/from-env"}):
                self.assertEqual(
                    resolve_model("openai/from-cli", "tag", config_path),
                    "openai/from-cli",
                )
                self.assertEqual(
                    resolve_model(None, "tag", config_path), "google/from-env"
                )

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    resolve_model(None, "tag", config_path), "anthropic/from-config"
                )
                self.assertEqual(
                    resolve_model(None, "ask", Path(directory) / "missing.toml"),
                    "openai/gpt-4o-mini",
                )

    def test_rejects_model_without_provider(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ConfigError, "provider/model"),
        ):
            resolve_model("gpt-4o-mini", "ask", Path(directory) / "missing")

        with self.assertRaisesRegex(ConfigError, "provider/model"):
            resolve_model("", "ask", Path("missing"))
