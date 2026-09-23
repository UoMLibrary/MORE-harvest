# MORE harvest — pipeline review snapshot

**This is a snapshot for review, not a live repo.** It was generated on
2026-09-02 from the MORE workspace at commit `1bdf600`
by `make_review_repo.py`, which copies an explicit allow-list of files out of the
working `MORE-harvest` folder. It is a build artefact: **don't edit it, and don't
expect it to stay in sync.** Findings come back to the author, who changes the live
folder and regenerates this.

## What this code does

It acquires already-published **CC-BY Version-of-Record** articles from open
sources and manufactures **house JATS packages** from them — the same package shape
a human cataloguer produces from an Author Accepted Manuscript, but at a fraction of
the effort, because the publisher already did the structuring.

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
python -m routing --explain
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
honest gap in the pipeline, not an omission from this snapshot.

Whatever the lane, every package passes the same three gates: `validate_jats`,
`jats_house_lint` and a licence check, run and fingerprinted by `gates_run.py`.

## Start here

```bash
pip install -r requirements.txt
python doctor.py
```

`doctor.py` reports which of the degraded modes you are in — in particular whether
DTD validation is running or being silently skipped, which is the difference between
a green verdict that means something and one that doesn't.

Then, with no key and no network:

```bash
python tests/crosswalk_pilot.py     # Lane C: seven real publisher XMLs through the chain
python -m routing --explain         # the routing policy as a decision table
```

A small sample of real OpenAlex metadata (36 works, several per route,
CC0) ships as a harvested page, so the router can be exercised for real:

```bash
python harvest_openalex.py build-db --year 2025
python tests/test_routing.py
```

Everything beyond that — actually fetching XML or PDFs — needs an OpenAlex Member+
key, which is institutional and not included.

## Reading order

1. `routing/rules.py` — the routing judgement, the densest domain reasoning here
2. `ingest_one.py` — the whole chain for one paper, end to end
3. `lanec/crosswalk_generic.py` — the Lane C workhorse
4. `lanec/publisher_rules.py` + `lanec/pdf_fidelity.py` — the Lane B config and its gate
5. `CHANGELOG.md` — the change discipline, which is unusual and load-bearing
6. `docs/harvest-lab/` — the same model explained for a non-programmer

## What was deliberately left out

This snapshot is the pipeline spine only (27 Python files). The live folder also
contains the operational estate that runs it day to day — a worklist read-view, a
standing re-lint sweep, a physical-integrity auditor, an append-only health ledger,
targeted repair scripts for named defect classes, and a commissioning seam that
takes DOI lists from a separate console app. None of it is imported by the code
here, and none of it is what you were asked to look at.

Also left out: the AAM cataloguing workstation (a separate repo), the
rights-restricted manuscript corpus, ~6 GB of harvested packages and DuckDB
indexes, and the API keys.

## Known gaps, stated up front

- **Lane B is half built.** TEI-plus-PDF works and is in production; PDF-only does not exist.
- **Figures on Lane B are an attended step.** Physics collaboration figures have no
  clean automated source, and the pipeline is designed to mark those `partial`
  rather than pretend. The workstation's PDF figure-extraction fallback is not
  vendored here, so that path degrades to `partial` in this checkout by design.
- **ANZSRC codes are provisional.** Division-level, assigned from the OpenAlex
  topic, flagged for cataloguer review. Never presented as final.
- **Licence is verified per work.** The router only assigns a route to `cc-by`;
  an institution's own VoRs are frequently NC-ND, which is exactly why.
