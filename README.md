# MORE-harvest — Workstation B (harvest workstation)

This is the maintained source of the harvest workstation. It acquires
already-published **CC-BY Version-of-Record** articles from open sources and
manufactures **house JATS packages** from them — the same package shape a human
cataloguer produces from an Author Accepted Manuscript, but at a fraction of the
effort, because the publisher already did the structuring. It covers **Lanes B,
C and C′**; anything not CC-BY is out of scope here.

**Workstation A** (`aam-to-jatsxml`, a separate private repo) is the AAM
cataloguing workstation. It handles **Lane A** — rights-driven conversion of
author accepted manuscripts — and owns the shared quality gates both producers
are judged by. It joins this repo as the `lane_a/` submodule; until then the
gates live in `vendor/`, which will be replaced by `lane_a/`.

A package is one folder per work:

```
ingested/W4362692175/
├── article.xml        # house JATS 1.4 Archiving
├── assets/            # figures — the source XML never carries its own images
├── anzsrc.xml         # provisional subject classification
└── metadata.json      # the intra-article sidecar
```

## The four steps, and where each one lives

**1. Get the metadata records.** `harvest_openalex.py harvest-year` pulls a year of
one institution's works from OpenAlex — metadata only, cheap, no full text.

**2. Judge which lane to use.** `harvest_openalex.py build-db` derives, per paper,
the cheapest mechanism by which its full text could actually be obtained. That
judgement is the most consequential thing in the pipeline and it lives on its own in
**`routing/rules.py`**, as an ordered first-match-wins decision table with the
reasoning attached to each arm:

```bash
uv run python -m routing --explain
```

**3. Get the XML where it exists, and crosswalk it.** Where the publisher already
publishes JATS, `lanec/crosswalk_generic.py` lifts any dialect (PMC, APS, JHEP,
Frontiers, NLM 2.3) into house style — *Lane C*. Where the publisher's XML is a
foreign vocabulary, a written-once converter (`lanec/elsevier_to_jats.py`) produces
generic JATS first and then the same crosswalk runs — *Lane C'*.

**4. Get the PDF, and convert it through a publisher-level config.** Where there is
no open XML at all, OpenAlex's GROBID TEI plus the archived PDF go through
`lanec/tei_to_jats.py`, configured per publishing house by
**`lanec/publisher_rules.py`** — *Lane B*. The finished package is then read back
against its own PDF by an independent **fidelity gate** (`lanec/pdf_fidelity.py`),
whose thresholds were calibrated rather than guessed (`fidelity_calibrate.py`). A
fidelity FAIL never ships clean.

True PDF-only conversion — with no TEI to lean on — is **not built**. That is the
honest gap in the pipeline.

Whatever the lane, every package passes the same three gates: `validate_jats`,
`jats_house_lint` and a licence check, run and fingerprinted by `gates_run.py`.

## Quick start

```bash
uv sync
uv run python doctor.py
```

`doctor.py` reports which of the degraded modes you are in — in particular whether
DTD validation is running or being silently skipped, which is the difference between
a green verdict that means something and one that doesn't.

Then, with no key and no network:

```bash
uv run python tests/crosswalk_pilot.py  # Lane C: seven real publisher XMLs through the chain
uv run python -m routing --explain      # the routing policy as a decision table
```

A small sample of real OpenAlex metadata (36 works, several per route,
CC0) ships as a harvested page, so the router can be exercised for real:

```bash
uv run python harvest_openalex.py build-db --year 2025
uv run python tests/test_routing.py
```

Everything beyond that — actually fetching XML or PDFs — needs an OpenAlex Member+
key, which is institutional and not included. Keys are read from the environment
(e.g. `OPENALEX_API_KEY`) or from the root key files, and are never committed
(see `.gitignore`).

## Reading order

1. `routing/rules.py` — the routing judgement, the densest domain reasoning here
2. `ingest_one.py` — the whole chain for one paper, end to end
3. `lanec/crosswalk_generic.py` — the Lane C workhorse
4. `lanec/publisher_rules.py` + `lanec/pdf_fidelity.py` — the Lane B config and its gate
5. `CHANGELOG.md` — the change discipline, which is unusual and load-bearing
6. `docs/harvest-lab/` — the same model explained for a non-programmer

## Not in this repository

The pipeline spine lives here; the operational estate that runs it day to day
does not:

- `worklist.py` — the operational read-view (route × status matrix, do-next queue)
- `regate.py`, `rebuild_scan.py` — re-judging finished packages under today's gates
  and listing which packages a fix affects
- `corpus_fsck.py` — the physical-integrity auditor for the built corpus
- `audit_ledger.py` — the append-only health ledger behind the corpus-health strip
- `intake_resolve.py`, `intake_watch.py` — the intake seam that takes DOI lists
  from the Platform console
- `render_article.py` — the article renderer
- `interrogate_pdfs.py` — the publisher-typesetting profiler that seeds the Lane-B
  rule cards
- `pmc_twin.py` — the PMC twin checker for ingest candidates and benchmark gold
- The Platform / Workbench — the staff console and its corpus views

None of it is imported by the code here. Also not here: the rights-restricted
manuscript corpus, ~6 GB of harvested packages and DuckDB indexes, and the API keys.

## Known gaps, stated up front

- **Lane B without TEI is not built.** TEI-plus-PDF works; PDF-only does not exist.
- **`scoap3_other` has no converter.** SCOAP3 journals depositing a foreign DTD
  need a written-once transform that does not exist yet.
- **A Springer A++ converter is still to do.**
- **Publisher figures are only available for PMC, PLOS and SCOAP3-via-arXiv.**
  Other routes mark figure-short packages `partial` rather than pretend.
- **Lane B's element-citation structuring is still to do.**
