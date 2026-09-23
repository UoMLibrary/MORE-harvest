#!/usr/bin/env python3
"""tei_pilot.py — batch-validate the Lane-B TEI->JATS chain against real TEI+PDF pairs.

For every work in harvest/pdfs_2025 with a fetched .grobid.xml, run the exact transform
chain a real convert_vor ingest runs — tei_to_jats (journal/publisher from
works_2025.duckdb, licence grepped from the VoR PDF, per-publisher rules applied) ->
crosswalk_generic -> the workstation gates — WITHOUT touching production state: no
ingested/ package, no ingest_log, no tracker. Output lands in the disposable
harvest/tei_pilot/ and a per-publisher report prints + persists (report.json) so rule
tweaks can be diffed run over run.

Figures are STUBBED (tiny placeholder PNGs for every <graphic> href) because this pilot
measures TEXT quality; figure capture is a separate step with its own design. That means
figure-related lint findings are structural only (captions, labels), never image truth.

Usage:  python tei_pilot.py [--only slug] [--keep]
"""
import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The gates live in vendor/scripts/ in this snapshot (see vendor/SOURCE.md);
# in the full workspace this points at the AAM workstation sibling instead.
WS = os.path.join(HERE, "vendor")
PDFS = os.path.join(HERE, "harvest", "pdfs_2025")
OUT = os.path.join(HERE, "harvest", "tei_pilot")
ANZSRC = os.path.join(HERE, "lanec", "anzsrc.xml")

sys.path.insert(0, HERE)
from ingest_one import cc_license_from_pdf  # noqa: E402  (the licence discipline, shared)

