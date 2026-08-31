"""Scoring for the retrieval eval.

Kept as pure functions with their own fast tests, so the numbers the eval
reports are themselves trustworthy. An eval harness with an off-by-one in its
MRR is worse than no eval: it produces a confident number nobody checks.
"""

import pytest

from eval.metrics import mean, rank_of, recall_at_k, reciprocal_rank, summarize


class TestRankOf:
    def test_a_hit_at_the_top_is_rank_one(self):
        assert rank_of(["a", "b", "c"], {"a"}) == 1

    def test_a_hit_further_down_reports_its_position(self):
        assert rank_of(["a", "b", "c"], {"c"}) == 3

    def test_the_best_rank_wins_when_several_are_relevant(self):
        assert rank_of(["a", "b", "c"], {"b", "c"}) == 2

    def test_no_hit_returns_none(self):
        assert rank_of(["a", "b"], {"z"}) is None

    def test_an_empty_result_list_returns_none(self):
        assert rank_of([], {"a"}) is None


class TestReciprocalRank:
    def test_rank_one_scores_one(self):
        assert reciprocal_rank(1) == 1.0

    def test_rank_four_scores_a_quarter(self):
        assert reciprocal_rank(4) == 0.25

    def test_a_miss_scores_zero(self):
        assert reciprocal_rank(None) == 0.0


class TestRecallAtK:
    def test_counts_a_hit_inside_k(self):
        assert recall_at_k([1, 2, 3], k=3) == 1.0

    def test_excludes_a_hit_beyond_k(self):
        assert recall_at_k([4, 5], k=3) == 0.0

    def test_misses_count_against_recall(self):
        # Two of four queries found the right chunk at rank 1.
        assert recall_at_k([1, 1, None, None], k=1) == 0.5

    def test_no_queries_is_zero_not_a_crash(self):
        assert recall_at_k([], k=1) == 0.0


class TestMean:
    def test_averages(self):
        assert mean([1.0, 2.0, 3.0]) == 2.0

    def test_empty_is_zero(self):
        assert mean([]) == 0.0


class TestSummarize:
    def test_reports_every_headline_figure(self):
        s = summarize([1, 2, None, 1])
        assert s["queries"] == 4
        assert s["recall@1"] == 0.5
        assert s["recall@3"] == 0.75
        assert s["mrr"] == pytest.approx((1 + 0.5 + 0 + 1) / 4)
        assert s["misses"] == 1

    def test_a_perfect_run_scores_one_across_the_board(self):
        s = summarize([1, 1, 1])
        assert s["recall@1"] == 1.0 and s["mrr"] == 1.0 and s["misses"] == 0
