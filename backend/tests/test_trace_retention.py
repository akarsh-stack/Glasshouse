"""Trace retention.

`QueryLog` is append-only and every request writes a row, so the table grew
without bound — the one component in a project about observability that had no
answer to "and then what?". Metrics only ever query a bounded window, so rows
older than the longest window are pure storage cost.
"""

from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app.models import QueryLog, utcnow


def add_log(observability, age_hours: float) -> None:
    with Session(observability.engine) as db:
        db.add(QueryLog(
            query_text="q",
            timestamp=utcnow() - timedelta(hours=age_hours),
            stages_ms='{"llm_ms": 10}',
        ))
        db.commit()


def count(observability) -> int:
    with Session(observability.engine) as db:
        return len(db.exec(select(QueryLog)).all())


class TestPrune:
    def test_rows_older_than_the_retention_window_are_removed(self, observability):
        add_log(observability, age_hours=200)
        add_log(observability, age_hours=1)
        removed = observability.prune_traces(retention_hours=168)
        assert removed == 1
        assert count(observability) == 1

    def test_rows_inside_the_window_survive(self, observability):
        for age in (1, 24, 100):
            add_log(observability, age_hours=age)
        assert observability.prune_traces(retention_hours=168) == 0
        assert count(observability) == 3

    def test_the_boundary_row_is_kept(self, observability):
        """Off-by-one here silently deletes the oldest slice of the 7d window."""
        add_log(observability, age_hours=167.9)
        assert observability.prune_traces(retention_hours=168) == 0

    def test_pruning_an_empty_table_is_a_no_op(self, observability):
        assert observability.prune_traces(retention_hours=168) == 0

    def test_retention_must_cover_the_longest_metrics_window(self, config):
        """7d is the widest window the dashboard offers; retaining less would
        make that view silently incomplete."""
        assert config.TRACE_RETENTION_HOURS >= 168
