from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .embedding import EMBEDDING_DIMENSIONS, MODEL_NAME

COLLECTION_NAME = "recall_chunks"
COLLECTION_METADATA = {
    "embedding_model": MODEL_NAME,
    "embedding_dimensions": EMBEDDING_DIMENSIONS,
}


class StoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    source_path: str
    content_hash: str
    size: int
    modified_ns: int
    category: str
    tags: list[str]
    summary: str
    chunk_count: int


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    chunk_id: str
    source_path: str
    content: str
    distance: float
    category: str
    tags: list[str]
    summary: str
    chunk_index: int


class ChromaStore:
    def __init__(self, path: Path) -> None:
        try:
            import chromadb

            path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(path))
            self.collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=None,
                metadata=COLLECTION_METADATA,
                configuration={"hnsw": {"space": "cosine"}},
            )
            self._validate_collection()
        except StoreError:
            raise
        except Exception as error:
            raise StoreError(f"无法打开 Chroma store {path}: {error}") from error

    def upsert_document(
        self,
        document: DocumentRecord,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> None:
        if not chunks or len(chunks) != len(embeddings):
            raise StoreError("chunks 与 embeddings 必须非空且数量相同")
        for embedding in embeddings:
            _validate_embedding(embedding)

        existing = self.collection.get(
            where={"document_id": document.document_id},
            include=[],
        )
        old_ids = set(existing["ids"])
        new_ids = [f"{document.document_id}:{index}" for index in range(len(chunks))]
        metadatas = [
            _metadata(document, chunk_index=index, chunk_count=len(chunks))
            for index in range(len(chunks))
        ]

        try:
            self.collection.upsert(
                ids=new_ids,
                documents=chunks,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            stale_ids = sorted(old_ids - set(new_ids))
            if stale_ids:
                self.collection.delete(ids=stale_ids)
        except Exception as error:
            raise StoreError(
                f"写入文档 {document.document_id} 失败: {error}"
            ) from error

    def get_document(self, document_id: str) -> DocumentRecord | None:
        records = self.collection.get(
            where={
                "$and": [
                    {"document_id": document_id},
                    {"chunk_index": 0},
                ]
            },
            include=["metadatas"],
            limit=1,
        )
        return _first_document(records)

    def find_by_path(self, source_path: str) -> DocumentRecord | None:
        records = self.collection.get(
            where={
                "$and": [
                    {"source_path": source_path},
                    {"chunk_index": 0},
                ]
            },
            include=["metadatas"],
            limit=1,
        )
        return _first_document(records)

    def find_by_hash(self, content_hash: str) -> list[DocumentRecord]:
        records = self.collection.get(
            where={
                "$and": [
                    {"content_hash": content_hash},
                    {"chunk_index": 0},
                ]
            },
            include=["metadatas"],
        )
        return _documents(records)

    def list_documents(self) -> list[DocumentRecord]:
        records = self.collection.get(
            where={"chunk_index": 0},
            include=["metadatas"],
        )
        return sorted(_documents(records), key=lambda item: item.document_id)

    def delete_document(self, document_id: str) -> None:
        if self.get_document(document_id) is None:
            raise StoreError(f"文档不存在: {document_id}")
        self.collection.delete(where={"document_id": document_id})

    def update_path(self, document_id: str, source_path: str) -> None:
        self._update_metadata(document_id, {"source_path": source_path})

    def update_tags(
        self,
        document_id: str,
        category: str,
        tags: list[str],
        summary: str,
    ) -> None:
        self._update_metadata(
            document_id,
            {"category": category, "tags": tags, "summary": summary},
        )

    def search(
        self,
        query_embedding: list[float],
        limit: int,
        category: str | None = None,
        tag: str | None = None,
    ) -> list[SearchHit]:
        _validate_embedding(query_embedding)
        if self.collection.count() == 0:
            return []

        filters: list[dict[str, Any]] = []
        if category:
            filters.append({"category": category})
        if tag:
            filters.append({"tags": {"$contains": tag}})
        where = None
        if len(filters) == 1:
            where = filters[0]
        elif filters:
            where = {"$and": filters}

        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = result["ids"][0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            _search_hit(chunk_id, content, distance, metadata)
            for chunk_id, content, distance, metadata in zip(
                ids, documents, distances, metadatas, strict=True
            )
        ]

    def _validate_collection(self) -> None:
        metadata = self.collection.metadata or {}
        actual = {
            "embedding_model": metadata.get("embedding_model"),
            "embedding_dimensions": metadata.get("embedding_dimensions"),
        }
        if actual == COLLECTION_METADATA:
            return
        if self.collection.count() == 0:
            self.collection.modify(metadata=COLLECTION_METADATA)
            return
        raise StoreError(
            "Store embedding 配置不兼容："
            f"当前需要 {MODEL_NAME} ({EMBEDDING_DIMENSIONS} 维)，"
            f"实际为 {actual['embedding_model'] or '未知模型'} "
            f"({actual['embedding_dimensions'] or '未知'} 维)；请重建 store"
        )

    def _update_metadata(self, document_id: str, updates: dict[str, Any]) -> None:
        records = self.collection.get(
            where={"document_id": document_id},
            include=["metadatas"],
        )
        ids = records["ids"]
        metadatas = records.get("metadatas") or []
        if not ids:
            raise StoreError(f"文档不存在: {document_id}")

        updated = []
        for metadata in metadatas:
            value = dict(metadata or {})
            for key, update in updates.items():
                if (key == "tags" and not update) or update == "":
                    value.pop(key, None)
                else:
                    value[key] = update
            updated.append(value)
        self.collection.update(ids=ids, metadatas=updated)


def _validate_embedding(embedding: list[float]) -> None:
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise StoreError(
            f"embedding 必须是 {EMBEDDING_DIMENSIONS} 维，实际为 {len(embedding)} 维"
        )


def _metadata(
    document: DocumentRecord,
    chunk_index: int,
    chunk_count: int,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "document_id": document.document_id,
        "source_path": document.source_path,
        "content_hash": document.content_hash,
        "size": document.size,
        "modified_ns": document.modified_ns,
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
    }
    if document.category:
        metadata["category"] = document.category
    if document.tags:
        metadata["tags"] = document.tags
    if document.summary:
        metadata["summary"] = document.summary
    return metadata


def _documents(records: dict[str, Any]) -> list[DocumentRecord]:
    return [
        _document(metadata)
        for metadata in records.get("metadatas") or []
        if metadata is not None
    ]


def _first_document(records: dict[str, Any]) -> DocumentRecord | None:
    documents = _documents(records)
    return documents[0] if documents else None


def _document(metadata: dict[str, Any]) -> DocumentRecord:
    return DocumentRecord(
        document_id=str(metadata["document_id"]),
        source_path=str(metadata["source_path"]),
        content_hash=str(metadata["content_hash"]),
        size=int(metadata["size"]),
        modified_ns=int(metadata["modified_ns"]),
        category=str(metadata.get("category", "")),
        tags=list(metadata.get("tags", [])),
        summary=str(metadata.get("summary", "")),
        chunk_count=int(metadata["chunk_count"]),
    )


def _search_hit(
    chunk_id: str,
    content: str | None,
    distance: float,
    metadata: dict[str, Any] | None,
) -> SearchHit:
    value = metadata or {}
    return SearchHit(
        document_id=str(value["document_id"]),
        chunk_id=chunk_id,
        source_path=str(value["source_path"]),
        content=content or "",
        distance=float(distance),
        category=str(value.get("category", "")),
        tags=list(value.get("tags", [])),
        summary=str(value.get("summary", "")),
        chunk_index=int(value["chunk_index"]),
    )
