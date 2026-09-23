---
type: lane
lane: B
tags: [harvest, lanes]
updated: 2026-07-15
---

# Lane B — Convert the VoR (now half-automated)

> [!info] In a line
> The paper is CC-BY, so we're allowed to make a structured version — but nobody has. Since
> 2026-07-14, for about half of these papers a machine-read draft already exists and we convert
> *that*; only the rest still need the true, careful PDF conversion.

Lane B used to be one undifferentiated "hard road". It's now **two tiers**:

## Tier 1 — TEI-assisted (built, working)

OpenAlex has already run roughly **half** of these papers through GROBID, a machine-reading tool
that produces a rough structured draft (title, authors, sections, paragraphs, references) called
TEI. We don't reverse-engineer the PDF from scratch — we translate that draft into house JATS
(`lanec/tei_to_jats.py`), guided by a small **rule card per publisher** (`publisher_rules.py`:
how they cite, whether headings are numbered, where the licence can be trusted from).

Proven on a 76-paper pilot across the five publishers that matter here (Wiley, Oxford, Cambridge,
Taylor & Francis, RSC): **72 of 76 pass both quality gates outright**. The four that don't are
exactly the ones that *should* escalate — one unreadable header, three PDFs that state no licence
anywhere (we checked every page; fail-closed is correct). Two disciplines the drafts can't give us:

- **The licence comes from the PDF the publisher printed** — never trusted from the draft, never
  fabricated. Wiley's is carried as a *clickable link* rather than text; we read the link.
- **Figures stay attended.** The draft has captions but no images; automatic caption-pairing
  declines rather than risk mislabelling (RSC end-places its captions, for example). A package
  with unfilled figures fails its gates honestly and queues for human completion.

The standing regression test is `tei_pilot.py` — re-run after any rule change, diff the report.

## Tier 2 — true PDF conversion (still the honest hard road)

Papers with no TEI draft still need the workstation-style attended conversion described below —
hours per paper, a council of extractors, an AI that *adjudicates rather than transcribes*.
This tier is **not built in the lab yet**; it remains the expensive remainder.

## Who lands here

After the harvest lanes take everything they can: CC-BY (or otherwise reusable) papers with **no
ready XML anywhere** — about **2,130 papers** in 2025 (the `convert_vor` disposition, "JATS from
VoR" in the Platform). It leans to the physical sciences that aren't particle physics: materials,
condensed matter, chemistry-physics, astronomy.

## The quiet payoff of the harvest lanes

Lane B doesn't get cheaper per paper — but tier 1 just removed *half the pile*, and every paper
the harvest lanes absorb concentrates the remaining attended hours on the papers where they're
the only option.

## It's also where the benchmark gold comes from

Lane-B-style papers that *do* have a publisher-XML twin become our measuring stick: we run our
own conversion, then compare against the publisher's version for a real accuracy number. That's
the *The Benchmark — Proof It Works* story.

---
Prev: [Lane A — Rights-Driven Conversion](Lane%20A%20—%20Rights-Driven%20Conversion.md) · Next: [Lane C — Ingest](Lane%20C%20—%20Ingest.md)
