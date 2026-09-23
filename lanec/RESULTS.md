# Lane-C crosswalk — proof of concept

**Paper:** "Holographic analysis of the pion", *Phys. Rev. D* 111, 034024 (2025).
doi:10.1103/PhysRevD.111.034024. OpenAlex W4407564473. 2-author theory paper, CC-BY-4.0.
**Run:** 2026-07-04, out-of-band in MORE-metadata-lab/lanec (synthetic id MORE-2025-900024).

## What lane C is

Not hand-authoring — a **written-once transform** (`crosswalk_aps.py`) run over every APS/SCOAP3
paper. Publisher JATS in → house-profile `article.xml` out. Text, math, references, and tables are
inherited verbatim; only the institutional layer is added.

## Timings (the "minutes not sessions" claim, measured)

| Step | Time |
|---|---|
| Fetch JATS + PDF from SCOAP3 (open S3, no auth) | ~1 s |
| Figure extraction from PDF (`pdf_preprocess`) | ~30 s |
| Crop 2 stacked-panel figures from page renders | ~5 s |
| **XML crosswalk (`crosswalk_aps.py`)** | **0.6 s** |
| Gates (validate + house lint) | ~4 s |

Total hands-on ≈ **a couple of minutes**, dominated by figure handling; the XML crosswalk itself is
sub-second. Contrast: an attended AAM/VoR authoring session is hours.

## Crosswalk transforms applied

1. DOCTYPE Publishing 1.3 → **Archiving 1.4 MathML3** (our DTD); `dtd-version`/`xml:lang` set.
2. Injected `<article-id pub-id-type="manuscript-id">` + ANZSRC `<article-categories>`
   (51 → 5107 → 510702 Field theory and string theory — the ONE judgement call).
3. **OASIS exchange tables → JATS XHTML** (`oasis:tgroup/row/entry` → `table/thead/tbody/tr/th|td`,
   colspan from namest/nameend, in-cell math preserved). 3/3 tables, 0 residual `oasis:` nodes.
4. 5 `<graphic>` EPS hrefs → house `assets/figN.png` (figures via the hybrid: `pdf_preprocess`
   got figs 3–5; figs 1–2, stacked panels, cropped from page renders).

## Gate results

| Gate | Result |
|---|---|
| validate_jats Tier 1 + Tier 2 (full JATS 1.4 DTD + MathML3) | **PASS** |
| jats_house_lint | **PASS** (0 errors, 504 warnings) |

Inherited verbatim from publisher: 55 references, 271 `<mml:math>`, 68 disp-formula, 203
inline-formula — none of which we had to author or adjudicate.

## Key finding — scope the StyleChecker MathML rules by provenance

493 of the 504 warnings are the new StyleChecker MathML-quality rules firing on APS's *authoritative*
MathML: 476 single-child `<mml:mrow>` "superfluous wrapper", 12 consecutive `<mml:mtext>`, 5 split
`<mml:mn>`. These rules were tuned to catch defects in OUR agent-recovered MathML; publisher MathML
legitimately uses these constructs. **Lane C should downgrade/suppress the MathML-quality warnings
when provenance = trusted publisher XML** (a `--source publisher` flag, or provenance in the sidecar).
The remaining 11 warnings are expected: house fig/table id naming (APS scheme), RRP-text absent
(CC-BY VoR), one non-house sec-type, corresp marked differently.

## Verdict

A first APS/SCOAP3 paper crossed to gate-passing house JATS in minutes, sub-second for the XML
itself. `crosswalk_aps.py` is reusable across the ~900 UoM APS papers. Two sibling transforms
(Springer A++, Elsevier 5.x) would extend lane C′ to the rest of SCOAP3.
