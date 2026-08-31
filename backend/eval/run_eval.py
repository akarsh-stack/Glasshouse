"""Measure retrieval quality against the golden set.

    python -m eval.run_eval
    python -m eval.run_eval --chunker fixed      # reproduce ADR-006's "before"

Everything in this project was measured except the thing it exists to do: return
the right passage. Latency, cost, cache hit rate and token counts were all
instrumented while retrieval quality was taken on faith. This closes that.

Nothing is mocked — real chunking, real ONNX embeddings, a real Chroma
collection in a temp directory, and the same `RetrievalOrchestrator` the API
uses. The corpus is `samples/`, so the numbers are reproducible by anyone who
clones the repo.
"""

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.chunkers.fixed import FixedSizeChunker  # noqa: E402
from app.chunkers.structural import StructuralChunker  # noqa: E402
from app.config import Config  # noqa: E402
from app.services.embedding import EmbeddingService  # noqa: E402
from app.services.ingestion import _extract_pages  # noqa: E402
from app.services.retrieval import RetrievalOrchestrator  # noqa: E402
from app.services.vector_store import ChromaVectorStore  # noqa: E402
from eval.metrics import mean, rank_of, summarize  # noqa: E402

SAMPLES = BACKEND.parent / "samples"
GOLDEN = Path(__file__).with_name("golden_set.json")


def build_chunks(chunker) -> list[dict]:
    """Chunk every sample document, mirroring IngestService's page handling."""
    chunks = []
    for path in sorted(SAMPLES.iterdir()):
        if path.name.startswith("."):
            continue
        for text, page in _extract_pages(path.read_bytes(), path.name):
            if not text.strip():
                continue
            for c in chunker.chunk(text, {"page_number": page}):
                chunks.append({
                    "id": f"{path.name}::{len(chunks)}",
                    "document_id": path.name,
                    "text": c["text"],
                    "chunk_index": len(chunks),
                    "page_number": c.get("page_number"),
                })
    return chunks


async def evaluate(
    chunker_name: str,
    top_k: int,
    score_threshold: float | None = None,
    relative_ratio: float | None = None,
) -> dict:
    cases = json.loads(GOLDEN.read_text())["cases"]
    tmp = Path(tempfile.mkdtemp(prefix="glasshouse-eval-"))

    try:
        overrides = {}
        if score_threshold is not None:
            overrides["SCORE_THRESHOLD"] = score_threshold
        if relative_ratio is not None:
            overrides["RELATIVE_SCORE_RATIO"] = relative_ratio
        config = Config(_env_file=None, CHROMA_PATH=str(tmp), TOP_K=top_k, **overrides)
        chunker = (
            FixedSizeChunker(config.CHUNK_SIZE_WORDS, config.CHUNK_OVERLAP_WORDS)
            if chunker_name == "fixed"
            else StructuralChunker(config.CHUNK_SIZE_WORDS, config.CHUNK_OVERLAP_WORDS)
        )

        chunks = build_chunks(chunker)
        embedder = EmbeddingService(config)
        await embedder.start()
        try:
            store = ChromaVectorStore(str(tmp))
            store.upsert(chunks, await embedder.embed_batch([c["text"] for c in chunks]))
            orchestrator = RetrievalOrchestrator(embedder, store, config)

            rows, ranks, gated_hits = [], [], 0
            margins: list[float | None] = []
            correct_scores: list[float] = []
            for case in cases:
                embedding, _ = await orchestrator.embed_query(case["question"])
                # Ungated ranking: what the vector search alone put on top.
                raw = store.query(embedding, top_k)
                raw.sort(key=lambda c: c["score"], reverse=True)
                relevant = {
                    c["chunk_id"] for c in raw if case["expect_substring"] in c["text"]
                }
                rank = rank_of([c["chunk_id"] for c in raw], relevant)

                # Gated: what the orchestrator actually hands to the model after
                # the relative-score cut and the token budget.
                selected, _ = await orchestrator.search(embedding)
                in_gated = any(case["expect_substring"] in c["text"] for c in selected)
                gated_hits += in_gated

                # Margin = how far the correct chunk outscores the best wrong
                # one. This is what ADR-006 is really claiming: a grab-bag chunk
                # averages several topics, so it matches many queries weakly and
                # none strongly. Rank alone hides that — a win by 0.005 and a win
                # by 0.3 are both "rank 1", but only the second survives a corpus
                # ten times larger.
                correct = [c["score"] for c in raw if c["chunk_id"] in relevant]
                wrong = [c["score"] for c in raw if c["chunk_id"] not in relevant]
                margin = (max(correct) - max(wrong)) if correct and wrong else None

                rows.append({
                    "id": case["id"],
                    "rank": rank,
                    "correct_score": round(max(correct), 3) if correct else 0.0,
                    "margin": round(margin, 3) if margin is not None else None,
                    "kept": len(selected),
                    "in_context": in_gated,
                })
                ranks.append(rank)
                margins.append(margin)
                correct_scores.append(max(correct) if correct else 0.0)
        finally:
            await embedder.stop()

        result = summarize(ranks)
        result["chunker"] = chunker_name
        result["score_threshold"] = config.SCORE_THRESHOLD
        result["relative_ratio"] = config.RELATIVE_SCORE_RATIO
        result["chunks_indexed"] = len(chunks)
        # The metric that decides whether the model can possibly answer: did the
        # right passage survive gating into the prompt?
        result["context_precision"] = round(gated_hits / len(cases), 4) if cases else 0.0
        result["mean_correct_score"] = round(mean(correct_scores), 4)
        # Averaged over cases where a wrong chunk existed to compare against.
        result["mean_margin"] = round(mean([m for m in margins if m is not None]), 4)
        result["rows"] = rows
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chunker", default="structural", choices=["structural", "fixed"])
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--score-threshold", type=float, default=None)
    ap.add_argument(
        "--relative-ratio",
        type=float,
        default=None,
        help="0 disables relative gating, leaving only the absolute floor",
    )
    ap.add_argument(
        "--before",
        action="store_true",
        help="reproduce ADR-006's original failure: fixed chunks + an absolute 0.3 floor",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.before:
        args.chunker, args.score_threshold, args.relative_ratio = "fixed", 0.3, 0.0

    result = asyncio.run(
        evaluate(args.chunker, args.top_k, args.score_threshold, args.relative_ratio)
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(
        f"\nchunker={result['chunker']}  chunks={result['chunks_indexed']}  "
        f"top_k={args.top_k}  floor={result['score_threshold']}  "
        f"relative={result['relative_ratio']}\n"
    )
    print(f"  {'case':22} {'rank':>5} {'score':>6} {'margin':>7}  {'kept':>4}  in-context")
    print("  " + "-" * 62)
    for row in result["rows"]:
        rank = row["rank"] if row["rank"] else "—"
        mark = "yes" if row["in_context"] else "NO"
        margin = f"{row['margin']:+.3f}" if row["margin"] is not None else "—"
        print(
            f"  {row['id']:22} {str(rank):>5} {row['correct_score']:>6.3f} {margin:>7}"
            f"  {row['kept']:>4}  {mark}"
        )

    print()
    for key in ("queries", "recall@1", "recall@3", "recall@5", "mrr",
                "context_precision", "mean_correct_score", "mean_margin", "misses"):
        print(f"  {key:18} {result[key]}")
    print()


if __name__ == "__main__":
    main()
