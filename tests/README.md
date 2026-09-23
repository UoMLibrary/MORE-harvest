# `tests/` — the transform harnesses

Not pytest. These are standing harnesses, run directly, and they are **fast and offline** —
committed fixtures only, no network, no production state touched.

```bash
python tests/crosswalk_pilot.py    # Lane C — run before committing any transform change
python tests/fidelity_pilot.py     # Lane B — the fidelity gate's own golden test
```

Both live at the top of the change discipline: a transform edit that hasn't been through
them isn't ready to commit.

---

## `crosswalk_pilot.py` — the Lane-C golden fixtures

Seven committed source XMLs, one per publisher flavour the crosswalk must survive, run
through the **real** chain: pre-transforms sniffed by header exactly as `ingest_one` does,
crosswalk, body-LaTeX conversion, then the workstation's validate gate.

Assertions are **semantic**, held in `expected.json` per fixture — not a diff of output
bytes. Each fixture pins things like: the root became `<article>`, every `<aff>` carries an
id, the licence is typed, zero residual prose LaTeX survived, and the contributor / figure /
formula / reference / linked-citation counts are what they were.

| Fixture | What it exercises |
|---|---|
| `aps.xml` | APS — JATS Publishing plus OASIS tables |
| `jhep_latex_body.xml` | JHEP A++ BodyRef with raw LaTeX in the text nodes (2,875 contributors, 1,444 formulas — the stress case) |
| `pmc_clean.xml` | The ordinary PMC path |
| `pmc_aff_noid.xml` | PMC affiliations arriving without ids |
| `pmc_articleset.xml` | PMC wrapped in an `<article-set>` |
| `native_open.xml` | Native-OA publishers on the older NLM-2.x flavour |
| `laneb_W7133915096.grobid.xml` | Lane B's TEI, so the Lane-C assertions cover it too |

The house lint is deliberately **not** run here: asset resolution is the ingest run's
concern, not the transform's, so lint asset errors would only be measuring the absent
figures.

## `fidelity_pilot.py` — the Lane-B gate's golden test

The gate that catches dropped content is itself regression-tested, which matters more than
it might sound: a fidelity gate that silently stops working looks exactly like a corpus with
no problems.

It runs the real Lane-B chain on the committed TEI fixture (W7133915096, Taylor & Francis,
CC-BY 4.0, *Crystallography Reviews*) against a committed PDF-text snapshot, and asserts
three things:

1. the **intact** conversion passes the gate (completeness, grounding, mass, parity);
2. a **mutant with most of its body deleted** does *not* pass — and note that **house-lint
   stays green on exactly this mutant**, which is precisely the hole the gate exists to
   close;
3. a **mutant missing one reference** breaks ref parity and FAILs.

Run it before committing any change to `tei_to_jats`, `crosswalk_generic` or `pdf_fidelity`.

## The larger harnesses (not here — repo root)

These need the fetched corpus and take real time, so they live at the root rather than in
`tests/`:

| Harness | What it does |
|---|---|
| `../tei_pilot.py` | Batch-validates the Lane-B chain over every real TEI+PDF pair in `harvest/pdfs_2025`, without touching production state — no package, no ingest log, no tracker. Figures are stubbed. Persists `report.json` so rule tweaks diff run over run. |
| `../fidelity_calibrate.py` | **The evidence tool.** Runs the gate's metrics over the pilot corpus, splits distributions by lint verdict, and reports per-publisher medians plus the verdict tally today's thresholds would give. |

**The discipline:** a fidelity threshold — whether a `pdf_fidelity` constant or a rule
card's `fidelity_floor` — moves only on `fidelity_calibrate.py` evidence, with a
`CHANGELOG.md` entry. Never on judgement, and never to make a batch pass.

## Fixtures

`fixtures/` holds the committed source XMLs plus, for the Lane-B pair, its metadata
(`.meta.json`) and PDF-text snapshot (`.pdftext.txt`). All are real CC-BY papers. When a
route surfaces a flavour the pipeline can't handle, the fix is a new fixture here **and**
the transform change — not the transform change alone.
