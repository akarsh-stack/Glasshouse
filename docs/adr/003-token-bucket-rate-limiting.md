# ADR-003: Token bucket, not fixed window, for rate limiting

**Status:** Accepted
**Date:** 2026-07

## Context

The rate limiter is the only layer allowed to reject a request before Glasshouse
spends anything — it sits ahead of the embedding call and the LLM call, which are
CPU and money respectively. What it needs to protect against is not steady load
(the capacity math says a single process handles peak fine) but *bursts* from one
client, including my own load-test button.

The standard choices are fixed window, sliding window log, sliding window
counter, leaky bucket, and token bucket.

## Decision

**Per-session token bucket**: 100 token capacity, refilling at 10 tokens/second,
executed as an **atomic Redis Lua script**, with in-memory per-process buckets as
the fallback when Redis is unavailable.

Rejected requests get an explicit `429` event carrying a computed `retry_after`.

## Consequences

**Why token bucket over fixed window.** Fixed window has a boundary problem that
is not a rounding error: a client can spend its full quota at 0:59 and its full
quota again at 1:01, delivering 2× the intended rate across a two-second span
that straddles the boundary. For a limiter whose entire job is absorbing bursts,
that failure mode is aimed directly at the thing it's meant to stop. Token bucket
has no boundaries — the bucket refills continuously, so the limit holds over
every window, not just the ones that happen to align with the clock.

**Why token bucket over a sliding window log.** A sliding window log is exact,
but it stores a timestamp per request per client and has to trim the set on every
check. Token bucket stores **two numbers** per client — token count and last
refill time — and updates them arithmetically. At the number of distinct sessions
this design is aimed at, that difference in memory and per-request work is the
whole argument.

**Why token bucket over leaky bucket.** Leaky bucket smooths output to a constant
rate, which is right when you're protecting a downstream that cannot absorb
spikes at all. Here a short burst is fine and even desirable — a user pasting
three questions in quick succession should not be throttled. Token bucket allows
exactly that, up to the accumulated capacity, and only clamps sustained rate.
Burst capacity is a feature, not a leak.

**Why the Lua script matters.** Read-then-write against Redis is a race: two
concurrent requests can both read "1 token left" and both spend it. Redis
executes a Lua script atomically, so the read, the refill computation, and the
decrement happen as one indivisible step. Without that, the limiter is
approximately correct under exactly the conditions — concurrency — that it exists
to handle.

**What the fallback gives up, deliberately.** When Redis is down, buckets become
per-process and in-memory. With more than one process that means the effective
limit is N× the configured limit, and state is lost on restart. That is a
conscious choice: for this system, degrading to a *looser* limit is better than
rejecting all traffic because the limiter's datastore is unavailable. The
failure-modes table in ARCHITECTURE.md records it as a known degraded mode rather
than pretending it doesn't exist.

**The parameters are a starting point.** 100 capacity and 10 tokens/second are
chosen to let a human burst freely while capping a script at 10 QPS per session.
They should be re-derived from observed per-session traffic, not treated as
constants.

## Alternatives considered

- **Fixed window counter** — the simplest possible implementation (`INCR` plus
  `EXPIRE`), and the boundary burst is why it was rejected.
- **Sliding window log** — exact, and the natural choice if the limit needed to
  be provably precise. Rejected on per-client memory and trim cost.
- **Sliding window counter** — a good middle ground that approximates the log
  with two counters. Comparable accuracy to token bucket for this use, but it
  does not express burst capacity as directly, and burst allowance is precisely
  what this limiter wants to reason about.
- **No limiter, rely on the Anthropic API's own limits** — the upstream limit is
  account-wide, so one abusive session would consume the budget for every user,
  and the rejection would arrive *after* Glasshouse had already paid for the
  embedding.
