---
type: pipeline
tags: [harvest, pipeline, duckdb]
updated: 2026-07-06
---

# The DuckDB Lane Router

> [!abstract] What it is
> A small, fast database that takes a year's worth of papers and stamps each one with the lane it
> belongs to — and then *tracks what happened* to each as the pipeline runs. It started as a map
> (how to get each paper); it's now also a dashboard (what's done, what's left, what a human must
> do). It's the dispatcher *and* the operations console.

## Why a database at all

We generate structured facts about papers faster than any human can eyeball them. Once you're asking
questions *across* thousands of papers — how many are CC-BY? how many have PMC XML? which publisher
dominates the convert pile? — you're asking database questions. DuckDB is the ideal fit: a single
file, no server to run, plain SQL, one small install. It reads our harvested files *in place*.

> [!info] A firm rule
> The database is a **disposable read-view**, never the source of truth. Every fact in it comes from
> the harvested OpenAlex records; delete the database and you rebuild it in seconds. It is never the
> place papers are "claimed" or coordinated — that would be the wrong tool and a corruption risk.

## What it stamps on each paper

For every 2025 paper the router computes and stores these facts:

- **`in_pmc`** — is there a PubMed Central copy? (detected from the paper's locations, since OpenAlex's
  own PMC flag is broken).
- **`pmcid`** — the PMC identifier, recovered from that location, so ingest can fetch it directly.
- **`scoap3`** — `aps` (JATS, ingest), `other` (physics, split further by journal), or blank.
- **`route`** — the *cheapest actual mechanism* to get this paper's XML: `pmc`, `jats_native_open`,
  `springer_oa_api`, `scoap3_aps`, `scoap3_jhep`, `scoap3_elsevier`, `scoap3_other`,
  `elsevier_entitlement`, `gated_commercial`, `repository`, `convert`, or `out_of_scope`. (The old
  coarse `scoap3_other` was split once we learned it hid three realities — JHEP ingest, EPJC via
  Springer API, PLB transform.) Informed by [The Full Source Landscape](../Sources/The%20Full%20Source%20Landscape.md).
- **`route_access`** — how much friction the route carries: `open`, `free_key`, `entitlement`,
  `gated`, `repository`, or `none`.
- **`asset_route`** — where the *figures* come from (never in the XML): `publisher_package`,
  `repo_pdf`, `oa_pdf`, `pdf_extract_laneB`, or `none`. Asset capture is non-negotiable, so `none`
  is an explicit escalation flag, never a silent gap.
- **`lane`** — the coarse cost tier rolled up from the route: `C_ingest`, `Cprime_transform`,
  `B_convert`, `out_of_scope`.
- **`disposition`** — what a *human* must do: `automated`, `convert_vor`, or `source_aam`, driven
  by the VoR licence. This is the decision that completes the model — see [The Disposition Model](../The%20Disposition%20Model.md).

All of these are **inter-article metadata** — computed without ever opening a manuscript. See
[Intra vs Inter-Article Metadata](../Concepts/Intra%20vs%20Inter-Article%20Metadata.md).

## From map to work-tracker

The columns above say *how to get* each paper. A second set, written back as the pipeline runs,
says *what happened*:

- **`ingest_status`** — `pending`, `ingested`, `partial` (text passed, figures short), `escalate`
  (a human must handle it), or `failed`.
- **`gates_passed`**, **`figures_status`**, **`escalate_reason`**, plus the indexed [sidecar](../The%20Sidecar%20&%20Index.md).

The trick is **durability**: outcomes live in `ingest_log.json` (and the per-paper sidecars), so a
rebuild-from-harvest never wipes real work — `build-db` seeds the columns `pending`, then overlays
the log. A single query is now the operational worklist: *what's pending on an open route, what
needs a human, what's done.* The [ingest-operator agent](../The%20Route-Operator%20Agents.md) and the
*Platform dashboard* both read this.

> [!example] The question the route column answers
> "Show me every CC-BY paper I can harvest openly right now" is `WHERE route_access = 'open'` — 2,283
> of them for 2025. "What's genuinely stuck in hand-conversion?" is `WHERE route = 'convert'` — just
> 310. The router turned a vague strategy into an exact worklist per route.

## The routing logic, in plain English

For each paper: if it isn't CC-BY, it's out of scope. Otherwise, if it's an APS/SCOAP3 physics paper
→ ingest; if it's other-publisher SCOAP3 → transform; if it's in PMC → ingest; if none of those, it's
CC-BY but unstructured → convert. One `CASE` statement, run over the whole year.

## What it produces

A single query — `SELECT lane, count(*) FROM works GROUP BY lane` — now prints the entire strategic
picture instantly. That output *is* *Facts and Figures (2025)*. When the operation scales to two or
three cataloguers, the same database federates across their folders (that's what `metadata_lab.py`
and the cataloguer simulation are for — see [The Tools](The%20Tools.md)).

> [!note] Run it
> `python harvest_openalex.py build-db --year 2025` — builds `works_2025.duckdb` and prints the lane
> table. `python worklist.py` reads it back as the operations view (route × status matrix,
> `--next` do-next queue, `--escalate` human queue, `--paper <id>` for a full sidecar record).

---
Prev: [SCOAP3 — The Physics Half](../Sources/SCOAP3%20—%20The%20Physics%20Half.md) · Next: [The Tools](The%20Tools.md)
