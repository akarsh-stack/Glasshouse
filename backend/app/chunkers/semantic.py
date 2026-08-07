import logging
from .base import ChunkerBase
from .fixed import FixedSizeChunker

logger = logging.getLogger(__name__)


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _split_sentences(text: str) -> list[str]:
    import re
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p for p in parts if p]


class SemanticChunker(ChunkerBase):
    def __init__(self, threshold: float = 0.5, max_tokens: int = 512):
        self.threshold = threshold
        self.max_tokens = max_tokens
        self._model = None
        self._fallback = FixedSizeChunker(chunk_size=max_tokens)

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception as e:
                logger.warning(f"SemanticChunker: model unavailable ({e}), using fallback")
        return self._model

    def chunk(self, text: str, metadata: dict) -> list[dict]:
        model = self._get_model()
        if model is None:
            return self._fallback.chunk(text, metadata)

        sentences = _split_sentences(text)
        if not sentences:
            return []

        try:
            embeddings = model.encode(sentences, show_progress_bar=False).tolist()
        except Exception as e:
            logger.warning(f"SemanticChunker encode failed: {e}")
            return self._fallback.chunk(text, metadata)

        chunks = []
        current = [sentences[0]]
        current_tokens = len(sentences[0].split())
        idx = 0

        for i in range(1, len(sentences)):
            tokens = len(sentences[i].split())
            sim = _cosine(embeddings[i - 1], embeddings[i])
            if current_tokens + tokens > self.max_tokens or sim < self.threshold:
                chunks.append({
                    "text": " ".join(current),
                    "chunk_index": idx,
                    "page_number": metadata.get("page_number"),
                })
                idx += 1
                current = [sentences[i]]
                current_tokens = tokens
            else:
                current.append(sentences[i])
                current_tokens += tokens

        if current:
            chunks.append({
                "text": " ".join(current),
                "chunk_index": idx,
                "page_number": metadata.get("page_number"),
            })

        return chunks
