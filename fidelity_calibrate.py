#!/usr/bin/env python3
"""Calibrate the Lane-B fidelity gate against the tei_pilot corpus — the EVIDENCE tool.

Runs lanec/pdf_fidelity.py's own metrics over every TEI+PDF pair in harvest/pdfs_2025
whose converted package sits in harvest/tei_pilot (run tei_pilot.py first), splits the
distributions by the pilot's lint verdict, and reports per-publisher medians + the
verdict tally the current thresholds would give.

THE DISCIPLINE: a fidelity threshold (pdf_fidelity constants or a rule card's
fidelity_floor) only ever moves on this report's evidence, with a CHANGELOG entry.
Run it after any converter or gate change:  python fidelity_calibrate.py

Report persists to harvest/tei_pilot/fidelity_calibration.json so runs can be diffed.
"""
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PDFS = os.path.join(HERE, "harvest", "pdfs_2025")
PILOT = os.path.join(HERE, "harvest", "tei_pilot")

sys.path.insert(0, HERE)
from lanec import pdf_fidelity  # noqa: E402  (single source of truth for the metrics)


def main():
    report = json.load(open(os.path.join(PILOT, "report.json"), encoding="utf-8"))
    manifest = {r["id"]: r for r in
                json.load(open(os.path.join(PDFS, "_manifest.json"), encoding="utf-8"))}

    rows = []
    for res in report["results"]:
        m = manifest.get(res["id"])
        if not m:
            continue
        pdf = m["path"] if os.path.isabs(m["path"]) else os.path.join(HERE, m["path"])
        tei = os.path.join(PDFS, res["slug"], f"{res['id']}.grobid.xml")
        art = os.path.join(PILOT, res["mid"], "article.xml")
        if not all(os.path.isfile(p) for p in (pdf, tei, art)):
            continue
        try:
            fid = pdf_fidelity.check(art, pdf, tei_path=tei)
        except Exception as e:  # noqa: BLE001 — a broken pair is data, not a crash
            print(f"  SKIP {res['id']} [{res['slug']}]: {type(e).__name__}: {e}")
            continue
        rows.append({"id": res["id"], "slug": res["slug"], "mid": res["mid"],
                     "lint": res["lint_pass"], "verdict": fid["verdict"],
                     "reasons": fid["reasons"], **fid["metrics"]})

    out = os.path.join(PILOT, "fidelity_calibration.json")
    json.dump(rows, open(out, "w", encoding="utf-8"), indent=1)
    print(f"{len(rows)} papers measured -> {os.path.relpath(out, HERE)}\n")

    def dist(vals, label):
        if not vals:
            return
        srt = sorted(vals)
        p5 = srt[max(0, int(len(srt) * 0.05) - 1)] if len(srt) >= 20 else srt[0]
        print(f"  {label:13s} n={len(vals):2d} min={srt[0]:.3f} p5={p5:.3f} "
              f"median={statistics.median(vals):.3f} max={srt[-1]:.3f}")

    for group, name in ((True, "LINT-GREEN"), (False, "LINT-FAIL")):
        g = [r for r in rows if r["lint"] == group]
        print(f"=== {name} ({len(g)}) ===")
        for metric in ("completeness", "grounding", "mass_ratio", "num_recall"):
            dist([r[metric] for r in g], metric)

    print("\n=== per-publisher completeness medians (lint-green only) ===")
    for slug in sorted({r["slug"] for r in rows}):
        g = [r["completeness"] for r in rows if r["slug"] == slug and r["lint"]]
        if g:
            print(f"  {slug:30s} n={len(g):2d} median={statistics.median(g):.3f} min={min(g):.3f}")

    print("\n=== verdicts at current thresholds ===")
    for v in ("pass", "flag", "fail"):
        n = sum(1 for r in rows if r["verdict"] == v)
        print(f"  {v.upper():5s}: {n}")
    for r in rows:
        if r["verdict"] != "pass":
            print(f"    {r['id']} [{r['slug']:28s}] lint={'PASS' if r['lint'] else 'FAIL'} "
                  f"{r['verdict'].upper()}: {'; '.join(r['reasons'])[:100]}")


if __name__ == "__main__":
    main()
