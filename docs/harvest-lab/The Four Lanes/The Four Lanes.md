---
type: map
tags: [harvest, lanes]
updated: 2026-07-04
---

# The Four Lanes

> [!abstract] The whole model in one picture
> A paper reaches house-style JATS by one of four routes. They differ enormously in cost — from *sub-second and automatic* to *hours of attended care* — so the entire game is routing each paper to the cheapest lane that can actually do the job.

Every Manchester paper falls into exactly one lane. Three of them are cheap because someone else
already did the structuring; the fourth is the workstation we already had.

| Lane | Name | What it means | Cost per paper |
|---|---|---|---|
| **A** | [Lane A — Rights-Driven Conversion](Lane%20A%20—%20Rights-Driven%20Conversion.md) | Convert the author's manuscript (AAM) under Rights Retention | Hours, attended |
| **B** | [Lane B — True Conversion](Lane%20B%20—%20True%20Conversion.md) | Convert the published PDF because no structured version exists | Hours, attended |
| **C** | [Lane C — Ingest](Lane%20C%20—%20Ingest.md) | Bring home ready publisher JATS and crosswalk it to house style | Minutes |
| **C′** | [Lane C′ — Transform](Lane%20C′%20—%20Transform.md) | Same, but the source is a non-JATS publisher format needing a one-time converter | Minutes (after a one-off build) |

## How the lanes relate

- **A and B are the expensive, attended lanes** — the workstation's territory. A is *rights-driven*
  (we do it because the paper is otherwise paywalled and Manchester holds the manuscript). B is
  *necessity-driven* (the published version is CC-BY but nobody structured it, so we must).
- **C and C′ are the cheap harvest lanes** — the new discovery. C is when the ready-made XML is
  already JATS (just a different flavour). C′ is when it's a different XML format entirely and needs a
  written-once translation program, after which it too is minutes-per-paper.

## The routing rule

For a given CC-BY paper, in order:

1. Is there ready JATS in [PubMed Central — The Biomedical Half](../Sources/PubMed%20Central%20—%20The%20Biomedical%20Half.md) or from APS in
   [SCOAP3 — The Physics Half](../Sources/SCOAP3%20—%20The%20Physics%20Half.md)? → **Lane C**.
2. Is there ready non-JATS XML (Springer, Elsevier via SCOAP3)? → **Lane C′**.
3. Otherwise, it's CC-BY but unstructured → **Lane B**.
4. Not CC-BY at all → out of scope for the VoR route (but maybe **Lane A** via the manuscript).

That decision is made automatically for every paper by [The DuckDB Lane Router](../The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md). To see how the
real 2025 numbers fall across the four lanes, go to *Facts and Figures (2025)*.

---
Prev: [Intra vs Inter-Article Metadata](../Concepts/Intra%20vs%20Inter-Article%20Metadata.md) · Next: [Lane A — Rights-Driven Conversion](Lane%20A%20—%20Rights-Driven%20Conversion.md)
