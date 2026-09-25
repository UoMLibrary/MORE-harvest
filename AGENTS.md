# AGENTS.md — instructions for agents working in MORE-harvest

This file is the single canonical set of instructions for working in this
repository. `CLAUDE.md` and `GEMINI.md` are one-line pointers to it.

## 1. What this repo is

This is **Workstation B, the harvest workstation**. It acquires already-published
**CC-BY versions of record** from open sources and manufactures **house JATS
packages** from them — the same package shape a human cataloguer produces from an
Author Accepted Manuscript. It covers **Lanes B, C and C′**:

- **Lane C** — the publisher already publishes JATS; crosswalk it into house style.
- **Lane C′** — the publisher's XML is a foreign vocabulary; convert it to generic
  JATS first, then run the same crosswalk.
- **Lane B** — no open XML at all; convert via OpenAlex's GROBID TEI plus the PDF.

**Workstation A** (`aam-to-jatsxml`, a separate private repo) is the AAM
cataloguing workstation. It handles **Lane A** (rights-driven conversion of
author accepted manuscripts) and owns the shared quality gates. It joins this
repo as the `lane_a/` submodule; until then the gates live in
`vendor/`, which will be replaced once the submodule is integrated.

Read `README.md` first for the pipeline tour, then `routing/rules.py` for the
routing judgement.

## 2. Routing

The cheapest mechanism by which a paper's full text can actually be obtained,
judged per paper:

| Situation | Where it goes |
|---|---|
| Not CC-BY | Out of scope for B; may be an AAM candidate for Workstation A |
| CC-BY, publisher JATS available | Lane C |
| CC-BY, foreign-vocabulary XML | Lane C′ |
| CC-BY, no open XML | Lane B (OpenAlex TEI plus PDF) |

The policy itself is an ordered first-match-wins decision table in
`routing/rules.py`, compiled into the SQL that `harvest_openalex.py build-db`
runs. To see it rendered:

```bash
uv run python -m routing --explain
```

## 3. Where the code lives today

Flat layout at the repo root, with the transforms in `lanec/` and the routing
policy in `routing/`:

| Path | What it is |
|---|---|
| `harvest_openalex.py` | Metadata harvest (`harvest-year`) and DB build (`build-db`), which applies the routing policy |
| `routing/` | The routing policy (`rules.py`) and its `--explain` renderer |
| `ingest_one.py`, `ingest_batch.py` | The per-paper chain and the batch driver |
| `lanec/` | The transforms: `crosswalk_generic.py`, `elsevier_to_jats.py`, `tei_to_jats.py`, plus `publisher_rules.py`, `pdf_fidelity.py` and the LaTeX cleaners |
| `fetch_*.py` | The fetchers (TEI, VoR PDFs, figures, route dispatch) |
| `gates_run.py`, `vendor/` | The gate runner and the vendored Workstation A gates (to be replaced by `lane_a/`) |
| `sidecar.py`, `ingest_log.py`, `pipeline_versions.py` | Package sidecars, the ingest log and engine version stamps |
| `doctor.py` | Reports which degraded modes this checkout is in; run it first |
| `tei_pilot.py`, `fidelity_calibrate.py` | The Lane-B pilot harness and the fidelity evidence tool |
| `tests/` | Standing harnesses (`crosswalk_pilot.py`, `fidelity_pilot.py`, `test_routing.py`); see `tests/README.md` |
| `harvest/works_2025/page_0001.json` | The one tracked OpenAlex sample page (CC0); everything else under `harvest/` is ignored |
| `tei_pilot/` | The Lane-B calibration corpus |
| `docs/harvest-lab/` | The docs vault: the same model explained for a non-programmer |
| `CHANGELOG.md` | The change discipline, which is load-bearing |

Transforms will be reorganised into lane folders (`lane_b/`, `lane_c/`,
`lane_c_prime/`). Until then, the flat layout above is current.

## 4. Guardrails

These carry over from the original `CLAUDE.md` unchanged in intent:

- **Asset capture is non-negotiable.** The XML never carries its images, so every
  route has a named asset source. A paper whose figures cannot be captured is
  `partial` or `escalate` — **never a silent green**. Publisher figures with
  exact filenames beat PDF extraction; decline rather than mis-map.
- **ANZSRC is provisional by design** and must never be presented as final.
- **Verify licence per work.** Only `cc-by` gets a route.
- **The DuckDB is never the coordination layer.** Outcomes live in
  `ingest_log.json` and the per-package sidecars; the DB is a rebuildable index
  over them.
- **The changelog is mandatory** for any change to a transform, a gate, or the
  render — see `CHANGELOG.md` for the discipline and the remediation classes.
- **Routing changes must update `tests/test_routing.py`.** That test holds the
  original hand-written SQL verbatim and requires row-for-row agreement, so a
  deliberate policy change means updating the baseline in the same change.

## 5. Working with Workstation A

Workstation A will join as the `lane_a/` submodule. The import policy,
agreed with the project lead:

- B may use A's functions **only through `lane_a_bridge.py`** — one bridge
  module, no direct imports from `lane_a/` anywhere else.
- Every function used through the bridge is **listed here, in this section**,
  and each one has a **contract test** pinning the behaviour B relies on.
- A's scripts run **in A's own environment** (`uv run --project lane_a`), never
  in B's.

No functions are imported yet: `lane_a/` and `lane_a_bridge.py` do not exist
yet. The full section — the submodule pin, the function list and
the contract tests — will be completed when the submodule is added.

## 6. Environment

One uv environment, managed per machine and never committed:

```bash
uv sync                 # provision the environment
uv run python doctor.py # check which degraded modes you are in
uv run …                # run everything else through uv
```

Two system tools sit outside uv:

- `xmllint` — the DTD validation tier (without it, verdicts prove less than
  they appear to; `doctor.py` reports the tier).
- `gs` (Ghostscript) — optional EPS-to-PNG conversion for arXiv figures.

## 7. Data handling

- **Never commit keys or third-party content.** API keys, router databases, run
  outputs, fetched sources and built packages are all excluded by `.gitignore` —
  check it before adding anything unfamiliar.
- Keys are read from the **environment** (e.g. `OPENALEX_API_KEY`) or from the
  **root key files** (`openalex_key.txt`, `springer_key.txt`,
  `elsevier_key.txt`). Never paste a key into chat or a file that is committed.

## 8. Agents

The route-operator agents `ingest-operator` and `transform-author` are pending
from the project lead. **Do not write them from scratch.** Their canonical
definitions will live in `deploy/roles/`, generated per vendor into the
gitignored vendor directories. Vendor-specific copies may already exist under
the gitignored `.claude/` directory; those are generated output, not the
source, and will be promoted into `deploy/roles/`.

## 9. Language

British English in code comments and documentation (`optimise`, `behaviour`,
`colour`).
