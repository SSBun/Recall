import tempfile
import unittest
from pathlib import Path

from recall.documents import SourceError, discover_files, prepare_file, split_text


class DocumentTests(unittest.TestCase):
    def test_discovers_supported_files_recursively(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.md").write_text("one", encoding="utf-8")
            (root / "skip.csv").write_text("skip", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "two.txt").write_text("two", encoding="utf-8")

            self.assertEqual(
                discover_files([str(root)], recursive=True),
                [(root / "nested" / "two.txt").resolve(), (root / "one.md").resolve()],
            )

            with self.assertRaisesRegex(SourceError, "--recursive"):
                discover_files([str(root)], recursive=False)

    def test_prepares_text_file_and_splits_with_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            path.write_text("A" * 500 + "B" * 100, encoding="utf-8")

            source = prepare_file(path)
            chunks = split_text(source.text, chunk_size=500, overlap=50)

            self.assertEqual(source.path, path.resolve())
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0], "A" * 500)
            self.assertEqual(chunks[1], "A" * 50 + "B" * 100)
