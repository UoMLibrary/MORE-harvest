---
type: concept
tags: [harvest, concept]
updated: 2026-07-04
---

# Harvest, Don't Convert

> [!tip] The core reframe
> Conversion is turning a messy file into structure. Harvesting is *finding the structure someone
> already made* and bringing it home. The cheapest conversion is the one you don't have to do.

## The old mental model

Every paper is a cryptogram. You sit down, you decode it into JATS, you check it obsessively, you
ship it. That is the workstation, and it is the right model **when no structured version exists**.
The trap was assuming that was *always* the situation.

## What we actually found

A large fraction of Manchester's open-access papers have already been turned into publisher-grade JATS XML — by the publisher, or by a repository like [PubMed Central — The Biomedical Half](../Sources/PubMed%20Central%20—%20The%20Biomedical%20Half.md) or [SCOAP3 — The Physics Half](../Sources/SCOAP3%20—%20The%20Physics%20Half.md). That XML is:

- **Structured** — real tables, real maths, real references, all machine-readable.
- **Free and open** — because the paper is CC-BY, the licence *lets us take and adapt it*. See
  [Why CC-BY Is the Key](Why%20CC-BY%20Is%20the%20Key.md).
- **Often better than anything we could extract** — a publisher's own table markup beats any attempt to reconstruct a table from a PDF (see the war story in [Lane C — Ingest](../The%20Four%20Lanes/Lane%20C%20—%20Ingest.md)).

So for those papers, the job changes completely. We are not *decoding* — we are **translating** a
document that is already structured, from the publisher's dialect of JATS into ours, and bolting on
the Manchester house layer (our ID, our subject classification, our rights statement). That is
minutes of work, most of it automatic.

## The catch that keeps us honest

Two things stop this being a free lunch, and both are covered elsewhere:

1. **The licence must be checked on every single paper.** Not every "open" paper is CC-BY, and the
   very first one we tested turned out to be the more restrictive CC-BY-NC-ND — see
   [Why CC-BY Is the Key](Why%20CC-BY%20Is%20the%20Key.md).
2. **A structured version has to actually exist.** When it doesn't, we're back to the honest, careful
   [Lane B — True Conversion](../The%20Four%20Lanes/Lane%20B%20—%20True%20Conversion.md) — the workstation's home turf.

## The shape of the whole idea

Harvest where you can, convert where you must, and always be able to tell which is which. That
"telling which is which" is a database job — see [The DuckDB Lane Router](../The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md).

---
Prev: [00 — Start Here (The Big Idea)](../00%20—%20Start%20Here%20%28The%20Big%20Idea%29.md) · Next: [Intra vs Inter-Article Metadata](Intra%20vs%20Inter-Article%20Metadata.md)
