#!/usr/bin/env python3
"""Lane-C golden fixtures — the crosswalk's standing regression test.

Six committed source XMLs (real CC-BY papers, one per publisher flavour the
crosswalk must handle) run through the REAL chain — pre-transforms sniffed by
header exactly as ingest_one does, crosswalk, body-LaTeX conversion, the
workstation validate gate — and SEMANTIC expectations are asserted per fixture
(root becomes <article>, every <aff> has an id, zero residual prose LaTeX, at
least N linked citations…). No network, no figures: asset resolution is the
ingest run's concern, not the transform's, so the house-lint isn't run here
(its asset errors would only measure the missing figures).

Run BEFORE committing any transform change; tei_pilot.py is Lane B's twin.

    python tests/crosswalk_pilot.py            # assert against expected.json
    python tests/crosswalk_pilot.py --rebase   # accept current behaviour as the baseline

`--rebase` rewrites expected.json from the current run — only do that when the
CHANGELOG entry for your change explains why the baseline moved.

Fixture provenance (all CC-BY Versions of Record, committed under their licence):
  pmc_clean.xml       W4407798564  pmc               ordinary clean PMC JATS
  pmc_articleset.xml  W4407405359  pmc               <pmc-articleset> wrapper case
  pmc_aff_noid.xml    W4407111158  pmc               affiliations lack @id
  aps.xml             W4404395497  scoap3_aps        APS JATS 1.4 Publishing
  native_open.xml     W4404459448  jats_native_open  publisher-native open JATS
  jhep_latex_body.xml W4404371760  scoap3_jhep       raw LaTeX in body prose
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
HARVEST = os.path.dirname(HERE)
WS = os.path.join(HARVEST, "vendor")
sys.path.insert(0, HARVEST)
sys.path.insert(0, os.path.join(HARVEST, "lanec"))

EXPECTED = os.path.join(HERE, "expected.json")
ANZ = ('<article-categories><subj-group subj-group-type="anzsrc">'
       '<subject>fixture</subject></subj-group></article-categories>')


def ln(el):
    t = el.tag
    return "" if not isinstance(t, str) else t.rsplit("}", 1)[-1]


def run_chain(src):
    """Fixture source -> (article root, validate_pass) via the real transforms."""
    import latex_body_clean
    from lanec import crosswalk_generic as cw
    tmp = tempfile.mkdtemp(prefix="cwpilot_")
    try:
        os.makedirs(os.path.join(tmp, "assets"), exist_ok=True)
        head = open(src, "rb").read(600)
        src_xml = src
        if b"//ES//DTD" in head:                      # Elsevier pre-transform
            interm = os.path.join(tmp, "elsevier.jats.xml")
            subprocess.run([sys.executable, os.path.join(HARVEST, "lanec", "elsevier_to_jats.py"),
                            src, "-o", interm], capture_output=True)
            src_xml = interm
        elif b"tei-c.org/ns/1.0" in head:             # Lane-B TEI pre-transform
            interm = os.path.join(tmp, "grobid.jats.xml")
            subprocess.run([sys.executable, os.path.join(HARVEST, "lanec", "tei_to_jats.py"),
                            src, "-o", interm, "--journal", "Fixture Journal"],
                           capture_output=True)
            src_xml = interm
        ax, _log, _root = cw.crosswalk(src_xml, tmp, "MORE-FIXTURE-000001", ANZ)
        raw = open(ax, encoding="utf-8").read()
        if "\\cite" in raw or re.search(r"(?<!\\)\$", raw):
            latex_body_clean.convert_file(ax)
        v = subprocess.run([sys.executable, os.path.join(WS, "scripts", "validate_jats.py"), ax],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        vlast = (v.stdout.strip().splitlines() or ["?"])[-1]
        root = etree.parse(ax).getroot()
        return root, ("PASS" in vlast and "FAIL" not in vlast)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def measure(root, validate_pass):
    """The semantic fingerprint a transform change must not silently move."""
    import latex_body_clean
    affs = root.findall(".//{*}aff")
    return {
        "validate": bool(validate_pass),
        "root_is_article": ln(root) == "article",
        "has_title": bool("".join(root.find(".//{*}article-title").itertext()).strip()
                          if root.find(".//{*}article-title") is not None else ""),
        "contrib_count": len(root.findall(".//{*}contrib[@contrib-type='author']")),
        "affs_all_have_ids": all(a.get("id") for a in affs) if affs else True,
        "residual_latex": latex_body_clean.residual_latex(root),
        "bibr_links": len(root.findall(".//{*}xref[@ref-type='bibr']")),
        "ref_count": len(root.findall(".//{*}ref")),
        "fig_count": len(root.findall(".//{*}fig")),
        "formula_count": (len(root.findall(".//{*}inline-formula"))
                          + len(root.findall(".//{*}disp-formula"))),
        "cc_license_typed": any(l.get("license-type") == "creative-commons"
                                for l in root.findall(".//{*}license")),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rebase", action="store_true",
                    help="accept current behaviour as the new baseline")
    args = ap.parse_args()

    fixtures = sorted(f for f in os.listdir(os.path.join(HERE, "fixtures")) if f.endswith(".xml"))
    got = {}
    for f in fixtures:
        root, vpass = run_chain(os.path.join(HERE, "fixtures", f))
        got[f] = measure(root, vpass)

    if args.rebase:
        json.dump(got, open(EXPECTED, "w", encoding="utf-8"), indent=1, sort_keys=True)
        print(f"rebased {EXPECTED} on current behaviour — record WHY in CHANGELOG.md")
        return 0

    if not os.path.isfile(EXPECTED):
        sys.exit("no expected.json — run once with --rebase to set the baseline")
    want = json.load(open(EXPECTED, encoding="utf-8"))
    failed = 0
    for f in fixtures:
        diffs = {k: (want.get(f, {}).get(k), v) for k, v in got[f].items()
                 if want.get(f, {}).get(k) != v}
        if diffs:
            failed += 1
            print(f"REGRESSION  {f}:")
            for k, (w, g) in sorted(diffs.items()):
                print(f"    {k}: expected {w!r}, got {g!r}")
        else:
            print(f"ok          {f}")
    if failed:
        print(f"\n{failed}/{len(fixtures)} fixture(s) moved — if intentional, "
              "--rebase and explain in CHANGELOG.md")
        return 1
    print(f"\nall {len(fixtures)} fixtures match the baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
