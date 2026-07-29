import tempfile
import unittest
from pathlib import Path

from recall.embedding import EMBEDDING_DIMENSIONS
from recall.pi_client import DocumentTags, TaggingResult
from recall.service import RecallApp
from recall.store import ChromaStore


def _embedding():
    return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


class FakeEmbedder:
    def encode_documents(self, texts):
        return [_embedding() for _ in texts]

    def encode_query(self, text):
        return _embedding()


class FakePi:
    def __init__(self, fail_names=()):
        self.fail_names = set(fail_names)
        self.tag_calls = 0
        self.ask_prompts = []

    def tag_documents(self, documents, model=None):
        self.tag_calls += 1
        tags = {}
        errors = {}
        for document in documents:
            if Path(document.path).name in self.fail_names:
                errors[document.request_id] = "TAGGING_FAILED"
            else:
                tags[document.request_id] = DocumentTags(
                    "engineering", ["rag"], f"Summary for {Path(document.path).name}"
                )
        return TaggingResult(tags, errors)

    def ask(self, prompt, model=None):
        self.ask_prompts.append(prompt)
        return "answer [1]"


class RecallIndexTests(unittest.TestCase):
    def test_index_is_idempotent_and_keeps_identity_across_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "old.md"
            source.write_text("alpha", encoding="utf-8")
            pi = FakePi()
            app = RecallApp(ChromaStore(root / "db"), FakeEmbedder(), pi)

            first = app.index([str(source)], concurrency=1)
            document_id = first["indexed"][0]["document_id"]
            self.assertEqual(pi.tag_calls, 1)

            second = app.index([str(source)], concurrency=1)
            self.assertEqual(second["unchanged"][0]["document_id"], document_id)
            self.assertEqual(pi.tag_calls, 1)

            renamed = root / "renamed.md"
            source.rename(renamed)
            third = app.index([str(renamed)], concurrency=1)
            self.assertEqual(third["indexed"][0]["status"], "renamed")
            self.assertEqual(third["indexed"][0]["document_id"], document_id)
            self.assertEqual(pi.tag_calls, 1)

            renamed.write_text("changed", encoding="utf-8")
            fourth = app.index([str(renamed)], no_tag=True, concurrency=1)
            self.assertEqual(fourth["indexed"][0]["document_id"], document_id)
            record = app.show(document_id)
            self.assertEqual(record["tags"], ["rag"])
            self.assertEqual(record["summary"], "Summary for old.md")

    def test_no_tag_is_empty_for_new_document_and_batch_failures_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            untagged = root / "untagged.md"
            good = root / "good.md"
            bad = root / "bad.md"
            for path in (untagged, good, bad):
                path.write_text(path.stem, encoding="utf-8")

            pi = FakePi(fail_names={"bad.md"})
            app = RecallApp(ChromaStore(root / "db"), FakeEmbedder(), pi)

            no_tag = app.index([str(untagged)], no_tag=True, concurrency=1)
            untagged_id = no_tag["indexed"][0]["document_id"]
            self.assertEqual(app.show(untagged_id)["tags"], [])
            self.assertEqual(pi.tag_calls, 0)

            result = app.index([str(good), str(bad)], concurrency=2)
            self.assertEqual(
                [item["path"] for item in result["failed"]], [str(bad.resolve())]
            )
            self.assertEqual(result["failed"][0]["code"], "TAGGING_FAILED")
            self.assertEqual(len(result["indexed"]), 1)
            self.assertEqual(len(app.list_documents()), 2)

    def test_invalid_embedding_batch_is_reported_as_embedding_failure(self):
        class BrokenEmbedder(FakeEmbedder):
            def encode_documents(self, texts):
                return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "note.md"
            source.write_text("text", encoding="utf-8")
            app = RecallApp(ChromaStore(root / "db"), BrokenEmbedder(), FakePi())

            result = app.index([str(source)], no_tag=True, concurrency=1)

            self.assertEqual(result["failed"][0]["code"], "EMBEDDING_FAILED")
            self.assertEqual(app.list_documents(), [])

    def test_invalid_pdf_does_not_stop_other_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "good.md"
            bad = root / "bad.pdf"
            good.write_text("good", encoding="utf-8")
            bad.write_bytes(b"not-a-pdf")
            app = RecallApp(ChromaStore(root / "db"), FakeEmbedder(), FakePi())

            result = app.index([str(good), str(bad)], no_tag=True, concurrency=2)

            self.assertEqual(len(result["indexed"]), 1)
            self.assertEqual(result["failed"][0]["code"], "SOURCE_ERROR")
            self.assertEqual(result["failed"][0]["path"], str(bad.resolve()))

    def test_explicit_document_id_handles_move_and_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.md"
            old.write_text("old", encoding="utf-8")
            app = RecallApp(ChromaStore(root / "db"), FakeEmbedder(), FakePi())
            document_id = app.index([str(old)], concurrency=1)["indexed"][0][
                "document_id"
            ]

            moved = root / "moved.md"
            old.rename(moved)
            moved.write_text("new", encoding="utf-8")
            result = app.index(
                [str(moved)], document_id=document_id, no_tag=True, concurrency=1
            )

            self.assertEqual(result["indexed"][0]["document_id"], document_id)
            self.assertEqual(app.show(document_id)["path"], str(moved.resolve()))
