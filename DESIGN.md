# Glasshouse — Frontend Design Plan

Written before any component code, per build order. The product makes an invisible
signal (a query) visible as it travels a measured pipeline. The UI is an
**instrumentation panel**, not a SaaS marketing page and not a chat-bubble app.

## Palette

Base is a deep ink-navy, never flat black, never charcoal-gray.

| Token | Hex | Use |
|---|---|---|
| `ink-950` | `#080D1A` | App background |
| `ink-900` | `#101A2E` | Panel background |
| `ink-800` | `#1C2947` | Raised surfaces, cards |
| `ink-700` | `#33456F` | Borders, dividers |
| `ink-600` | `#4A5F94` | Emphasis borders, hover edges |
| `ink-300` | `#94A6CC` | Secondary text — 7.1:1 on `ink-900` |
| `ink-100` | `#E4EBFA` | Primary text — 14.5:1 on `ink-900` |

Each pipeline stage gets one hue, used **everywhere** that stage appears (trace
nodes, waterfall bars, dashboard charts, chunk cards, the logo). Listed in
pipeline order:

| Stage | Token | Hex | Luminance |
|---|---|---|---|
| Embed | `stage-embed` | `#3DDC97` (spring green) | 0.544 |
| Cache | `stage-cache` | `#FFC24D` (gold) | 0.604 |
| Retrieve | `stage-retrieve` | `#A98BFF` (violet) | 0.341 |
| Generate | `stage-generate` | `#3FBEF5` (sky) | 0.445 |
| Error/fallback | `signal-warn` | `#FF7A66` (coral) | 0.361 |

No single "bright accent" — the four stage hues *are* the accent system.

### Revised from the first pass

The original palette was built on "restrained, desaturated", and it went too far:
mean accent chroma was **29%**, three of the four stage hues sat within **0.035**
luminance of each other, and only **0.028** luminance separated four surface
tokens. The result measured as flat and read as flat — one blue-grey wash with
nothing for the eye to rank. Quiet had become inert.

Two corrections, both measured rather than eyeballed:

- **Chroma 29% → 62%.** On a ground this dark, saturated hues read as
  *emissive* — a lit instrument — rather than as loud paint. That is the whole
  reason the restraint could be relaxed without the panel becoming a toy.
- **Luminance spread 0.143 → 0.263**, with a minimum gap of 0.060 between
  adjacent stages. The four are now rankable by brightness alone, which is also
  what makes the pipeline legible to colour-blind viewers.

Every accent clears 6.4:1 against `ink-900`; body text is 14.5:1. The surface
range doubled so panels actually lift off the background instead of floating in
it.

## The mark

One signal enters glass and leaves as four — the product stated as a shape. A
neutral incoming line meets an edge-on glass plane and refracts into the four
stage hues in pipeline order. Seeing amber in the mark and amber on trace node 2
is the same fact twice, so the logo teaches the colour language before the user
has run anything.

Deliberately **not** a container: an outlined box at 24px competed with the beams
and the fan overflowed its own corners. The glass is a single plane, which is how
a prism cross-section is actually drawn, and it leaves the beams as the only
detail the eye must resolve. `components/Logo.tsx` and `public/favicon.svg` share
the geometry — beams radiate from (12.5, 16) at ±28° and ±9.5°, length 16.4 — and
the favicon adds a rounded ink plate because a tab needs its own ground.

It replaces a stock violet gradient (`#863bff`) that shared no colour, concept or
geometry with anything else in the product.

**Honest limit:** at 16px the fan softens, as any four-way detail does. It holds
from 24px up, which is where it lives.

## Typography — three families, six roles

**Families.**

1. **Display** (headings, stage names): `"Space Grotesk"` — geometric with character,
   reads technical without being a terminal cliché.
2. **Body/labels**: `"Instrument Sans"` (humanist, quiet).
3. **Measurements** (every number that is a measurement — ms, tokens, $, similarity):
   `"JetBrains Mono"`. Numbers read like instrument output.

**Scale.** Sizes are named for their *role*, not their pixels, so call sites say
what a thing is:

| Token | Size / leading | Use |
|---|---|---|
| `text-label` | 11 / 1, `0.14em` | Section labels, units, mono captions |
| `text-meta` | 12 / 1.5 | Chunk passages, secondary detail |
| `text-ui` | 14 / 1.5 | Controls, body copy |
| `text-lede` | 17 / 1.7 | **The answer**, and the query input |
| `text-title` | 20 / 1.25 | Wordmark, panel titles |
| `text-readout` | 34 / 1 | Ops numerals |