# a valid 1x1 grey PNG — the figure stub (text pilot; real capture is a separate step)
PNG_STUB = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108000000003a7e9b55"
    "0000000a49444154789c636000000002000148afa4710000000049454e44ae426082")


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def works_meta():
    """id -> (publisher, journal) from the router DB (authoritative, per Lane-B rule)."""
    import duckdb
    con = duckdb.connect(os.path.join(HERE, "works_2025.duckdb"), read_only=True)
    rows = con.execute("SELECT id, publisher, journal, title FROM works").fetchall()
    con.close()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def stub_figures(pkg_dir, article_xml):
    """Write a placeholder PNG for every graphic href so the fig gate tests STRUCTURE."""
    hrefs = re.findall(r'xlink:href="([^"]+)"', open(article_xml, encoding="utf-8").read())
    n = 0
    for h in hrefs:
        if h.startswith(("http:", "https:", "doi:")):
            continue
        dest = os.path.normpath(os.path.join(pkg_dir, h))
        if not dest.startswith(os.path.normpath(pkg_dir)):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(PNG_STUB)
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="restrict to one publisher slug")
    ap.add_argument("--keep", action="store_true", help="keep prior pilot output")
    args = ap.parse_args()

    manifest = json.load(open(os.path.join(PDFS, "_manifest.json"), encoding="utf-8"))
    meta = works_meta()
    if not args.keep and os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    pairs = []
    for r in manifest:
        tei = os.path.join(PDFS, r["publisher_slug"], f"{r['id']}.grobid.xml")
        if os.path.isfile(tei) and (not args.only or r["publisher_slug"] == args.only):
            pairs.append((r, tei))
    print(f"{len(pairs)} TEI+PDF pairs to run\n")

    stats = collections.defaultdict(lambda: {
        "n": 0, "validate_pass": 0, "lint_pass": 0, "errors": 0, "warnings": 0,
        "error_kinds": collections.Counter(), "warning_kinds": collections.Counter()})
    results = []

    for i, (r, tei) in enumerate(sorted(pairs, key=lambda p: (p[0]["publisher_slug"], p[0]["id"]))):
        slug, wid = r["publisher_slug"], r["id"]
        publisher, journal, title = meta.get(wid, (r.get("publisher"), None, None))
        pdf = os.path.join(HERE, r["path"]) if not os.path.isabs(r["path"]) else r["path"]
        mid = f"MORE-2025-99{i:04d}"
        pkg = os.path.join(OUT, mid)
        os.makedirs(pkg, exist_ok=True)

        lic_url, lic_prose = cc_license_from_pdf(pdf) if os.path.isfile(pdf) else (None, None)
        lic = lic_url or lic_prose

        jats = os.path.join(pkg, "grobid.jats.xml")
        t = sh(sys.executable, os.path.join(HERE, "lanec", "tei_to_jats.py"), tei, "-o", jats,
               "--journal", journal or "", "--license", lic or "", "--publisher", publisher or "",
               "--title", title or "")
        if not os.path.isfile(jats):
            print(f"  {wid} [{slug}] tei_to_jats FAILED: {t.stderr.strip()[:120]}")
            stats[slug]["n"] += 1
            stats[slug]["error_kinds"]["tei_to_jats crashed"] += 1
            continue

        c = sh(sys.executable, os.path.join(HERE, "lanec", "crosswalk_generic.py"),
               jats, "-o", pkg, "--mid", mid, "--anzsrc", ANZSRC)
        art = os.path.join(pkg, "article.xml")
        if not os.path.isfile(art):
            print(f"  {wid} [{slug}] crosswalk FAILED: {(c.stderr or c.stdout).strip()[:120]}")
            stats[slug]["n"] += 1
            stats[slug]["error_kinds"]["crosswalk crashed"] += 1
            continue

        stub_figures(pkg, art)

        v = sh(sys.executable, os.path.join(WS, "scripts", "validate_jats.py"), art)
        v_line = (v.stdout.strip().splitlines() or ["?"])[-1]
        v_pass = "PASS" in v_line.upper() or "OK" in v_line.upper()

        hl = sh(sys.executable, os.path.join(WS, "scripts", "jats_house_lint.py"), art)
        m = re.search(r"Result: (\w+) \((\d+) error\(s\), (\d+) warning\(s\)\)", hl.stdout)
        l_pass, n_err, n_warn = (m.group(1) == "PASS", int(m.group(2)), int(m.group(3))) if m else (False, -1, -1)

        s = stats[slug]
        s["n"] += 1
        s["validate_pass"] += v_pass
        s["lint_pass"] += l_pass
        s["errors"] += max(n_err, 0)
        s["warnings"] += max(n_warn, 0)
        for line in hl.stdout.splitlines():
            line = line.strip()
            # normalise messages into kinds: drop ids/numbers so identical rules group
            if line.startswith("ERROR"):
                s["error_kinds"][re.sub(r"[A-Za-z0-9_.:/#-]*\d[A-Za-z0-9_.:/#-]*", "N", line[5:].strip())[:90]] += 1
            elif line.startswith("warning"):
                s["warning_kinds"][re.sub(r"[A-Za-z0-9_.:/#-]*\d[A-Za-z0-9_.:/#-]*", "N", line[7:].strip())[:90]] += 1
        lic_note = "url" if lic_url else ("prose" if lic_prose else "NONE")
        print(f"  {wid} [{slug:28s}] validate={'PASS' if v_pass else 'FAIL'} "
              f"lint={'PASS' if l_pass else 'FAIL'} err={n_err} warn={n_warn} lic={lic_note}")
        results.append({"id": wid, "slug": slug, "mid": mid, "validate": v_pass,
                        "lint_pass": l_pass, "errors": n_err, "warnings": n_warn,
                        "license": lic_url or lic_prose})

    print("\n=== per publisher ===")
    print(f"{'publisher':30s} {'n':>3} {'validate':>9} {'lint':>5} {'err':>4} {'warn':>5}")
    for slug, s in sorted(stats.items()):
        print(f"{slug:30s} {s['n']:>3} {s['validate_pass']:>9} {s['lint_pass']:>5} "
              f"{s['errors']:>4} {s['warnings']:>5}")

    print("\n=== top finding kinds (all publishers) ===")
    all_err = collections.Counter()
    all_warn = collections.Counter()
    for s in stats.values():
        all_err.update(s["error_kinds"])
        all_warn.update(s["warning_kinds"])
    for kind, n in all_err.most_common(8):
        print(f"  ERROR x{n:<3} {kind}")
    for kind, n in all_warn.most_common(12):
        print(f"  warn  x{n:<3} {kind}")

    report = {"results": results,
              "stats": {k: {**v, "error_kinds": dict(v["error_kinds"]),
                            "warning_kinds": dict(v["warning_kinds"])} for k, v in stats.items()}}
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(f"\nreport -> {os.path.relpath(os.path.join(OUT, 'report.json'), HERE)}")


if __name__ == "__main__":
    main()
