import tempfile
import unittest
from pathlib import Path

from recall.embedding import EMBEDDING_DIMENSIONS
from recall.pi_client import DocumentTags, TaggingResult
from recall.service import RecallApp
from recall.store import ChromaStore


def _embedding():
    return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


class QueryEmbedder:
    def encode_documents(self, texts):
        return [_embedding() for _ in texts]

    def encode_query(self, text):
        return _embedding()


class QueryPi:
    def __init__(self):
        self.ask_prompts = []
        self.tag_version = 0

    def tag_documents(self, documents, model=None):
        self.tag_version += 1
        return TaggingResult(
            {
                item.request_id: DocumentTags(
                    "engineering",
                    ["rag", f"v{self.tag_version}"],
                    f"summary-v{self.tag_version}",
                )
                for item in documents
            },
            {},
        )

    def ask(self, prompt, model=None):
        self.ask_prompts.append(prompt)
        return "Recall uses Chroma [1]"


class RecallQueryTests(unittest.TestCase):
    def test_search_ask_retag_and_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "note.md"
            source.write_text("Recall uses Chroma for vectors.", encoding="utf-8")
            pi = QueryPi()
            app = RecallApp(ChromaStore(root / "db"), QueryEmbedder(), pi)
            document_id = app.index([str(source)], concurrency=1)["indexed"][0][
                "document_id"
            ]

            hits = app.search(
                "vector database", limit=5, category="engineering", tag="rag"
            )
            self.assertEqual(hits[0]["document_id"], document_id)
            self.assertEqual(hits[0]["content"], "Recall uses Chroma for vectors.")

            answer = app.ask("Which database?", limit=5)
            self.assertEqual(answer["answer"], "Recall uses Chroma [1]")
            self.assertFalse(answer["used_general_knowledge"])
            self.assertIn("只能依据", pi.ask_prompts[-1])
            self.assertEqual(answer["sources"][0]["reference"], 1)

            general = app.ask("Which database?", limit=5, allow_general_knowledge=True)
            self.assertTrue(general["used_general_knowledge"])
            self.assertIn("模型补充", pi.ask_prompts[-1])

            retagged = app.retag([document_id])
            self.assertEqual(retagged["updated"], [document_id])
            self.assertEqual(app.show(document_id)["tags"], ["rag", "v2"])

            removed = app.remove([document_id])
            self.assertEqual(removed["removed"], [document_id])
            self.assertEqual(app.list_documents(), [])
