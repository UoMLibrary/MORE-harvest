---
title: The Sidecar & Index
tags: [harvest]
---

# 🧾 The Sidecar & Index

> [!abstract] The idea
> When the pipeline converts a paper, it should record *what it produced* — not just "done" in a
> log, but a durable, per-paper record of the identity, classification, gate results and every
> figure. That's the **sidecar**. The DuckDB then holds a queryable *index* of them.

## The intra-article record

Every ingested paper gets `ingested/{id}/metadata.json` — the durable **intra-article record**
(schema `more-intra-article/1`, mirroring the workstation's own sidecar). It carries:

- **identity** — work id, MORE id, DOI, journal, title
- **route + provenance** — the route it came by, tagged `registry+<route>`
- **classification** — the ANZSRC triple (with its provisional flag)
- **gate verdicts** — validate/lint pass, error and warning counts
- **asset manifest** — *every* figure, with byte size, SHA-256, and where it came from

This is exactly the [intra-article](Concepts/Intra%20vs%20Inter-Article%20Metadata.md) half of Scott's concept,
made concrete. (The *inter*-article half — resolved reference DOIs, the self-DOI, shared authors —
isn't in the sidecar yet; that's the natural next extension.)

## File is truth; the DB is a rebuildable index

The sidecar *file* is the source of truth. The [router DuckDB](The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md) holds only
a **rebuildable projection**: a `sidecar_path`, the full sidecar as a queryable JSON column, and a
few convenience counts. On every rebuild, `build-db` re-globs the sidecars and re-indexes them —
so the DB can be deleted and rebuilt with zero loss, honouring "the database is disposable".

Because it's stored as JSON, it's genuinely SQL-queryable — e.g. group every paper by
`sidecar->'assets'->>'source'`, or count `json_array_length(sidecar->'assets'->'manifest')`. This
is precisely the `read_json` federation the *metadata lab* was built for.

## Why it matters

Before the sidecar, the pipeline produced the *deliverable* (article.xml + assets) but never a
*record of it*. Now every conversion leaves an auditable trail — and the *Platform* reads these sidecars to know identity, classification and asset provenance
for each harvested article.

Related: [The DuckDB Lane Router](The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md) · [Intra vs Inter-Article Metadata](Concepts/Intra%20vs%20Inter-Article%20Metadata.md) · [The Tools](The%20Production%20Pipeline/The%20Tools.md)
