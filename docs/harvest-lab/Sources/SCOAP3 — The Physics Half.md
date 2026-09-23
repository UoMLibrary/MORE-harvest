---
type: source
tags: [harvest, source]
updated: 2026-07-04
---

# SCOAP3 — The Physics Half

> [!success] What it is
> A CERN-run consortium that makes particle-physics papers open access. Everything in it is CC-BY *by
> design*, and it publishes both PDF and XML through a clean, open, no-authentication API. It is the
> PMC of physics.

Where [PubMed Central — The Biomedical Half](PubMed%20Central%20—%20The%20Biomedical%20Half.md) covers the biomedical side, SCOAP3 covers the
particle-physics papers that PMC never touches — which is exactly the corner of the "no ready XML"
pile that would otherwise be expensive [Lane B — True Conversion](../The%20Four%20Lanes/Lane%20B%20—%20True%20Conversion.md) work.

## The scale

About **320 Manchester papers a year** live in SCOAP3 journals (Physical Review D, Physical Review
Letters, Journal of High Energy Physics, EPJ C, Physics Letters B, and a few more) — ~1,600 across five
years. Almost all CC-BY, because that's the consortium's whole purpose.

## The delightful detail: one publisher speaks our language

SCOAP3 aggregates several publishers, and they deposit in different XML formats — which is why physics
splits across two lanes:

- **APS** (Physical Review D/C/Letters) deposits **JATS** — the *same tag suite we author in*. That
  makes APS a pure [Lane C — Ingest](../The%20Four%20Lanes/Lane%20C%20—%20Ingest.md) feed. Their format is a slightly older/publishing flavour of
  JATS; converting it to ours is downhill.
- **Springer** (JHEP, EPJ C) uses its proprietary **A++** format, and **Elsevier** (Physics Letters B)
  its own DTD — both are [Lane C′ — Transform](../The%20Four%20Lanes/Lane%20C′%20—%20Transform.md), each needing a written-once converter.

## Why physics is actually the *easy* harvest

Two bonuses make SCOAP3 arguably the smoothest source of all:

- **No FTP wall.** Unlike PMC, SCOAP3 serves everything (PDF and XML) as direct open HTTPS links from
  CERN storage. It just works on the University network.
- **arXiv underneath.** Every SCOAP3 record carries its arXiv ID, and arXiv holds the original LaTeX
  source with the author's figure files.

> [!warning] The honest exception: physics figures are hard
> SCOAP3 provides no figure image files (only PDF + XML), and — unlike [PubMed Central — The Biomedical Half](PubMed%20Central%20—%20The%20Biomedical%20Half.md),
> where the publisher's figures come as a tidy zip matched by filename — physics has *no clean figure
> source*. We tried arXiv: the author's figure files don't map to the published figures (they split one
> published figure into many sub-panels — 26 files for 17 figures, 55 for 3), so matching them safely
> is impossible and we decline rather than mis-caption. That leaves extracting figures from the PDF,
> which is lossy (~75%). So physics papers often reach *almost*-complete automatically, with the figure
> shortfall flagged for a human glance — the one place the physics route needs attended care.

## Proven

We pulled a real Physical Review D paper end-to-end and crosswalked its APS JATS to house style in
**0.6 seconds** for the XML step. See *The Benchmark — Proof It Works* and `lanec/crosswalk_aps.py`.

---
Prev: [PubMed Central — The Biomedical Half](PubMed%20Central%20—%20The%20Biomedical%20Half.md) · Next: [The DuckDB Lane Router](../The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md)
