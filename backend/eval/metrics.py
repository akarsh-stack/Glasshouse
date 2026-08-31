"""Ranking metrics for the retrieval eval.

Deliberately tiny and dependency-free. These are the numbers that decide whether
a chunking or gating change was an improvement, so they are worth being able to
read in one sitting.
"""

from typing import Iterable, Optional


def rank_of(retrieved_ids: list[str], relevant_ids: set[str]) -> Optional[int]:
    """1-based position of the first relevant hit, or None if it never appears."""
    for position, chunk_id in enumerate(retrieved_ids, 1):
        if chunk_id in relevant_ids:
            return position
    return None


def reciprocal_rank(rank: Optional[int]) -> float:
    """1/rank, or 0 for a miss.

    Reciprocal rank is the right shape for RAG: the difference between rank 1 and
    rank 2 matters far more than between rank 9 and 10, because only the top few
    chunks fit in the context budget.
    """
    return 1.0 / rank if rank else 0.0


def recall_at_k(ranks: Iterable[Optional[int]], k: int) -> float:
    """Fraction of queries whose correct chunk landed in the top k."""
    ranks = list(ranks)
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def summarize(ranks: list[Optional[int]]) -> dict:
    return {
        "queries": len(ranks),
        "recall@1": round(recall_at_k(ranks, 1), 4),
        "recall@3": round(recall_at_k(ranks, 3), 4),
        "recall@5": round(recall_at_k(ranks, 5), 4),
        "mrr": round(mean(reciprocal_rank(r) for r in ranks), 4),
        "misses": sum(1 for r in ranks if r is None),
    }
