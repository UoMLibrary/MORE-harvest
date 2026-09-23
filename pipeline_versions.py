#!/usr/bin/env python3
"""The pipeline step versions — the counterpart of CHANGELOG.md, machine-readable.

Every package's sidecar records the version of each step that built it (sidecar.py
stamps this automatically). After a transform fix, `python rebuild_scan.py` compares
sidecars against these numbers and lists exactly which packages need re-ingesting —
the affected class, never a blanket --redo.

THE DISCIPLINE (same commit as the change, alongside the CHANGELOG entry):
bump the step you changed. Versions only ever move forward; the history and the
"why" live in CHANGELOG.md.

All steps start at 1 as of 2026-07-15 (commit 2893f80): packages built BEFORE
stamping have no `pipeline` block and are treated as version 0 everywhere —
i.e. the scan reports them stale for any step you query, which is honest
(we can't know what built them without the log archaeology this replaces).
"""

PIPELINE_VERSIONS = {
    "crosswalk": 1,        # lanec/crosswalk_generic.py
    "tei_to_jats": 3,      # lanec/tei_to_jats.py (Lane B) — v2: back matter; v3: author fallback (2026-07-15)
    "elsevier": 1,         # lanec/elsevier_to_jats.py (Lane C')
    "body_clean": 1,       # lanec/latex_body_clean.py
    "caption_clean": 1,    # latex_caption_clean.py
    "fig_repair": 1,       # repair_repo_pdf_figs.py
    "figures": 1,          # fetch_figures.py / pdf fallback wiring
    "fidelity": 1,         # lanec/pdf_fidelity.py (Lane B gate, ingest_one [2e]) — new 2026-07-15
}


def stale_steps(sidecar):
    """Which steps of this sidecar's package are older than the current engine?
    Returns {step: (recorded_version, current_version)} for every stale step."""
    recorded = (sidecar or {}).get("pipeline") or {}
    out = {}
    for step, cur in PIPELINE_VERSIONS.items():
        rec = int(recorded.get(step, 0))
        if rec < cur:
            out[step] = (rec, cur)
    return out
