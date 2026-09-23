"""Timestamps are timezone-aware.

This was naive UTC on purpose — the original reasoning was that an aware value
would change what lands in SQLite and stop comparing against existing rows. That
reasoning was wrong in one important way: newer `sqlmodel` *rejects* naive
datetimes for a `DateTime` column outright, so the choice wasn't
"compatible vs correct", it was "works on my machine vs works anywhere".

`requirements.txt` asked for `sqlmodel>=0.0.18`, so CI resolved a newer version
than the one installed locally and every test that wrote a trace failed there
while passing here. Aware is both correct and portable; the range is now bounded
so the two environments agree.
"""

from datetime import timedelta, timezone

from sqlmodel import Session, select

from app.models import QueryLog, utcnow


class TestUtcnow:
    def test_is_timezone_aware(self):
        assert utcnow().tzinfo is not None

    def test_is_utc(self):
        assert utcnow().utcoffset() == timedelta(0)

    def test_is_comparable_with_itself(self):
        # Naive/aware mixing raises TypeError, which is what a half-migrated
        # codebase produces at the point of comparison rather than at write.
        assert utcnow() - timedelta(hours=1) < utcnow()


class TestRoundTrip:
    def test_a_trace_timestamp_survives_the_database(self, observability):
        trace = observability.start_trace("tz-1")
        trace.query_text = "q"
        observability.finish_trace(trace)

        with Session(observability.engine) as db:
            stored = db.exec(select(QueryLog).where(QueryLog.id == "tz-1")).one()

        assert stored.timestamp.tzinfo is not None, "naive on read means naive in storage"
        assert stored.timestamp.utcoffset() == timedelta(0)

    def test_the_metrics_window_matches_what_was_written(self, observability):
        """The window filter compares a computed bound against stored values, so
        both sides have to agree about awareness."""
        trace = observability.start_trace("tz-2")
        trace.query_text = "q"
        observability.record_stage(trace, "llm_ms", 12.0)
        observability.finish_trace(trace)

        assert observability.get_metrics("1h")["total_requests"] == 1

    def test_an_old_trace_falls_outside_the_window(self, observability):
        with Session(observability.engine) as db:
            db.add(QueryLog(
                id="tz-3",
                query_text="ancient",
                timestamp=utcnow() - timedelta(days=30),
                stages_ms='{"llm_ms": 5}',
            ))
            db.commit()

        assert observability.get_metrics("1h")["total_requests"] == 0
        assert observability.get_metrics("7d")["total_requests"] == 0
