# Glasshouse — Frontend Design Plan

Written before any component code, per build order. The product makes an invisible
signal (a query) visible as it travels a measured pipeline. The UI is an
**instrumentation panel**, not a SaaS marketing page and not a chat-bubble app.

## Palette

Base is a deep ink-navy, never flat black, never charcoal-gray.

| Token | Hex | Use |
|---|---|---|
| `ink-950` | `#0B1120` | App background |
| `ink-900` | `#111A2E` | Panel background |
| `ink-800` | `#1A2540` | Raised surfaces, cards |
| `ink-700` | `#263354` | Borders, dividers |
| `ink-300` | `#8B99B8` | Secondary text |
| `ink-100` | `#DDE4F2` | Primary text |

Each pipeline stage gets one restrained, desaturated hue, used **everywhere** that
stage appears (trace nodes, waterfall bars, dashboard charts, chunk cards):

| Stage | Token | Hex |
|---|---|---|
| Embed | `stage-embed` | `#7C9E8F` (desaturated sage) |
| Retrieve | `stage-retrieve` | `#9287C0` (dusty violet) |
| Cache | `stage-cache` | `#C7A96B` (muted amber) |
| Generate | `stage-generate` | `#6B95C7` (slate blue) |
| Error/fallback | `signal-warn` | `#C77B6B` (muted terracotta) |

No single "bright accent" — the four stage hues *are* the accent system.

## Typography — three roles

1. **Display** (headings, stage names): `"Space Grotesk"` — geometric with character,
   reads technical without being a terminal cliché.
2. **Body/labels**: `"Instrument Sans"` (humanist, quiet).
3. **Measurements** (every number that is a measurement — ms, tokens, $, similarity):
   `"JetBrains Mono"`. Numbers read like instrument output.

## Layout

**Playground (default view)**
- Top: slim header — wordmark, view switcher (Playground / Ops), tier toggle (Fast / Quality / Deep).
- Center column: query input ("Ask a question about your documents"), then the
  **signature element** — the pipeline trace (below), then the streaming answer with citations.
- Right panel: retrieved-chunk cards (source doc, highlighted snippet, similarity as a small
  horizontal bar in the stage-retrieve hue), sorted by score. Cache badge above them:
  "Cache hit — semantic, 0.97 similarity" / "Cache miss → calling claude-sonnet-5".
- Bottom of answer: the "receipt" — a compact trace strip: stage-by-stage latency
  waterfall (stage colors), model, tokens in/out, cost. Numbered stage markers 1–4.
- Left rail (collapsible): document list + upload dropzone.

**Ops dashboard**
- Instrument-panel readout row (not icon+number cards): requests/sec, p50/p95/p99,
  cache hit rate, cost today — big mono numerals, small labels, hairline separators.
- Latency-over-time chart stacked by stage (stage colors), cache hit-rate trend,
  model usage breakdown.
- "Run load test" button — fires the load script; the panel updates live.

## Signature element — the live trace

A horizontal oscilloscope line running through four numbered stage nodes
(1 Embed → 2 Retrieve → 3 Cache → 4 Generate). As SSE events arrive, the signal
draws left→right; **the time spent drawing each segment is the real measured
latency of that stage** (a 640 ms LLM call visibly takes ~80× longer than an 8 ms
cache check). Completed segments settle into the stage hue; the moving head glows
slightly. On cache hit, the signal terminates at node 3 with the amber badge.
On fallback, the Generate node pulses terracotta and the receipt says plainly which
model took over. `prefers-reduced-motion`: the full trace renders instantly, no animation.

## Everything else stays quiet

One bold moment (the trace). Panels are flat ink with hairline borders, no
gradients, no glassmorphism, no glow except the trace head. Skeleton loading states
match final layout. Focus rings visible (2px, stage-generate hue). Copy is written
from the user's side: "Ask a question", "Upload documents", errors say what
happened and what to do next.
