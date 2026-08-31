from typing import Protocol, runtime_checkable
import logging

logger = logging.getLogger(__name__)


@runtime_checkable
class VectorStore(Protocol):
    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None: ...
    def query(self, embedding: list[float], top_k: int, score_threshold: float | None = None) -> list[dict]: ...
    def delete_by_document(self, document_id: str) -> None: ...


class ChromaVectorStore:
    def __init__(self, path: str):
        import chromadb
        self._client = chromadb.PersistentClient(path=path)
        self._col = self._client.get_or_create_collection(
            name="glasshouse",
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        ids = [c["id"] for c in chunks]
        # Chunk text lives in `documents`, which is where Chroma expects it —
        # it used to be written to both `documents` and a `text` metadata field,
        # storing every chunk twice for no gain.
        metadatas = [
            {
                "document_id": c["document_id"],
                "chunk_index": c["chunk_index"],
                # Chroma metadata can't hold None, so absent pages are sentinelled.
                "page_number": c.get("page_number") or -1,
            }
            for c in chunks
        ]
        self._col.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=[c["text"] for c in chunks],
        )

    def query(self, embedding: list[float], top_k: int, score_threshold: float | None = None) -> list[dict]:
        results = self._col.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["metadatas", "distances", "documents"],
        )
        out = []
        ids = results["ids"][0]
        distances = results["distances"][0]
        metadatas = results["metadatas"][0]
        documents = results["documents"][0]
        for cid, dist, meta, text in zip(ids, distances, metadatas, documents):
            score = 1.0 - dist
            if score_threshold is not None and score < score_threshold:
                continue
            page = meta.get("page_number", -1)
            out.append({
                "chunk_id": cid,
                "score": score,
                "text": text or "",
                "document_id": meta.get("document_id", ""),
                "chunk_index": meta.get("chunk_index", 0),
                # -1 is the "no page" sentinel written on upsert.
                "page_number": page if isinstance(page, int) and page > 0 else None,
            })
        return out

    def delete_by_document(self, document_id: str) -> None:
        # include=[] fetches ids only; the default pulls every document body and
        # metadata dict for rows that are about to be thrown away.
        results = self._col.get(where={"document_id": document_id}, include=[])
        if results["ids"]:
            self._col.delete(ids=results["ids"])
