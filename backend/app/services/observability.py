import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from ..models import QueryLog, utcnow

logger = logging.getLogger(__name__)


@dataclass
class RequestTrace:
    request_id: str
    cache_status: str = "miss"
    model_used: str = ""
    fallback_triggered: bool = False
    stages_ms: dict = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    error: bool = False
    error_message: str = ""
    rate_limited: bool = False
    retrieved_chunks: list = field(default_factory=list)
    timestamp: datetime = field(default_factory=utcnow)
    query_text: str = ""
    _start: float = field(default_factory=time.monotonic, repr=False)


class ObservabilityService:
    def __init__(self, engine):
        self.engine = engine

    def start_trace(self, request_id: Optional[str] = None) -> RequestTrace:
        return RequestTrace(request_id=request_id or str(uuid.uuid4()))

    def record_stage(self, trace: RequestTrace, stage_name: str, duration_ms: float):
        trace.stages_ms[stage_name] = round(duration_ms, 2)

    def finish_trace(self, trace: RequestTrace):
        try:
            with Session(self.engine) as db:
                log = QueryLog(
                    id=trace.request_id,
                    query_text=trace.query_text,
                    timestamp=trace.timestamp,
                    cache_status=trace.cache_status,
                    model_used=trace.model_used,
                    retrieved_chunk_ids=json.dumps([c.get("chunk_id") for c in trace.retrieved_chunks]),
                    stages_ms=json.dumps(trace.stages_ms),
                    tokens_in=trace.tokens_in,
                    tokens_out=trace.tokens_out,
                    cost_usd=trace.cost_usd,
                    fallback_triggered=trace.fallback_triggered,
                    error=trace.error,
                    error_message=trace.error_message[:500],
                    rate_limited=trace.rate_limited,
                )
                db.add(log)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to save trace {trace.request_id}: {e}")

    def prune_traces(self, retention_hours: int) -> int:
        """Delete traces older than the retention window. Returns rows removed.

        The metrics endpoint only ever queries a bounded window (1h/24h/7d), so
        anything older is storage cost with no reader. Called once at startup —
        a cron would be the production answer, but a single-process demo that
        prunes on boot is honest about what it is.
        """
        cutoff = utcnow() - timedelta(hours=retention_hours)
        with Session(self.engine) as db:
            stale = db.exec(select(QueryLog).where(QueryLog.timestamp < cutoff)).all()
            for row in stale:
                db.delete(row)
            db.commit()
            return len(stale)

    def get_trace(self, request_id: str) -> Optional[QueryLog]:
        with Session(self.engine) as db:
            return db.get(QueryLog, request_id)

    @staticmethod
    def _empty_metrics(window: str) -> dict:
        """The same keys the populated case returns, zeroed.

        An empty window used to return just `{window, total_requests}`, which
        forced every consumer to treat all twelve figures as optional and made
        "no traffic" indistinguishable from "field missing".
        """
        return {
            "window": window,
            "total_requests": 0,
            "served_requests": 0,
            "observed_span_sec": 0.0,
            "req_per_sec": 0,
            "cache_hit_rate": 0,
            "error_rate": 0,
            "rate_limited_count": 0,
            "latency_p50_ms": 0,
            "latency_p95_ms": 0,
            "latency_p99_ms": 0,
            "total_cost_usd": 0.0,
            "model_breakdown": {},
        }

    def get_metrics(self, window: str = "1h") -> dict:
        windows = {"1h": 1, "24h": 24, "7d": 168}
        hours = windows.get(window, 1)
        since = utcnow() - timedelta(hours=hours)

        with Session(self.engine) as db:
            logs = db.exec(
                select(QueryLog).where(QueryLog.timestamp >= since)
            ).all()

        if not logs:
            return self._empty_metrics(window)

        # Two populations, deliberately kept apart. Everything that arrived
        # (`logs`) drives the counts; only what was *admitted* (`served`) drives
        # latency, cache and error rates.
        #
        # A rejected request did no work: it never embedded, never consulted the
        # cache, never called a model. Its total stage time is 0 ms, so including
        # rejections in the percentiles pulls p50 toward zero and reports a
        # shedding platform as a fast one. Observed directly: a 220-request burst
        # produced p50=0 ms alongside p95=36 s. Rates behave the same way — a
        # rejection is neither a cache miss nor an error, so counting it in those
        # denominators silently deflates both.
        served = [l for l in logs if not l.rate_limited]

        latencies = []
        for log in served:
            try:
                stages = json.loads(log.stages_ms or "{}")
                latencies.append(sum(stages.values()))
            except Exception:
                pass

        latencies.sort()
        # Request count is the number of logged requests, not the number whose
        # stage timings happened to parse — otherwise a malformed row silently
        # shrinks the denominator of every rate below.
        n = len(logs)
        n_served = len(served)

        def percentile(p):
            if not latencies:
                return 0
            idx = int(len(latencies) * p / 100)
            return latencies[min(idx, len(latencies) - 1)]

        cache_hits = sum(1 for l in served if l.cache_status != "miss")
        errors = sum(1 for l in served if l.error)
        rate_limited = sum(1 for l in logs if l.rate_limited)
        model_counts: dict = {}
        for log in served:
            if log.model_used:
                model_counts[log.model_used] = model_counts.get(log.model_used, 0) + 1

        # Rate over the span traffic actually arrived in, not over the window.
        # Dividing by the window length reports a 30-second load test inside a
        # 1h window as 0.06 req/s — the demo the README asks you to run looked
        # like idle traffic. The floor keeps a single request finite.
        timestamps = [l.timestamp for l in logs]
        observed_span_sec = max(1.0, (max(timestamps) - min(timestamps)).total_seconds())

        return {
            "window": window,
            # Arrivals, not admissions — this is offered load, and a shed request
            # is still traffic that arrived.
            "total_requests": n,
            "served_requests": n_served,
            # Published so the rate can be read in context: 20 requests over 9s
            # is a burst, over 3600s it is a trickle, and req_per_sec alone
            # cannot tell you which.
            "observed_span_sec": round(observed_span_sec, 2),
            "req_per_sec": round(n / observed_span_sec, 4),
            "cache_hit_rate": round(cache_hits / n_served, 4) if n_served else 0,
            "error_rate": round(errors / n_served, 4) if n_served else 0,
            "rate_limited_count": rate_limited,
            "latency_p50_ms": percentile(50),
            "latency_p95_ms": percentile(95),
            "latency_p99_ms": percentile(99),
            # Served, not all arrivals — a shed request spent nothing, and the
            # rest of this payload already follows that rule.
            "total_cost_usd": round(sum(l.cost_usd for l in served), 6),
            "model_breakdown": model_counts,
        }
