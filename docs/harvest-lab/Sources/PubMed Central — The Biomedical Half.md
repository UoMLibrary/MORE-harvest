---
type: source
tags: [harvest, source]
updated: 2026-07-04
---

# PubMed Central — The Biomedical Half

> [!success] What it is
> The US National Library of Medicine's open archive of biomedical papers. Its open-access subset holds **publisher-quality JATS XML** — free, no key, one URL per paper. This is the single biggest harvest source we have.

> [!important] Not only biomedical
> The name is a slight misnomer for our purposes. The PMC **open-access subset is cross-publisher** — MDPI, Frontiers, Oxford, Wiley-OA, Springer-OA, RSC and ACS open articles all get normalise into JATS here too. So the `in_pmc` flag is the first-check ingest signal for *any* publisher, not just life sciences. See [The Full Source Landscape](The%20Full%20Source%20Landscape.md).

PubMed Central (PMC), and its European mirror Europe PMC, is the gold mine for Lane C on the
biomedical and life-sciences side of Manchester's output — and, because of funder mandates, a good deal beyond it.

## The scale

Of Manchester's CC-BY papers, the consistent per-record count is about **1,700 in 2025 alone** sitting
in the PMC open-access subset with ready JATS — roughly a fifth of the entire year's output, harvest-ready.

> [!caution] A numbers footnote worth remembering
> Europe PMC's own affiliation search returns a *higher* figure (~2,300) because it matches "Manchester" more loosely over a different population. The reliable, apples-to-apples number — counting the same papers OpenAlex counts — is **1,700**. When the two disagree, trust the per-paper join, not the loose affiliation search.

## What the XML gives you — and what it doesn't

- **Fully in the XML:** text, references, and — the big win — **tables and maths as proper markup**.
  These are exactly the things that are hardest to reconstruct from a PDF, handed over perfect.
- **Referenced, not included:** figure image files and supplementary files. The XML names them; the
  actual binaries live in a separate per-article package.

## The delivery gotcha (so the next person doesn't lose an hour)

Getting the *text* XML is trivial — a single open URL. Getting the *figure package* is fiddly on our
network: PMC serves the packages over old-fashioned FTP (which the University network blocks), the web figure URLs are bot-gated, and the tidy HTTPS mirror path 404s. The proven answer is the
**hybrid**: take the perfect text/tables/maths from the PMC XML, and get the figures from the open PDF with our own extractor — both halves already work. Other options exist (an AWS mirror of the OA subset, Europe PMC's supplementary-files endpoint) if we want them later.

## One more caution

PMC also stores *author manuscript* versions (the NIHMS records) right alongside publisher versions.
When ingesting, we must pick the **version of record**, not an author manuscript — the mirror image of the workstation's "only accept AAMs" rule.

---
Prev: [OpenAlex — The Index](OpenAlex%20—%20The%20Index.md) · Next: [SCOAP3 — The Physics Half](SCOAP3%20—%20The%20Physics%20Half.md)
