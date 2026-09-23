---
type: map
tags: [harvest, start-here]
updated: 2026-07-04
---

# The Big Idea

> [!abstract] In one sentence
> For roughly half of Manchester's open-access papers, a fully-structured, house-style JATS
> version **already exists somewhere** — so instead of converting them one-by-one, we can
> **harvest** them for next to nothing, and save our expensive hand-conversion for the papers
> where nothing structured exists.

For the last while, the MORE workstation has done one thing beautifully: take a messy manuscript
and turn it — slowly, carefully, by hand-with-an-AI — into archival JATS XML. That workstation is
finished, locked in, in GitHub, with its own *vault*. It is the **producer of last resort**: the
place a paper goes when no structured version can be found anywhere.

This lab is about a discovery that sits *in front of* that workstation. Two of them, really:

1. **PubMed Central already holds publisher-quality JATS** for a huge slice of our biomedical
   output — free, keyless, downloadable. See [PubMed Central — The Biomedical Half](Sources/PubMed%20Central%20—%20The%20Biomedical%20Half.md).
2. **SCOAP3 holds the same for particle physics** — and one publisher (APS) even deposits it in
   *our own tag suite*. See [SCOAP3 — The Physics Half](Sources/SCOAP3%20—%20The%20Physics%20Half.md).

Put those together and a paper no longer has just one road to JATS. It has **four**, and only the
last one is expensive. That is the heart of everything here: [The Four Lanes](The%20Four%20Lanes/The%20Four%20Lanes.md).

## The map

- **The insight** — [Harvest, Don't Convert](Concepts/Harvest,%20Don't%20Convert.md) · [Intra vs Inter-Article Metadata](Concepts/Intra%20vs%20Inter-Article%20Metadata.md)
- **The four lanes** — [The Four Lanes](The%20Four%20Lanes/The%20Four%20Lanes.md) → [Lane A — Rights-Driven Conversion](The%20Four%20Lanes/Lane%20A%20—%20Rights-Driven%20Conversion.md) ·
  [Lane B — True Conversion](The%20Four%20Lanes/Lane%20B%20—%20True%20Conversion.md) · [Lane C — Ingest](The%20Four%20Lanes/Lane%20C%20—%20Ingest.md) · [Lane C′ — Transform](The%20Four%20Lanes/Lane%20C′%20—%20Transform.md)
- **Where the XML comes from** — [OpenAlex — The Index](Sources/OpenAlex%20—%20The%20Index.md) · [PubMed Central — The Biomedical Half](Sources/PubMed%20Central%20—%20The%20Biomedical%20Half.md) ·
  [SCOAP3 — The Physics Half](Sources/SCOAP3%20—%20The%20Physics%20Half.md) · [The Full Source Landscape](Sources/The%20Full%20Source%20Landscape.md) (every other route we scanned)
- **The production machine** — [The DuckDB Lane Router](The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md) · [The Tools](The%20Production%20Pipeline/The%20Tools.md)
- **The numbers** — *Facts and Figures (2025)*
- **The proof** — *The Benchmark — Proof It Works*
- **Plain-English dictionary** — *Glossary*

## Why this matters, bluntly

Our attended workstation is the scarce, precious resource — it costs hours of careful human-plus-AI
attention per paper. The discovery in this lab means we can point that scarce attention at *exactly*
the papers that need it, while a fifth of our entire annual output arrives already done, at the cost
of a database lookup and a sub-second transform. See *Facts and Figures (2025)* for what that looks
like across one real year of Manchester papers.

---
Next: [Harvest, Don't Convert](Concepts/Harvest,%20Don't%20Convert.md)
