# ADR-004: Server-Sent Events for the query stream

**Status:** Accepted
**Date:** 2026-07

## Context

The query endpoint has to push a sequence of events to the browser as they
happen: retrieval results, cache status, then answer tokens as the model produces
them, then a final trace. The pipeline visualization depends on receiving these
*incrementally* — a trace that arrives all at once is a bar chart, not a live
instrument.

The transport options are SSE, WebSockets, and HTTP long-polling.

## Decision

**Server-Sent Events** over a plain `POST /api/query` returning
`text/event-stream`, with each event a single JSON object.

Metrics on the Ops dashboard are **polled** over ordinary HTTP rather than
pushed.

## Consequences

**Why SSE fits the shape of the problem.** The query stream is strictly
unidirectional and strictly request-scoped: the client sends one query and
receives a burst of events until the answer completes, then the connection ends.
That is exactly SSE's shape. WebSockets buy bidirectionality this endpoint has no
use for, and the cost is real — connection lifecycle, heartbeats, reconnection
logic, and a second protocol for proxies and load balancers to handle.

**What SSE gives for free.** It is HTTP, so it inherits ordinary auth headers,
compression, and proxy behavior with no special cases. FastAPI's
`StreamingResponse` over an async generator maps onto it directly — the endpoint
is a generator that `yield`s formatted strings, which is why `api/query.py` reads
top-to-bottom as the pipeline itself.

**The trade-off actually accepted.** SSE is one-way. If the product later needs
mid-stream client input — cancelling a running generation, steering a response —
that does not fit and the transport has to change. Cancellation today relies on
the client closing the connection, which is coarser than an explicit cancel
message.

**Two operational details this forces.** Buffering proxies will hold a streamed
response until it completes, which silently destroys the entire effect, so the
response sets `X-Accel-Buffering: no` and `Cache-Control: no-cache`. And SSE over
HTTP/1.1 counts against the ~6-connection-per-origin limit; that is a non-issue
for one stream at a time, and disappears entirely under HTTP/2.

**Why metrics are polled rather than pushed.** The Ops dashboard reads
aggregates that are recomputed from SQLite, and the shortest interesting interval
for a human watching a dashboard is a second or two. Polling `GET /api/metrics`
on an interval is a few lines of client code with no connection state to manage,
no reconnect path, and no server-side subscriber registry. A WebSocket
(`/ws/live-metrics`) would reduce the request count and cut worst-case staleness
to zero, and it is the obvious upgrade if the dashboard ever needs sub-second
updates — but at the point where dashboard freshness matters more than the
complexity of keeping a subscriber set alive, which this does not reach.

## Alternatives considered

- **WebSockets for everything** — one transport for both query streaming and live
  metrics, and genuinely better if mid-stream client→server messages are ever
  needed. Rejected as complexity bought against a requirement the product does
  not have yet.
- **Long-polling** — works everywhere, including environments that break
  streaming responses, but re-establishes a connection per event, which for
  token-by-token output is absurd overhead and adds visible latency to exactly
  the thing being visualized.
- **Returning the whole answer in one response** — simplest of all, and it
  destroys the product. The point of Glasshouse is watching the pipeline execute;
  a single response reduces that to a spinner and a result.
