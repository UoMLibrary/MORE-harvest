#!/usr/bin/env python3
"""The ingest work-tracker: turns the router DuckDB from a MAP into a DASHBOARD.

The router (harvest_openalex.build_db) stamps how to GET each paper from its metadata.
This module records what HAPPENED when we tried — so a query can distinguish "pending",
"done", "failed" and "needs a human" instead of only "here's the route".

Two-place write, on purpose:
  * ingest_log.json  — the durable record, keyed by work id. Survives a rebuild of
    works_YYYY.duckdb (which is derived-from-harvest and disposable); build_db overlays
    this file back onto the fresh columns.
  * works_YYYY.duckdb — updated in place too, so `worklist.py` reflects a run immediately
    without needing a rebuild first.

The log is the source of truth; the DB columns are a convenience mirror.
"""
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "ingest_log.json")

# The five outcomes a paper can land in (ingest_status):
#   pending     — routed, not yet attempted (seeded by build_db)
#   ingested    — both gates pass AND figures complete: a finished house package
#   partial     — gates pass but figures incomplete: usable text, assets need a human
#   escalate    — a known-hard case a human must handle (e.g. math-as-image, no source)
#   failed      — the chain errored or a gate failed for a non-figure reason
STATUSES = ("pending", "ingested", "partial", "escalate", "failed")


def classify(validate_pass, lint_pass, figures_status, escalate_reason, licence_pass=True):
    """Map a run's raw signals to one ingest_status. Figure shortfall is NOT failure —
    it's the honest 'partial' (physics figures) or 'escalate' (math-as-image) boundary."""
    if not licence_pass:
        # Hard stop: we ingest only CC-BY VoR content. A missing or non-CC-BY licence on
        # the packaged document is a failure regardless of the other gates — never green.
        return "failed"
    if escalate_reason:
        return "escalate"
    if validate_pass and lint_pass:
        return "ingested"
    # gates only fail on figures once the transform/crosswalk itself is sound: that's a
    # complete-text / incomplete-assets package, not a broken one.
    if validate_pass and not lint_pass and figures_status in ("partial", "none"):
        return "partial"
    return "failed"


def _load():
    if os.path.isfile(LOG):
        return json.load(open(LOG, encoding="utf-8"))
    return {}


def year_for(work_id):
    """Which works_YYYY.duckdb knows this work — the corpus is multi-year since the
    intake seam (works_2017..works_2026 on disk). Falls back to 2025, the original
    single-year assumption, when no DB claims the id."""
    try:
        import duckdb
    except ImportError:
        return 2025
    for p in sorted(os.listdir(HERE)):
        m = re.match(r"works_(\d{4})\.duckdb$", p)
        if not m:
            continue
        try:
            con = duckdb.connect(os.path.join(HERE, p), read_only=True)
            row = con.execute("SELECT 1 FROM works WHERE id=?", [work_id]).fetchone()
            con.close()
        except Exception:  # a busy DB or one without a works table contributes nothing
            continue
        if row:
            return int(m.group(1))
    return 2025


def record(work_id, *, ingest_status, gates_passed=None, figures_status=None,
           escalate_reason=None, mid=None, year=None, db=True):
    """Upsert one paper's outcome into ingest_log.json and (optionally) the live DuckDB."""
    log = _load()
    log[work_id] = {
        "ingest_status": ingest_status,
        "gates_passed": gates_passed,
        "figures_status": figures_status,
        "escalate_reason": escalate_reason or None,
        "mid": mid,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    tmp = LOG + ".tmp"
    json.dump(log, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    os.replace(tmp, LOG)  # atomic — never leave a half-written log

    if db:
        y = year or year_for(work_id)
        dbp = os.path.join(HERE, f"works_{y}.duckdb")
        if os.path.isfile(dbp):
            import duckdb
            # The Platform's live refresh can hold a works DB open; the JSON write
            # above is the truth, so a locked mirror must never abort the run —
            # build-db re-overlays the log on the next rebuild anyway.
            try:
                con = duckdb.connect(dbp)
                try:
                    con.execute("""UPDATE works SET ingest_status=?, gates_passed=?,
                                     figures_status=?, escalate_reason=?, ingest_mid=?, ingest_ts=?
                                   WHERE id=?""",
                                [ingest_status, gates_passed, figures_status,
                                 escalate_reason or None, mid, log[work_id]["ts"], work_id])
                finally:
                    con.close()
            except Exception as e:
                print(f"      (works_{y} mirror skipped — {str(e)[:80]}; "
                      "log is truth, build-db will catch the DB up)")
    return log[work_id]


# ---- sidecar indexing: mirror the on-disk intra-article record into the DB projection ----
# The sidecar file (ingested/{id}/metadata.json, written by sidecar.py) is the source of
# truth; these columns are a rebuildable cache so the artifacts are queryable in SQL.
SIDE_COLS = (("sidecar_path", "VARCHAR"), ("sidecar", "JSON"),
             ("n_assets", "INTEGER"), ("err_count", "INTEGER"), ("warn_count", "INTEGER"))


def ensure_side_cols(con):
    for c, t in SIDE_COLS:
        con.execute(f"ALTER TABLE works ADD COLUMN IF NOT EXISTS {c} {t}")


def apply_sidecar(con, work_id, sidecar_path, sc):
    """UPDATE the DB projection for one sidecar (shared by index_sidecar and build_db)."""
    con.execute("""UPDATE works SET sidecar_path=?, sidecar=?, n_assets=?,
                     err_count=?, warn_count=? WHERE id=?""",
                [os.path.relpath(sidecar_path, HERE),
                 json.dumps(sc, ensure_ascii=False),
                 sc["assets"]["count"], sc["gates"]["errors"], sc["gates"]["warnings"],
                 work_id])


def index_sidecar(work_id, sidecar_path, year=None, db=True):
    """Read a sidecar file and mirror its projection into the live DuckDB."""
    sc = json.load(open(sidecar_path, encoding="utf-8"))
    if db:
        y = year or year_for(work_id)
        dbp = os.path.join(HERE, f"works_{y}.duckdb")
        if os.path.isfile(dbp):
            import duckdb
            # Same degrade-gracefully rule as record(): sidecar on disk is the truth.
            try:
                con = duckdb.connect(dbp)
                try:
                    ensure_side_cols(con)
                    apply_sidecar(con, work_id, sidecar_path, sc)
                finally:
                    con.close()
            except Exception as e:
                print(f"      (works_{y} sidecar mirror skipped — {str(e)[:80]}; "
                      "sidecar is truth, build-db will catch the DB up)")
    return sc
