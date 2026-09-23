---
type: source
tags: [harvest, source]
updated: 2026-07-04
---

# OpenAlex — The Index

> [!info] What it is
> A free, open catalogue of ~250 million scholarly works. It's the *card catalogue* of the whole
> operation: it tells us what Manchester published, whether it's open access, what licence it carries, and where a full-text copy lives. Manchester is now an institutional premium member.

OpenAlex is where every paper *starts*. It doesn't hold the good structured XML itself — but it tells
us, per paper, everything we need to decide which lane the paper belongs in.

## What we get from it

- **The corpus** — every Manchester journal article, by year (~9,200 in 2025 alone).
- **Licence** — the crucial CC-BY / not-CC-BY flag, per paper (see [Why CC-BY Is the Key](../Concepts/Why%20CC-BY%20Is%20the%20Key.md)).
- **Version** — whether the best open copy is the published version or an author manuscript.
- **Locations** — where open copies live, *including whether one is in PubMed Central* — which is how we detect Lane C eligibility.
- **Content links** — a hosted PDF for many papers, and a machine-made XML (see the trap below).

Almost all of this is **inter-article metadata** (see [Intra vs Inter-Article Metadata](../Concepts/Intra%20vs%20Inter-Article%20Metadata.md)) — facts
about the paper's place in the world, not its contents — so gathering it never touches a manuscript.

## The trap: OpenAlex's "XML" is not publisher JATS

OpenAlex *does* offer an XML download — but it's **GROBID TEI**, a machine's best-guess parse of the
PDF, not the publisher's authoritative version. It's the same *kind* of thing our own pipeline
produces, not a gold source. It's useful as a rough structure hint and as a benchmark opponent (see *The Benchmark — Proof It Works*), but it is **not** what Lane C harvests. The real gold is publisher JATS from [PubMed Central — The Biomedical Half](PubMed%20Central%20—%20The%20Biomedical%20Half.md) and [SCOAP3 — The Physics Half](SCOAP3%20—%20The%20Physics%20Half.md).

## Two useful quirks we learned

- The tidy "is it in PMC?" filter is **broken** (returns nothing), but the PMC *location* is present
  on each record — so we detect PMC membership per-paper and even recover the PMC ID from it. This is how [The DuckDB Lane Router](../The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md) gets its `in_pmc` flag.
- Costs are tiny: catalogue queries are fractions of a cent; only actual content downloads cost
  (about a penny each). A whole year's metadata harvest costs about half a cent.

> [!note] Run it
> `python harvest_openalex.py landscape` — the licence/version/PMC landscape.
> `python harvest_openalex.py harvest-year --year 2025` — pull a whole year's records.

---
Prev: [Lane C′ — Transform](../The%20Four%20Lanes/Lane%20C′%20—%20Transform.md) · Next: [PubMed Central — The Biomedical Half](PubMed%20Central%20—%20The%20Biomedical%20Half.md)
