import os
from typing import Any

MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_DIMENSIONS = 1024


class QwenEmbedder:
    def __init__(self) -> None:
        self._model: Any = None

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load_model().encode_document(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def encode_query(self, text: str) -> list[float]:
        vector = self._load_model().encode_query(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vector.tolist()

    def _load_model(self) -> Any:
        if self._model is None:
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
            os.environ.setdefault("HF_HUB_VERBOSITY", "error")
            os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
            from sentence_transformers import SentenceTransformer

            try:
                self._model = SentenceTransformer(
                    MODEL_NAME, local_files_only=True
                )
            except OSError:
                self._model = SentenceTransformer(MODEL_NAME)
        return self._model
