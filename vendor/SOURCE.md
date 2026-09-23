# vendor/ — the shared quality gates, copied

These files are **not part of the harvest pipeline**. They belong to the AAM
cataloguing workstation, the other producer in the MORE workspace, and they are
copied here so this snapshot can run standalone.

They matter because they are the SHARED RULER: both producers — the AAM lane and
this harvest lane — are judged by the same validate and house-lint, which is what
makes a package a package regardless of which lane made it. Reviewing them is in
scope only insofar as they define what the pipeline is aiming at.

Both gate scripts are pure standard library. Tier 2 of validate additionally wants
the JATS 1.4 DTD — see `dtd/README.md`.

Copied 2026-09-02 from `MORE-aam-to-jats` (workspace commit `1bdf600`).

| File | sha256 (16) | bytes |
|---|---|---|
| `scripts/validate_jats.py` | `cc6f4b8b8da8677e` | 8,776 |
| `scripts/jats_house_lint.py` | `edb01b264cf6fc5e` | 35,803 |
| `scripts/data/anzsrc_2020.json` | `ad2da17f0416b097` | 171,885 |

`gates_run.py` records the content hash of the gate engine that issued every
verdict, into every package sidecar. That is what makes a hardened gate turn old
verdicts visibly stale rather than silently wrong — and here it doubles as drift
detection: if these copies fall behind the workstation's originals, the hashes
stamped by this snapshot will not match the ones in the live corpus.
