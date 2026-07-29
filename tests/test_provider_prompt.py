import unittest
from unittest.mock import patch

from recall.provider_prompt import PROVIDER_OPTIONS, select_provider


class ProviderPromptTests(unittest.TestCase):
    def test_selects_supported_auth_provider_with_cmd2(self):
        with patch("recall.provider_prompt.cmd2.Cmd") as cmd:
            cmd.return_value.select.return_value = "openai-codex"

            selected = select_provider()

        self.assertEqual(selected, "openai-codex")
        cmd.return_value.select.assert_called_once_with(
            PROVIDER_OPTIONS,
            prompt="选择要登录的供应商：",
        )
