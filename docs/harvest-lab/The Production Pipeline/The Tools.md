---
type: pipeline
tags: [harvest, pipeline, tools]
updated: 2026-07-15
---

# The Tools (what runs what)

> [!info] Orientation
> A short map of the actual programs in this lab and what each one is for. Everything here is
> **read-only on the outside world and on the workstation** — the lab consumes; it never writes back
> into the conversion workstation.

## The harvesting tool — `harvest_openalex.py`

The workhorse. One program, several jobs:

- `landscape` — survey Manchester's open-access output: counts, licences, versions, PMC coverage.
- `harvest-year --year 2025` — pull a whole year's catalogue records (cheap; ~half a cent).
- `build-db --year 2025` — turn those records into `works_2025.duckdb` **and** run
  [The DuckDB Lane Router](The%20DuckDB%20Lane%20Router.md) (stamp `in_pmc` / `pmcid` / `scoap3` / `lane` on every paper).
- `fetch-one --doi <doi>` — download one paper's PDF (+ machine XML) with a licence guard.
- `pull-pdfs` — grab a bounded sample of CC-BY PDFs, grouped by publisher, for testing.

## The fetcher — `fetch_router.py`

The action end of [The DuckDB Lane Router](The%20DuckDB%20Lane%20Router.md): give it a DOI (or a route and a count) and it looks up
the paper's route in the database, dispatches to the right adapter, and saves the XML into
`fetched/{route}/`. One adapter per route: Europe PMC (with a fallback), SCOAP3 (using its exact
`doi=` lookup — with APS/JHEP capitalisation rebuilt, since the archive is case-sensitive and our
catalogue lowercases DOIs), Frontiers (needs the journal name in the URL), PLOS / eLife / F1000 /
PeerJ / Royal Society URL conventions, and ready-but-waiting adapters for the Springer OA API and
Elsevier (each activates by dropping a key file in the lab). Known gap: MDPI blocks scripted
downloads — its papers mostly appear in PMC after a deposit lag, so patience usually solves it.

> [!note] Run it
> `python fetch_router.py --doi 10.1234/example` · `python fetch_router.py --route pmc --limit 5`

## The crosswalks — `lanec/crosswalk_generic.py` (and `crosswalk_aps.py`)

The [Lane C — Ingest](../The%20Four%20Lanes/Lane%20C%20—%20Ingest.md) translator: publisher JATS in → house JATS out, in under a second.
`crosswalk_generic.py` handles all the JATS flavours we've met — APS, PMC, Frontiers, and the older
NLM-2.3 dialect many open publishers still emit — by normalising their differences (old `<citation>`
tags → modern `<mixed-citation>`, licence encodings, element ordering) and adding the house layer
(our ID, subject classification, figure-asset names). Proven end-to-end through the gates on APS,
a PMC medical paper, and a Frontiers paper — and since 2026-07-14 at real scale: the first
proper PMC batch put **216 clean packages** on the board (two crosswalk fixes en route: PMC
sometimes wraps the article in a container we now unwrap, and sometimes omits affiliation IDs
we now supply). (It grew out of an earlier APS-only crosswalk, since absorbed and deleted.) The
[Lane C′ — Transform](../The%20Four%20Lanes/Lane%20C′%20—%20Transform.md) Elsevier converter (`lanec/elsevier_to_jats.py`) is built; a Springer-A++
transform remains todo.

Since 2026-07-14 the same discipline that covers figures covers **supplementary files** too: an
article often points at extra files the publisher hosted beside it (a "Supplementary Information"
PDF, a spreadsheet of data, a peer-review file). The PMC fetch now captures those alongside the
figures, and the crosswalk points the article's references at our captured copies. Anything we
*couldn't* capture is left visible on purpose, so the quality gates flag the gap — the same
"honest partial, never a silent green" rule as figures. One reference is simply removed: PMC's
pointer to *its own* PDF copy of the article, which describes PMC's bundle rather than ours
(always noted in the run log, never dropped silently). A one-off companion,
`repair_local_hrefs.py`, applied the same fix retroactively to every package ingested before the
rule existed.

## The ingest driver — `ingest_one.py`

Chains the whole thing for one harvested paper: extract figures from the fetched PDF → crosswalk →
run the workstation gates. It's how we proved a harvested paper reaches a gate-passing, figure-complete
house package with no human in the loop. Output lands in `ingested/{id}/`.

> [!note] Run it
> `python ingest_one.py W4406497212 --mid MORE-2025-901212 --for '51:Physical sciences,5107:Particle and high energy physics,510799:…'`

## The batch driver & the worklist — `ingest_batch.py` / `worklist.py`

`ingest_batch.py --route pmc --limit N` runs the whole chain for N papers of a route (assigning
each a provisional subject code from its OpenAlex topic first), writing every outcome back to the
log. One trap worth knowing: `--limit N` means *the first N papers by ID, skipping ones already
done* — so on a part-processed route the number must reach **past** the already-done prefix to
touch new papers. `worklist.py` is the operational read-view: the route × status matrix, a
do-next queue, the escalation queue, and a full per-paper record.

## The Lane-B toolkit — machine drafts into house JATS

