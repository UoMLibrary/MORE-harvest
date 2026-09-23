---
type: lane
lane: C-prime
tags: [harvest, lanes]
updated: 2026-07-04
---

# Lane C′ — Transform (ingest's cousin)

> [!success] In a line
> The ready-made version exists, but it's in a *different* XML format — so we write one translation
> program per format, once, and then it too is minutes per paper forever.

Lane C′ is [Lane C — Ingest](Lane%20C%20—%20Ingest.md) with one extra step at the front. Some publishers deposit their
open-access content not as JATS but in their own house XML format. The content is all there and
perfectly structured — it just speaks a different language.

## The concrete case: SCOAP3 physics

[SCOAP3 — The Physics Half](../Sources/SCOAP3%20—%20The%20Physics%20Half.md) gathers particle-physics papers from several publishers, and they don't
all use the same format:

- **APS** (Physical Review D/C/Letters) deposits **JATS** — so APS is plain [Lane C — Ingest](Lane%20C%20—%20Ingest.md).
- **Springer** (Journal of High Energy Physics, EPJ C) deposits its proprietary **A++** format.
- **Elsevier** (Physics Letters B) deposits its own **article DTD 5.x** format.

Springer and Elsevier are Lane C′: each needs a written-once converter from their format into house JATS.

## Why "written once" is the whole point

A translation program is an investment with a fixed cost and an unlimited payoff. You spend a day
writing the Springer A++ → house converter *one time*, and from then on every JHEP and EPJ C paper — hundreds a year — flows through it in minutes. The per-paper cost collapses to essentially zero; only the up-front build costs anything.

This is exactly the "per-publisher rules pay off at scale" economics: heterogeneous inputs, but each
*kind* of input handled by one reusable tool.

## How big is it

Small but real: about **150 papers in 2025** (Springer + Elsevier physics). Two converters would
cover it. Worth doing once the two big ingest feeds (PMC, APS) are running. See
*Facts and Figures (2025)*.

## Status — all three SCOAP3 formats now handled

The physics side is done, and the reality turned out cleaner than "three transforms":

- **JHEP (Springer)** — no transform needed. Its A++ file is a *header* pointing to full-text that's
  already JATS at the publisher's server, so it's plain [Lane C — Ingest](Lane%20C%20—%20Ingest.md). Built and proven.
- **EPJC (Springer)** — SCOAP3 only supplies metadata for it, so the full text comes from the free
  Springer Nature Open Access API instead. No bespoke transform.
- **Physics Letters B (Elsevier)** — this is the one that genuinely needed a written-once converter,
  and it's **built and proven** (`lanec/elsevier_to_jats.py`): Elsevier's entirely-different vocabulary
  → house JATS, passing both gates. Wired into the ingest driver, which auto-detects Elsevier XML.

The one caveat across all physics papers stays the figures — see the warning in
[SCOAP3 — The Physics Half](../Sources/SCOAP3%20—%20The%20Physics%20Half.md) — not the text conversion, which is now solved for every SCOAP3 format.

---
Prev: [Lane C — Ingest](Lane%20C%20—%20Ingest.md) · Next: [OpenAlex — The Index](../Sources/OpenAlex%20—%20The%20Index.md)
