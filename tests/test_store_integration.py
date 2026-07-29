import tempfile
import unittest
from pathlib import Path

from recall.embedding import EMBEDDING_DIMENSIONS, MODEL_NAME
from recall.store import ChromaStore, DocumentRecord, StoreError


def _vector(index: int = 0) -> list[float]:
    value = [0.0] * EMBEDDING_DIMENSIONS
    value[index] = 1.0
    return value


class ChromaStoreIntegrationTests(unittest.TestCase):
    def test_persists_searches_updates_and_removes_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "db"
            store = ChromaStore(store_path)
            document = DocumentRecord(
                document_id="doc_one",
                source_path="/notes/one.md",
                content_hash="hash-one",
                size=100,
                modified_ns=123,
                category="engineering",
                tags=["rag", "chroma"],
                summary="RAG notes",
                chunk_count=2,
            )

            store.upsert_document(
                document,
                ["alpha", "beta"],
                [_vector(0), _vector(1)],
            )

            reopened = ChromaStore(store_path)
            self.assertEqual(reopened.collection.metadata["embedding_model"], MODEL_NAME)
            self.assertEqual(
                reopened.collection.metadata["embedding_dimensions"],
                EMBEDDING_DIMENSIONS,
            )
            self.assertEqual(reopened.get_document("doc_one"), document)
            self.assertEqual(reopened.find_by_path("/notes/one.md"), document)
            self.assertEqual(reopened.find_by_hash("hash-one"), [document])
            self.assertEqual(reopened.list_documents(), [document])

            hits = reopened.search(
                _vector(0), limit=1, category="engineering", tag="rag"
            )
            self.assertEqual(hits[0].document_id, "doc_one")
            self.assertEqual(hits[0].content, "alpha")
            self.assertAlmostEqual(hits[0].distance, 0.0)

            reopened.update_path("doc_one", "/notes/renamed.md")
            reopened.update_tags("doc_one", "knowledge", ["updated"], "Updated")
            updated = reopened.get_document("doc_one")
            self.assertEqual(updated.source_path, "/notes/renamed.md")
            self.assertEqual(updated.tags, ["updated"])

            reopened.upsert_document(
                DocumentRecord(**{**updated.__dict__, "chunk_count": 1}),
                ["replacement"],
                [_vector()],
            )
            self.assertEqual(reopened.get_document("doc_one").chunk_count, 1)

            reopened.delete_document("doc_one")
            self.assertIsNone(reopened.get_document("doc_one"))

    def test_rejects_nonempty_store_without_embedding_metadata(self):
        import chromadb

        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "db"
            client = chromadb.PersistentClient(path=str(store_path))
            collection = client.get_or_create_collection(
                name="recall_chunks",
                embedding_function=None,
                configuration={"hnsw": {"space": "cosine"}},
            )
            collection.add(
                ids=["legacy:0"],
                documents=["legacy"],
                embeddings=[_vector()],
            )

            with self.assertRaisesRegex(StoreError, "embedding 配置不兼容"):
                ChromaStore(store_path)

    def test_rejects_wrong_embedding_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChromaStore(Path(directory) / "db")
            document = DocumentRecord(
                document_id="doc_one",
                source_path="/notes/one.md",
                content_hash="hash-one",
                size=100,
                modified_ns=123,
                category="",
                tags=[],
                summary="",
                chunk_count=1,
            )

            with self.assertRaisesRegex(StoreError, "1024"):
                store.upsert_document(document, ["alpha"], [[1.0, 0.0]])
            with self.assertRaisesRegex(StoreError, "1024"):
                store.search([1.0, 0.0], limit=1)
