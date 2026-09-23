---
type: lane
lane: C
tags: [harvest, lanes]
updated: 2026-07-04
---

# Lane C — Ingest (the cheap miracle)

> [!success] In a line
> Ready-made publisher JATS already exists — so we just bring it home and translate it into our house style. Minutes, mostly automatic, the structure inherited perfectly.

This is the lane the whole lab was chasing. When a CC-BY paper already has publisher JATS in
[PubMed Central — The Biomedical Half](../Sources/PubMed%20Central%20—%20The%20Biomedical%20Half.md) or (for APS physics) in [SCOAP3 — The Physics Half](../Sources/SCOAP3%20—%20The%20Physics%20Half.md), there
is nothing to *decode*. The tables, the maths, the references — all already machine-readable. We only have to do the translation and add the Manchester layer.

## What "ingest and crosswalk" actually means

Given the publisher's JATS, a written-once program:

1. Switches the DOCTYPE to our JATS 1.4 Archiving flavour.
2. Injects our **manuscript ID** and our **subject classification** (the one genuine judgement call —
   everything else is mechanical).
3. Retags anything in a different table model into our table model.
4. Renames the figure references to our house asset names.
5. Leaves text, maths, and references exactly as the publisher wrote them.

Then it runs the *same gates* a hand-converted paper runs (Lane A's standard applies to everyone).

## The war story: tables

The pilot that proved this best was a computer-science paper with two big, ugly tables. When we ran our PDF extractor over it, those tables came out as **scrambled nonsense** — the classic limit of
reading tables off a PDF. But the *publisher's JATS* carried them as clean, correct table markup. And
in the same paper, an automatic text-mining tool (GROBID) failed to parse the reference list *at all*
— zero references — while the publisher JATS had all 31 perfect. That's the case for ingest in a
nutshell: the structure the publisher already made is better than anything we could reconstruct, and it's free. See *The Benchmark — Proof It Works*.

## The catch: figures come separately — but it's solved

The one thing publisher JATS *doesn't* hand you is the figure image files — the XML just references
them by filename. But this turned out to have a clean answer for the big route: **Europe PMC serves
a zip containing the figure binaries named exactly as the XML references them** (over normal HTTPS — no FTP wall). So we fetch the publisher's own figures, match them to the XML by filename with zero guesswork, and they arrive at publisher quality. A paper that's in PMC gets this even if it arrived by another route (we can look up its PMC id from the DOI). Where a paper genuinely has no publisher figure source, we fall back to extracting figures from the open PDF — reliable for normal figures, though it can miss a purely-vector diagram (a flowchart), which is the one small residual gap.

## Proven end to end

The whole chain now runs without a human: harvest the XML + assets, fetch the publisher figures,
crosswalk to house style, run the gates — and the gates' "every figure must resolve to a real image" rule is what confirms the assets survived. Demonstrated on a real PMC medical paper (3 publisher figures, both gates green) and an APS physics paper. See *The Benchmark — Proof It Works* and `ingest_one.py`.

## How big is it

In 2025: about **1,700 papers** via PMC and **170** via APS/SCOAP3 — roughly **a fifth of everything
Manchester published that year**, at minutes each. See *Facts and Figures (2025)*.

> [!note] Run it
> `python harvest_openalex.py fetch-one --doi <doi>` — pulls the PDF (+ GROBID TEI) for one paper and checks its licence. The APS→house crosswalk lives in `lanec/crosswalk_aps.py`.

---
Prev: [Lane B — True Conversion](Lane%20B%20—%20True%20Conversion.md) · Next: [Lane C′ — Transform](Lane%20C′%20—%20Transform.md)
