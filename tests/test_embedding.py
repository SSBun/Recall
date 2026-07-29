import os
import sys
import types
import unittest
from unittest.mock import patch

from recall.embedding import MODEL_NAME, QwenEmbedder


class _Vectors:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class _Model:
    def __init__(self):
        self.calls = []

    def encode_document(self, texts, **options):
        self.calls.append(("document", texts, options))
        return _Vectors([[1.0, 0.0]])

    def encode_query(self, text, **options):
        self.calls.append(("query", text, options))
        return _Vectors([0.0, 1.0])


class EmbeddingTests(unittest.TestCase):
    def test_uses_qwen_document_and_query_encoders_without_progress(self):
        model = _Model()
        load_calls = []

        def load_model(name, **options):
            load_calls.append((name, options))
            return model

        module = types.SimpleNamespace(SentenceTransformer=load_model)
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.dict(sys.modules, {"sentence_transformers": module}),
        ):
            embedder = QwenEmbedder()
            self.assertEqual(embedder.encode_documents(["document"]), [[1.0, 0.0]])
            self.assertEqual(embedder.encode_query("query"), [0.0, 1.0])

            self.assertEqual(
                load_calls, [(MODEL_NAME, {"local_files_only": True})]
            )
            self.assertEqual([call[0] for call in model.calls], ["document", "query"])
            for _, _, options in model.calls:
                self.assertTrue(options["normalize_embeddings"])
                self.assertFalse(options["show_progress_bar"])
            self.assertEqual(os.environ["HF_HUB_DISABLE_PROGRESS_BARS"], "1")
            self.assertEqual(os.environ["HF_HUB_VERBOSITY"], "error")
            self.assertEqual(os.environ["TRANSFORMERS_VERBOSITY"], "error")

    def test_downloads_model_when_it_is_not_cached(self):
        model = _Model()
        load_calls = []

        def load_model(name, **options):
            load_calls.append((name, options))
            if options.get("local_files_only"):
                raise OSError("not cached")
            return model

        module = types.SimpleNamespace(SentenceTransformer=load_model)
        with patch.dict(sys.modules, {"sentence_transformers": module}):
            QwenEmbedder().encode_query("query")

        self.assertEqual(
            load_calls,
            [(MODEL_NAME, {"local_files_only": True}), (MODEL_NAME, {})],
        )
