# Orientation for an agent working in this snapshot

This repo is a **generated, standalone snapshot** of one folder from a larger
workspace, cut down to a single question: how published articles are harvested from
open sources and converted into house JATS. Read `README.md` first.

## What is different from the folder this came from

- **The gates are vendored.** `vendor/scripts/validate_jats.py` and
  `jats_house_lint.py` belong to a sibling project (the AAM cataloguing
  workstation) and are copied in so this runs alone. See `vendor/SOURCE.md`.
  They are the shared quality standard both producers are judged by — that is why
  they are borrowed rather than reimplemented.
- **The PDF figure-extraction fallback is absent.** It was a ~95 KB subtree of the
  workstation. Papers that would have used it degrade to `partial`, which is the
  documented behaviour for a paper whose figures cannot be captured.
- **The operational estate is absent** — worklist, regate, corpus_fsck, the audit
  ledger, the repair scripts, the intake seam. Nothing here imports them.

## Guardrails that still apply

- **Asset capture is non-negotiable.** The XML never carries its images, so every
  route has a named asset source. A paper whose figures cannot be captured is
  `partial` or `escalate` — **never a silent green**. Publisher figures with exact
  filenames beat PDF extraction; decline rather than mis-map.
- **ANZSRC is provisional by design** and must never be presented as final.
- **Verify licence per work.** Only `cc-by` gets a route.
- **The DuckDB is never the coordination layer.** Outcomes live in
  `ingest_log.json` and the per-package sidecars; the DB is a rebuildable index
  over them.
- **The changelog is mandatory** for any change to a transform, a gate, or the
  render — see `CHANGELOG.md` for the discipline and the remediation classes.
- **Routing changes must update `tests/test_routing.py`.** That test holds the
  original hand-written SQL verbatim and requires row-for-row agreement, so a
  deliberate policy change means updating the baseline in the same commit.

## Do not

- Do not edit this snapshot expecting the changes to survive; it is regenerated
  from the live folder by `make_review_repo.py`. Report findings instead.
- Do not commit anything the `.gitignore` excludes. The folder this was cut from
  holds several gigabytes of third-party article packages and a live API key
  under those exact paths.
