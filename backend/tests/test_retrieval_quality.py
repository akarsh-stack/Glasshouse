"""Retrieval quality regression gate.

Floors, not exact values: the point is to catch a change that makes retrieval
worse, without failing on embedding-model noise. Current measured figures are in
the assertions' messages so a drop is legible without rerunning by hand.

Run the full report with:  python -m eval.run_eval
"""

import pytest

from eval.run_eval import evaluate

pytestmark = pytest.mark.corpus


@pytest.fixture(scope="module")
def structural():
    import asyncio

    return asyncio.run(evaluate("structural", top_k=5))


@pytest.fixture(scope="module")
def fixed():
    import asyncio

    return asyncio.run(evaluate("fixed", top_k=5))


class TestShippingConfiguration:
    def test_every_question_finds_its_passage(self, structural):
        assert structural["misses"] == 0

    def test_the_right_passage_is_top_ranked_almost_always(self, structural):
        assert structural["recall@1"] >= 0.90, "measured 0.9167"

    def test_the_right_passage_is_always_in_the_top_three(self, structural):
        assert structural["recall@3"] == 1.0

    def test_the_right_passage_always_survives_gating(self, structural):
        """The metric that decides whether the model *can* answer correctly."""
        assert structural["context_precision"] == 1.0, (
            "a passage that is retrieved but gated out of the prompt is a passage "
            "the model never sees"
        )

    def test_mrr_stays_high(self, structural):
        assert structural["mrr"] >= 0.94, "measured 0.9583"


class TestStructuralBeatsFixed:
    """ADR-006's claim, reduced to numbers.

    Note what this does *not* show: rank is nearly identical between the two.
    The advantage is in signal strength, which is what actually degrades as a
    corpus grows.
    """

    def test_correct_chunks_score_higher(self, structural, fixed):
        assert structural["mean_correct_score"] > fixed["mean_correct_score"], (
            f"structural {structural['mean_correct_score']} vs "
            f"fixed {fixed['mean_correct_score']} (measured 0.507 vs 0.363)"
        )

    def test_correct_chunks_win_by_a_wider_margin(self, structural, fixed):
        assert structural["mean_margin"] > fixed["mean_margin"], (
            f"structural {structural['mean_margin']} vs fixed {fixed['mean_margin']} "
            "(measured 0.204 vs 0.149)"
        )

    def test_structural_never_gates_out_a_correct_passage(self, structural, fixed):
        assert structural["context_precision"] >= fixed["context_precision"]

    def test_structural_produces_more_single_topic_chunks(self, structural, fixed):
        """The mechanism behind the score gap: fewer topics averaged per vector."""
        assert structural["chunks_indexed"] > fixed["chunks_indexed"], (
            f"structural {structural['chunks_indexed']} vs "
            f"fixed {fixed['chunks_indexed']} chunks (measured 9 vs 4)"
        )
