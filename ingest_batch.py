#!/usr/bin/env python3
"""Run a batch of fetched papers through the FULL ingest chain and score the result.

For each fetched paper of a route: assign a PROVISIONAL ANZSRC classification from its
OpenAlex topic domain->division (flagged for cataloguer review — ANZSRC is the one genuine
human judgement call), then run ingest_one (publisher figures -> crosswalk -> gates) and
record whether it produced a gate-passing, figure-complete house package.

Usage:  python ingest_batch.py --route pmc --limit 10
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

import ingest_log

HERE = os.path.dirname(os.path.abspath(__file__))
# The gates live in vendor/scripts/ in this snapshot (see vendor/SOURCE.md);
# in the full workspace this points at the AAM workstation sibling instead.
WS = os.path.join(HERE, "vendor")
ANZSRC = json.load(open(os.path.join(WS, "scripts", "data", "anzsrc_2020.json"), encoding="utf-8"))["for"]

# OpenAlex field (26) -> ANZSRC 2-digit division. Provisional; the division is what we're
# confident of, the specific field is left as the division's "Other … nec" pending review.
FIELD_DIV = {
    "Medicine": "32", "Nursing": "42", "Health Professions": "42", "Dentistry": "32",
    "Pharmacology, Toxicology and Pharmaceutics": "32", "Immunology and Microbiology": "32",
    "Neuroscience": "32", "Biochemistry, Genetics and Molecular Biology": "31",
    "Agricultural and Biological Sciences": "30", "Veterinary": "30",
    "Environmental Science": "41", "Chemistry": "34", "Chemical Engineering": "40",
    "Materials Science": "40", "Engineering": "40", "Energy": "40",
    "Physics and Astronomy": "51", "Earth and Planetary Sciences": "37",
    "Mathematics": "49", "Computer Science": "46", "Decision Sciences": "46",
    "Economics, Econometrics and Finance": "38", "Business, Management and Accounting": "35",
    "Social Sciences": "44", "Psychology": "52", "Arts and Humanities": "36",
}
DOMAIN_DIV = {"Health Sciences": "42", "Life Sciences": "31",
              "Physical Sciences": "51", "Social Sciences": "44"}


def openalex_topic(work_id):
    # Through harvest_openalex.get so the org key travels as the Bearer header it
    # requires — as an api_key query param the key is IGNORED and the call silently
    # falls into the (budget-capped) keyless pool.
    import harvest_openalex
    try:
        pt = harvest_openalex.get(f"/works/{work_id}",
                                  select="primary_topic").get("primary_topic") or {}
        field = (pt.get("field") or {}).get("display_name")
        domain = (pt.get("domain") or {}).get("display_name")
        return field, domain
    except Exception:
        return None, None


def anzsrc_triple(div):
    """(division, group-nec, field-nec) code:label pairs with exact official labels."""
    g, f = div + "99", div + "9999"
    return [(div, ANZSRC.get(div, "").title()),
            (g, ANZSRC.get(g, "")), (f, ANZSRC.get(f, ""))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="pmc")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--redo", action="store_true",
                    help="re-process papers already ingested/partial (default: skip them)")
    ap.add_argument("--no-retry", action="store_true",
                    help="skip prior failed/escalate papers too (default: retry them)")
    args = ap.parse_args()

    xmls = sorted(glob.glob(os.path.join(HERE, "fetched", args.route, "*.xml")))[:args.limit]
    if not xmls:
        sys.exit(f"no fetched XML for route {args.route}")

    # mids are PERSISTENT: a work ingested before keeps its mid (from ingest_log.json);
    # new works allocate max(existing)+1. Without this every batch restarted at 910001,
    # so re-runs and different routes minted COLLIDING mids.
    log = ingest_log._load()
    used = [int(r["mid"].rsplit("-", 1)[1]) for r in log.values()
            if r.get("mid") and r["mid"].rsplit("-", 1)[1].isdigit()]
    seq = max(used, default=910000)

    rows = []
    for xp in xmls:
        wid = os.path.basename(xp)[:-4]
        # skip papers already ingested/partial (re-run only failures/new); --redo forces
        if not args.redo and log.get(wid, {}).get("ingest_status") in ("ingested", "partial"):
            continue
        # --no-retry: also skip prior failed/escalate — licence-class fails re-fail
        # identically every run, and at ~30s/paper the accumulated tail costs real
        # wall-clock. Rerun the tail deliberately (default) after an engine change.
        if args.no_retry and log.get(wid, {}).get("ingest_status") in ("failed", "escalate"):
            continue
        field, domain = openalex_topic(wid)
        div = FIELD_DIV.get(field) or DOMAIN_DIV.get(domain) or "42"
        triple = anzsrc_triple(div)
        forarg = ",".join(f'{c}:{l}' for c, l in triple)
        prior = log.get(wid, {}).get("mid")
        if prior:
            mid = prior
        else:
            # the mid's year is the work's corpus year (which works_YYYY.duckdb holds
            # it), not a hardcoded 2025 — the corpus is multi-year since the intake
            # seam. The seq suffix stays GLOBAL across years, so mids can never
            # collide whatever year they carry.
            seq += 1
            mid = f"MORE-{ingest_log.year_for(wid)}-{seq:06d}"
        r = subprocess.run([sys.executable, os.path.join(HERE, "ingest_one.py"), wid,
                            "--mid", mid, "--for", forarg],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = r.stdout
        val = "PASS" if re.search(r"validate: PASS", out) else "FAIL"
        lint = "PASS" if re.search(r"house-lint: Result: PASS", out) else "FAIL"
        # the Lane-B fidelity gate [2e]: FAIL means the package did not survive an
        # independent reading of its own PDF — never clean, whatever the lint said
        fid = re.search(r"\[2e\] fidelity: (PASS|FLAG|FAIL|SKIPPED)", out)
        if fid and fid.group(1) == "FAIL":
            lint = "FAIL"
        fm = re.search(r"\((\d+)/(\d+) images matched", out)
        pm = re.search(r"fallback: (\d+) figure", out)
        nfig = int(fm.group(1)) if fm else (int(pm.group(1)) if pm else 0)
        both = val == "PASS" and lint == "PASS"
        lic = "PASS" if re.search(r"licence: PASS", out) else "FAIL"
        errs = re.findall(r"ERROR\s+(.*)", out)
        reason = ""
        if not both:
            if any("M" in e and ".gif" in e for e in errs):
                reason = "inline-math images (no MathML, not in OA package) -> ESCALATE"
            elif errs:
                reason = re.sub(r"'[^']*'", "X", errs[0])[:60]
        if lic == "FAIL" and not reason:
            reason = "licence not CC-BY -> FAILED"
        if fid and not reason:
            fdetail = re.search(r"fidelity gate: \w+ \(([^)]*)\)", out)
            if fid.group(1) == "FAIL":
                reason = ("fidelity: " + (fdetail.group(1) if fdetail else "see sidecar"))[:60]
            elif fid.group(1) == "FLAG":
                # ships (gates green) but the reason rides in the tracker so the
                # worklist/board can surface it for a human look
                reason = ("fidelity flag: " + (fdetail.group(1) if fdetail else "see sidecar"))[:60]
        # write the outcome back to the work-tracker (ingest_log.json + live DuckDB)
        is_esc = "ESCALATE" in reason
        # figures_status must reflect ACTUAL figure coverage, not the lint verdict: a lint
        # failure for a NON-figure reason (e.g. a rights-statement error) must not be
        # laundered into "partial" (a usable package) — that is a real failure. Only call it
        # partial when the lint errors are actually about figure/graphic coverage.
        fig_errs = [e for e in errs if "graphic" in e.lower() or "fig" in e.lower()]
        if lint == "PASS":
            fig_status = "complete"
        elif fig_errs:
            fig_status = "partial" if nfig > 0 else "none"
        else:
            fig_status = "complete"      # figures fine; lint failed for another reason -> failed
        status = ingest_log.classify(val == "PASS", lint == "PASS", fig_status,
                                     reason if is_esc else None, licence_pass=(lic == "PASS"))
        ingest_log.record(wid, ingest_status=status, gates_passed=both,
                          figures_status=fig_status, escalate_reason=(reason or None),
                          mid=mid)
        rows.append((wid, field or domain or "?", div, nfig, val, lint, both, reason, status))
        print(f"  {wid} [{field or domain}] div{div} imgs={nfig} validate={val} lint={lint} "
              f"-> {status.upper()} {'** PASS **' if both else '-- ' + reason}")

    npass = sum(1 for r in rows if r[6])
    print(f"\n=== BATCH SCORECARD ({args.route}) ===")
    print(f"  attempted:            {len(rows)}")
    print(f"  full pass (both gates): {npass}")
    print(f"  validate failed:      {sum(1 for r in rows if r[4]=='FAIL')}")
    print(f"  house-lint failed:    {sum(1 for r in rows if r[5]=='FAIL')}")
    print(f"  total figures placed: {sum(r[3] for r in rows)}")
    print("  --- work-tracker status (written back to ingest_log.json + DuckDB) ---")
    for s in ingest_log.STATUSES:
        c = sum(1 for r in rows if r[8] == s)
        if c:
            print(f"    {s:10s}: {c}")
    ing = os.path.join(HERE, "ingested")
    sz = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(ing) for f in fs)
    print(f"  ingested/ footprint:  {sz/1e6:.1f} MB")
    print("  NOTE: ANZSRC is auto-provisional (division-level, flagged for cataloguer review).")


if __name__ == "__main__":
    main()
