#!/usr/bin/env python3
"""Lane-B fidelity-gate golden test — the gate itself is regression-tested.

Runs the REAL Lane-B chain (tei_to_jats -> crosswalk_generic) on the committed
TEI fixture (W7133915096, Taylor & Francis, CC-BY 4.0, Crystallography Reviews),
then asserts three things against the committed PDF-text snapshot:

  1. the INTACT conversion passes the fidelity gate (completeness/grounding/mass/parity)
  2. a MUTANT with most of its body deleted does NOT pass (the dropped-section case
     the gate exists to catch — house-lint stays green on exactly this mutant)
  3. a MUTANT missing one reference breaks ref parity -> FAIL

Run before committing any change to tei_to_jats, crosswalk_generic or pdf_fidelity:
    python tests/fidelity_pilot.py
Exit 0 = all green. Like crosswalk_pilot, no network, no key, no production state.
"""
import json
import os
import subprocess
import sys
import tempfile

from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
H = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
WID = "W7133915096"

sys.path.insert(0, H)
from lanec import pdf_fidelity  # noqa: E402


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def build_article(workdir):
    """The real Lane-B chain: TEI -> generic JATS -> house crosswalk."""
    meta = json.load(open(os.path.join(FIX, f"laneb_{WID}.meta.json"), encoding="utf-8"))
    jats = os.path.join(workdir, "grobid.jats.xml")
    r = sh(sys.executable, os.path.join(H, "lanec", "tei_to_jats.py"),
           os.path.join(FIX, f"laneb_{WID}.grobid.xml"), "-o", jats,
           "--journal", meta["journal"] or "", "--license", meta["license"] or "",
           "--publisher", meta["publisher"] or "", "--title", meta["title"] or "")
    assert os.path.isfile(jats), f"tei_to_jats failed: {r.stderr[:300]}"
    r = sh(sys.executable, os.path.join(H, "lanec", "crosswalk_generic.py"),
           jats, "-o", workdir, "--mid", "MORE-2025-990000",
           "--anzsrc", os.path.join(H, "lanec", "anzsrc.xml"))
    art = os.path.join(workdir, "article.xml")
    assert os.path.isfile(art), f"crosswalk failed: {(r.stderr or r.stdout)[:300]}"
    return art


def main():
    pdf_txt = open(os.path.join(FIX, f"laneb_{WID}.pdftext.txt"), encoding="utf-8").read()
    tei = os.path.join(FIX, f"laneb_{WID}.grobid.xml")
    failures = []

    with tempfile.TemporaryDirectory() as tmp:
        art = build_article(tmp)

        # 1 — intact conversion passes
        fid = pdf_fidelity.check(art, tei_path=tei, pdf_txt=pdf_txt)
        m = fid["metrics"]
        print(f"intact:      {fid['verdict'].upper()} completeness={m['completeness']:.2f} "
              f"grounding={m['grounding']:.2f} refs={m['ref_jats']}/{m['ref_tei']}")
        if fid["verdict"] != "pass":
            failures.append(f"intact conversion should PASS, got {fid['verdict']}: {fid['reasons']}")

        # 2 — dropped-body mutant must not pass
        root = etree.parse(art).getroot()
        body = next(root.iter("body"))
        secs = list(body)
        for sec in secs[:max(1, len(secs) * 2 // 3)]:   # delete ~two-thirds of the body
            body.remove(sec)
        mut = os.path.join(tmp, "mutant_dropped.xml")
        etree.ElementTree(root).write(mut, encoding="utf-8")
        fid = pdf_fidelity.check(mut, tei_path=tei, pdf_txt=pdf_txt)
        print(f"dropped-body: {fid['verdict'].upper()} "
              f"completeness={fid['metrics']['completeness']:.2f}")
        if fid["verdict"] == "pass":
            failures.append("a conversion missing two-thirds of its body must never PASS")

        # 3 — one missing reference breaks parity -> FAIL
        root = etree.parse(art).getroot()
        ref = next(root.iter("ref"))
        ref.getparent().remove(ref)
        mut = os.path.join(tmp, "mutant_ref.xml")
        etree.ElementTree(root).write(mut, encoding="utf-8")
        fid = pdf_fidelity.check(mut, tei_path=tei, pdf_txt=pdf_txt)
        print(f"dropped-ref:  {fid['verdict'].upper()} "
              f"refs={fid['metrics']['ref_jats']}/{fid['metrics']['ref_tei']}")
        if fid["verdict"] != "fail" or not any("parity" in r for r in fid["reasons"]):
            failures.append(f"a missing reference must FAIL ref parity, got {fid['verdict']}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  - " + f)
        return 1
    print("\nall green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
