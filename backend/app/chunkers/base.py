from abc import ABC, abstractmethod


class ChunkerBase(ABC):
    @abstractmethod
    def chunk(self, text: str, metadata: dict) -> list[dict]:
        """Split text into chunks. Returns list of {text, chunk_index, page_number}."""
        ...
