"""Metrics aggregation.

Three defects pinned here:

  * `req_per_sec` divided by the *window* length, so the 30-second load test the
    README tells you to demo reported ~0.06 req/s in a 1h window. The rate has to
    be measured over the span traffic actually arrived in.
  * The empty case returned two keys while the populated case returned twelve,
    so every consumer had to treat the whole payload as optional.
  * `total_cost_usd` summed over arrivals while every other figure summed over
    admissions, contradicting the two-population rule the module documents.
"""

from datetime import timedelta

import pytest
from sqlmodel import Session

from app.models import QueryLog, utcnow


def add_log(observability, **kwargs) -> QueryLog:
    defaults = dict(
        query_text="q",
        timestamp=utcnow(),
        cache_status="miss",
        model_used="claude-haiku-4-5",
        stages_ms='{"embed_ms": 10, "llm_ms": 90}',
        cost_usd=0.001,
    )
    defaults.update(kwargs)
    log = QueryLog(**defaults)
    with Session(observability.engine) as db:
        db.add(log)
        db.commit()
    return log


class TestPayloadShape:
    """One shape, always — an empty window is zeros, not absent keys."""

    EXPECTED = {
        "window",
        "total_requests",
        "served_requests",
        "observed_span_sec",
        "req_per_sec",
        "cache_hit_rate",
        "error_rate",
        "rate_limited_count",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
        "total_cost_usd",
        "model_breakdown",
    }

    def test_empty_window_returns_the_full_shape(self, observability):
        assert set(observability.get_metrics("1h")) == self.EXPECTED

    def test_populated_window_returns_the_same_shape(self, observability):
        add_log(observability)
        assert set(observability.get_metrics("1h")) == self.EXPECTED

    def test_empty_window_is_all_zeros(self, observability):
        m = observability.get_metrics("1h")
        assert m["total_requests"] == 0
        assert m["req_per_sec"] == 0
        assert m["cache_hit_rate"] == 0
        assert m["model_breakdown"] == {}


class TestRequestRate:
    def test_rate_is_measured_over_the_span_traffic_arrived_in(self, observability):
        """20 requests inside 10 seconds is 2 req/s, not 20/3600."""
        base = utcnow()
        for i in range(20):
            add_log(observability, timestamp=base - timedelta(seconds=10 - i * 0.5))
        m = observability.get_metrics("1h")
        assert m["observed_span_sec"] == pytest.approx(9.5, abs=0.6)
        assert m["req_per_sec"] == pytest.approx(2.1, abs=0.3)

    def test_the_span_is_reported_so_the_rate_is_interpretable(self, observability):
        add_log(observability)
        m = observability.get_metrics("1h")
        assert m["observed_span_sec"] >= 1.0, "a floor keeps a single request finite"


class TestTwoPopulations:
    def test_cost_counts_only_admitted_requests(self, observability):
        add_log(observability, cost_usd=0.005)
        add_log(observability, cost_usd=0.0, rate_limited=True, model_used="")
        m = observability.get_metrics("1h")
        assert m["total_requests"] == 2
        assert m["served_requests"] == 1
        assert m["total_cost_usd"] == pytest.approx(0.005)

    def test_shed_requests_stay_out_of_the_rates(self, observability):
        add_log(observability)
        for _ in range(3):
            add_log(observability, rate_limited=True, stages_ms="{}", model_used="")
        m = observability.get_metrics("1h")
        assert m["rate_limited_count"] == 3
        assert m["error_rate"] == 0
        assert m["latency_p50_ms"] == 100, "rejections contribute no latency"
