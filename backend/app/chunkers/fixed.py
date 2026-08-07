from .base import ChunkerBase


class FixedSizeChunker(ChunkerBase):
    """Fixed-width word windows with overlap.

    Sizes are in *words*, not tokens — roughly 1.3 tokens per word for English.
    The default 220 words (~290 tokens) sits in the range where a chunk is big
    enough to carry a self-contained fact but small enough that its embedding
    still points somewhere specific; a 500-word chunk covering four topics
    averages out to a vector that matches all of them weakly. The 40-word
    overlap (~18%) exists so a fact spanning a boundary survives in at least one
    chunk intact.
    """

    def __init__(self, chunk_size: int = 220, overlap: int = 40):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str, metadata: dict) -> list[dict]:
        words = text.split()
        chunks = []
        start = 0
        idx = 0
        while start < len(words):
            end = start + self.chunk_size
            chunk_words = words[start:end]
            chunks.append({
                "text": " ".join(chunk_words),
                "chunk_index": idx,
                "page_number": metadata.get("page_number"),
            })
            idx += 1
            start += self.chunk_size - self.overlap
        return chunks