Before this there was no scale: 10, 10.5, 11, 12, 13, 15, 17 and 30px all
appeared, chosen per call site. Nothing sat in a relationship to anything else,
so the whole interface read at one volume and the eye had nowhere to land.

Two consequences worth stating:

- **The answer is the largest body text in the app.** It was 15px — one pixel
  above a caption, for the thing the product exists to produce. At 17/1.7 it is
  the first element that reads as something to sit and read.
- **Section labels have two levels.** `label-caps` for panels, `label-caps-primary`
  (heavier, `ink-100`) for the answer. Previously "Pipeline trace", "Answer" and
  "Retrieved context" were identical, so nothing signalled which one was output
  and which were chrome.

## Measure and rhythm

Long text is capped at `max-w-measure` (62ch). The answer previously ran the
full column width, which on a 1440px display is past 120 characters — the eye
loses the line return and a three-sentence answer reads as a wall.

Vertical rhythm is `mt-6` between major blocks and `mt-3`/`mb-2.5` within them,
replacing an ad-hoc mix of `mt-3`/`mt-4`/`mt-5`.

## The empty state earns its space

The idle Playground was an input, an empty trace, and then half a screen of
nothing — the emptiest possible first impression for a product about making
things visible. It now offers starter questions, **derived from the documents
actually loaded**: the sample corpus gets tailored questions (including the
cache-demo pair), anything else gets generic openers. A suggestion referencing a
document the user never uploaded would be worse than no suggestion.

It also makes a live demo one click instead of typing a question from memory.

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
(1 Embed → 2 Cache → 3 Retrieve → 4 Generate). As SSE events arrive, the signal
draws left→right; **the width of each settled segment is the backend's own
measurement of that stage**, carried on the SSE events (`embed_ms`, `cache_ms`,
`retrieve_ms`, and `llm_ms` on the final trace). Completed segments settle into
the stage hue; the moving head glows slightly. On cache hit, the signal
terminates at node 2 with the amber badge.

> **Revised from the original plan.** This was drawn as Embed → Retrieve →
> Cache, matching neither the execution order nor good sense: a cache that is
> consulted *after* the vector search cannot save the search. The backend now
> runs Embed → Cache → Retrieve, and the trace follows it. A hit is served with
> the chunks that were cached alongside the answer, so the retrieval panel still
> fills while nodes 3 and 4 stay dark.
>
> The "real measured latency" line above was also aspirational for a while: the
> frontend split the Embed/Retrieve segment at a hardcoded 35/65 ratio while the
> backend measured the true embed time and discarded it. It is now literally
> true, and `frontend/src/lib/stageTimeline.test.ts` keeps it that way.
On fallback, the Generate node pulses terracotta and the receipt says plainly which
model took over. `prefers-reduced-motion`: the full trace renders instantly, no animation.

## Citations are the link between answer and evidence

The model cites its passages as `[n]` and the chunk cards are numbered to match.
Those two are **wired together**: hovering or focusing a citation lights its card
and inverts both markers; activating one scrolls the card into view. Citations
are buttons, not `<sup>`, so the link is keyboard-reachable.

This is the product's whole argument made operable — "you can see where the
answer came from" is a weaker claim when checking it means matching numbers
across two panels by eye. The highlight moves border, background and marker fill
together rather than hue alone, so it survives colour-blindness.

## Icons

Six hand-rolled glyphs in `components/icons.tsx`, on Lucide's conventions
(24-unit grid, 2px stroke, round caps, `currentColor`) so swapping to the real
library later is a substitution rather than a redraw. Structural icons were
previously text glyphs — `⟨`, `⟩`, `×` — which are font-dependent, ignore stroke
and size tokens, and get announced literally by screen readers.

The spinner is the one infinite animation in the app, which is the only correct
use: indeterminate progress. Under `prefers-reduced-motion` it slows to 2.4s
rather than stopping, because freezing the only "still alive" signal reads as a
hung UI.

## Everything else stays quiet

One bold moment (the trace). Panels are flat ink with hairline borders, no
gradients, no glassmorphism, no glow except the trace head. Skeleton loading states
match final layout. Focus rings visible (2px, stage-generate hue). Copy is written
from the user's side: "Ask a question", "Upload documents", errors say what
happened and what to do next.
