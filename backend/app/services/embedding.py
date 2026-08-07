import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, config):
        self.config = config
        self._model = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self.actual_batch_size: int = 0

    def _load_model(self):
        if self._model is not None:
            return
        provider = self.config.EMBEDDING_PROVIDER
        # Imports are deliberately lazy: only the selected provider's (large)
        # dependency has to be installed for the app to boot.
        if provider == "onnx":
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
            self._model = ONNXMiniLM_L6_V2()
        elif provider in ("sentence-transformers", "local"):
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.config.EMBEDDING_MODEL)
        elif provider == "openai":
            import openai
            self._openai = openai.AsyncOpenAI(api_key=self.config.OPENAI_API_KEY)
        else:
            raise ValueError(
                f"Unknown EMBEDDING_PROVIDER {provider!r}; expected one of "
                "'onnx', 'sentence-transformers', 'openai'"
            )

    async def start(self):
        self._load_model()
        self._task = asyncio.create_task(self._batch_worker())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _batch_worker(self):
        window = self.config.MICRO_BATCH_WINDOW_MS / 1000.0
        while True:
            await asyncio.sleep(window)
            items = []
            while not self._queue.empty():
                items.append(await self._queue.get())
            if not items:
                continue
            texts = [item[0] for item in items]
            futures = [item[1] for item in items]
            self.actual_batch_size = len(texts)
            try:
                embeddings = await self._embed_raw(texts)
                for fut, emb in zip(futures, embeddings):
                    if not fut.done():
                        fut.set_result(emb)
            except Exception as e:
                for fut in futures:
                    if not fut.done():
                        fut.set_exception(e)

    async def _embed_raw(self, texts: list[str]) -> list[list[float]]:
        provider = self.config.EMBEDDING_PROVIDER
        if provider in ("onnx", "sentence-transformers", "local"):
            # Both local backends are synchronous and CPU-bound, so they run in
            # the default executor to keep the event loop free.
            loop = asyncio.get_event_loop()
            if provider == "onnx":
                return await loop.run_in_executor(
                    None, lambda: [list(map(float, v)) for v in self._model(texts)]
                )
            return await loop.run_in_executor(
                None, lambda: self._model.encode(texts, show_progress_bar=False).tolist()
            )
        else:
            resp = await self._openai.embeddings.create(
                model="text-embedding-3-small", input=texts
            )
            return [d.embedding for d in resp.data]

    async def embed_one(self, text: str) -> list[float]:
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        await self._queue.put((text, fut))
        return await fut

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_raw(texts)
