import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from recall.api_token import get_or_create_token


class ApiTokenTests(unittest.TestCase):
    def test_generates_new_token_with_0600_under_0700_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "recall" / "api-token"
            token = get_or_create_token(token_path)

            self.assertTrue(token)
            self.assertEqual(len(token), 43)
            self.assertTrue(token_path.exists())
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(token_path.parent.stat().st_mode & 0o777, 0o700)

    def test_reuses_existing_token(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "recall" / "api-token"
            first = get_or_create_token(token_path)
            second = get_or_create_token(token_path)
            self.assertEqual(first, second)

    def test_empty_token_file_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "recall" / "api-token"
            token_path.parent.mkdir(parents=True, mode=0o700)
            token_path.write_text("   \n", encoding="utf-8")

            token = get_or_create_token(token_path)
            self.assertTrue(token)
            self.assertNotEqual(token.strip(), "")

    def test_two_generations_produce_different_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path_a = Path(directory) / "a" / "api-token"
            token_path_b = Path(directory) / "b" / "api-token"
            self.assertNotEqual(get_or_create_token(token_path_a), get_or_create_token(token_path_b))

    def test_concurrent_first_creation_returns_one_shared_token(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "recall" / "api-token"
            counter = {"value": 0}
            counter_lock = threading.Lock()

            def fake_token_urlsafe(_size: int) -> str:
                with counter_lock:
                    counter["value"] += 1
                    value = counter["value"]
                time.sleep(0.02)
                return f"token-{value}"

            with (
                patch("recall.api_token.secrets.token_urlsafe", side_effect=fake_token_urlsafe),
                ThreadPoolExecutor(max_workers=8) as executor,
            ):
                tokens = list(executor.map(lambda _index: get_or_create_token(token_path), range(8)))

            self.assertEqual(len(set(tokens)), 1)
            self.assertEqual(token_path.read_text(encoding="utf-8"), tokens[0])