The [Lane B](../The%20Four%20Lanes/Lane%20B%20—%20True%20Conversion.md) tier-1 pipeline (2026-07-14): `fetch_vor_pdfs.py` pulls a
publisher-grouped CC-BY PDF corpus; `fetch_tei.py` buys the matching machine-read drafts from
OpenAlex (budget-aware, ~1p each, resumable); `interrogate_pdfs.py` profiles each publisher's
typesetting to seed the **rule cards** in `lanec/publisher_rules.py`; `lanec/tei_to_jats.py` does
the actual draft→JATS translation; and `tei_pilot.py` re-runs the whole 76-paper pilot corpus so
any rule change is checked against reality before it ships.

## The intake seam — `intake_resolve.py` / `intake_watch.py`

The Platform's Intake console lets staff paste a list of DOIs; committing writes a **batch
request into the Platform's own drawer** — and this pair is the lab's side of the handshake
(the Platform proposes, the producer disposes; the one-way rule holds). `intake_resolve.py`
reads waiting batches and creates the catalogue records (metadata only — building packages stays
an operator decision); `intake_watch.py` runs it automatically every 90 seconds, so pasted papers
appear on the Platform's grid without anyone opening a terminal.

## LaTeX hygiene — `latex_caption_clean.py` / `lanec/latex_body_clean.py`

Physics sources (JHEP especially) arrive with the author's raw LaTeX still in the text —
`\cite{...}` where a citation link should be, `$...$` where an equation should render. The
caption cleaner turns caption LaTeX into readable Unicode; the body cleaner (2026-07-15) converts
prose LaTeX into *real* structure — citations become clickable links to the reference list,
maths become proper formula elements the article view typesets — and a **guard** ensures any
residue keeps the package off "clean" (the gates don't police prose LaTeX; this does).

## Change management — `CHANGELOG.md`, version stamps, golden fixtures

Four tools that answer "did we regress?", "wasn't this fixed already?" and "what needs re-doing?"
without archaeology (2026-07-15; gate verdicts joined 2026-07-18):

- **`CHANGELOG.md`** — one entry per change to the transformation, gates or render, *in the same
  commit*, naming the affected package classes and the remediation type (re-render / re-lint /
  re-ingest of the affected class — never a blanket redo).
- **Version stamps** — every package's sidecar records which engine versions built it
  (`pipeline_versions.py`); `rebuild_scan.py --step X` lists exactly which packages a fix
  affects, so re-ingests are targeted sweeps.
- **Gate verdict stamps** — the sidecar also records which *gate engines* judged the package
  (`gates.engine`: content-hashes of the validate/lint/licence implementations, since the
  validate and lint gates live in the workstation and can't be hand-versioned from here) and
  when. `regate.py` is the machine for the changelog's "re-lint" remediation: it re-judges the
  finished packages with today's gates and reports the drift — a green issued under an old
  standard is found, not trusted. `--apply` rewrites the sidecars (a flipped verdict keeps its
  previous reading) and reindexes the log, so the board's colours always mean "passes *today's*
  gates". Run it after every gate hardening.
- **Golden fixtures** — `tests/crosswalk_pilot.py` runs six committed real papers (one per
  publisher flavour) through the chain and asserts the *semantics* (wrappers unwrapped,
  affiliations ID'd, zero raw LaTeX, citation counts). Run before committing any transform
  change; a regression fails on fixtures, never on the live collection.
- **The physical audit** — `corpus_fsck.py` is the same idea aimed at the *files* rather than
  the judgements: every asset re-hashed against its manifest, the article checked against its
  baseline hash, strays surfaced, and Lane-B packages that have *lost their re-check inputs*
  flagged the day it happens rather than the day a fidelity hardening needs them. Verdicts can
  be re-proven (`regate.py`) and now so can the substance they describe. Run it routinely —
  entropy becomes a work list, never silent rot.
- **The health ledger** — every regate and fsck run appends one summary line to `audits.jsonl`
  (when, what scope, which engines, what drifted or broke). The reports are snapshots; the ledger
  is the *history* — "the gates hardened four times and the corpus absorbed every one" is a
  sentence only an append-only record can back. The Workbench's Operations tab reads the last
  full-corpus lines as its **Corpus health** strip: green *proven*, red *attention*. A scoped or
  partial run records its scope, so it can never pose as a full bill of health.

## The PMC checker — `pmc_twin.py`

Given a list of papers, asks PubMed Central which ones have a full publisher-JATS twin — used both to
find ingest candidates and to find benchmark gold (see *The Benchmark — Proof It Works*).

## The federation view — moved to its own sibling

`metadata_lab.py` + `simulate_cataloguers.py` (the 2–3 person federation experiment: fake
cataloguer folders with a planted ID-clash, one DuckDB read-view over everyone's trackers and
sidecars) moved to the **`MORE-metadata-lab/`** sibling at the 2026-07-05 split — see
[Intra vs Inter-Article Metadata](../Concepts/Intra%20vs%20Inter-Article%20Metadata.md) and *Metadata Lab Hub*. They are no longer programs in
this lab.

## The evidence folders

- `pilot/` and `pilot2/` — the two benchmark papers (our JATS vs publisher gold vs GROBID), each with a
  `RESULTS.md`.
- `lanec/` — the live Lane-C crosswalk demonstration, with its own `RESULTS.md`.

## One important guardrail

The lab holds an OpenAlex API key in `openalex_key.txt`. The lab's *source code* is
tracked by this repository, but the key file — like all data and build folders —
is git-ignored and must never be committed, pasted into chat, or shared.

---
Prev: [The DuckDB Lane Router](The%20DuckDB%20Lane%20Router.md) · Next: *Facts and Figures (2025)*
