import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from recall.daemon import DaemonClient, daemon_paths, serve


class _App:
    def __init__(self):
        self.list_calls = 0

    def list_documents(self):
        self.list_calls += 1
        return []

    def index(self, paths, **options):
        return {
            "concurrency": options["concurrency"],
            "indexed": [],
            "unchanged": [],
            "failed": [{"path": paths[0], "code": "SOURCE_ERROR"}],
        }


class DaemonTests(unittest.TestCase):
    def test_store_path_determines_runtime_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = daemon_paths(root / "store-a", root / "runtime")
            same = daemon_paths(root / "store-a/../store-a", root / "runtime")
            second = daemon_paths(root / "store-b", root / "runtime")

            self.assertEqual(first.socket, same.socket)
            self.assertNotEqual(first.socket, second.socket)

    def test_reuses_one_app_and_exits_after_idle_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            store = Path(directory) / "store"
            apps = []

            def app_factory(_store):
                app = _App()
                apps.append(app)
                return app

            thread = threading.Thread(
                target=serve,
                kwargs={
                    "store": store,
                    "runtime_root": root,
                    "idle_timeout": 0.2,
                    "app_factory": app_factory,
                },
            )
            thread.start()
            self._wait_for_socket(daemon_paths(store, root).socket)
            client = DaemonClient(store, runtime_root=root)

            self.assertEqual(client.request(["list"]), {"documents": []})
            self.assertEqual(client.request(["list"]), {"documents": []})
            partial = client.request(["index", "missing.md", "--no-tag"])
            self.assertEqual(partial["failed"][0]["code"], "SOURCE_ERROR")
            self.assertEqual(len(apps), 1)
            self.assertEqual(apps[0].list_calls, 2)

            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertFalse(daemon_paths(store, root).socket.exists())

    def test_autostart_is_singleton_and_isolates_stores(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory) / "runtime"
            first = DaemonClient(Path(directory) / "store-a", runtime_root=root)
            second = DaemonClient(Path(directory) / "store-b", runtime_root=root)
            root.mkdir(mode=0o700)
            first.paths.socket.touch()

            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(first.request, [["list"], ["list"]]))
                self.assertEqual(results, [{"documents": []}, {"documents": []}])
                first_status = first.status()
                note = Path(directory) / "note.md"
                note.write_text("daemon embedding reuse", encoding="utf-8")
                with patch.dict(os.environ, {"RECALL_INDEX_CONCURRENCY": "7"}):
                    indexed = first.request(
                        ["index", str(note), "--no-tag"]
                    )
                self.assertEqual(indexed["concurrency"], 7)

                self.assertEqual(second.request(["list"]), {"documents": []})
                second_status = second.status()

                self.assertNotEqual(first.paths.socket, second.paths.socket)
                self.assertNotEqual(first_status["pid"], second_status["pid"])
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)
                self.assertEqual(first.paths.socket.stat().st_mode & 0o777, 0o600)
            finally:
                first.stop()
                second.stop()

    def test_stop_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            store = Path(directory) / "store"
            thread = threading.Thread(
                target=serve,
                kwargs={
                    "store": store,
                    "runtime_root": root,
                    "idle_timeout": 10,
                    "app_factory": lambda _store: _App(),
                },
            )
            thread.start()
            self._wait_for_socket(daemon_paths(store, root).socket)
            client = DaemonClient(store, runtime_root=root)

            self.assertEqual(client.stop()["status"], "stopped")
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(client.stop()["status"], "stopped")

    def _wait_for_socket(self, socket_path: Path) -> None:
        deadline = time.monotonic() + 2
        while not socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(socket_path.exists())
