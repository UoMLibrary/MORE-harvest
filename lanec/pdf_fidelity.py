#!/usr/bin/env python3
"""Lane-B fidelity gate (ingest_one step [2e]): a second, independent reading of the PDF.

Lane B converts GROBID's TEI — ONE extractor's silent output. The structural gates
validate what EXISTS in the package; nothing checks what SHOULD exist (proof: the
back-matter hole, 93/93 divs dropped with every package lint-green, found by this
gate's calibration). This closes that hole deterministically — the workstation's
council-of-extractors principle at Lane-B economics: no queue, no adjudication, just
set arithmetic on two token streams (~2-4s per paper).

The five checks (thresholds MEASURED on the 76-pair pilot corpus, 2026-07-15 — they
move only on fidelity_calibrate.py evidence, recorded in CHANGELOG.md):

  1. ref parity    (hard)    JATS <ref> count == TEI biblStruct count. A converter
                             invariant: all 76 calibration papers sat at exactly 1.0.
  2. grounding     (hard)    >=0.60 of JATS 5-shingles found in the PDF. A breach means
                             WRONG PAIRING (TEI/PDF version mismatch, wrong file) —
                             invisible to every other gate. Calibration green min: .693.
  3. completeness  (tiered)  fraction of PDF 5-shingles found in the JATS.
                             < 0.40 FAIL | 0.40..floor FLAG | >= floor PASS
                             (default floor 0.65; green median .829, p5 .670; per-
                             publisher override via PublisherRule.fidelity_floor).
  4. body mass     (hard)    JATS letter-tokens >= 0.35 x PDF letter-tokens, and PDF
                             letter-tokens >= 2000. Catches the two catastrophic classes
                             seen live: an empty converted body (0 vs 25,147 tokens) and
                             a 1-page bad fetch that isn't the article.
  5. numbers       (advisory) reported, never blocks — PDF-side numerals are structurally
                             noisy (page numbers, axis ticks, table images).

Shingles use LETTER-BEARING tokens only: this one rule removes both systematic noise
sources found in calibration (line numbers interleaved through RSC 'Accepted
Manuscript' proofs; figure axis-tick text in the PDF layer). Known FLAG-band classes
(never FAIL): line-numbered proofs, math-dense papers — triage takes seconds because
the sidecar carries the largest missing runs.
"""
import argparse
import json
import re
import unicodedata

from lxml import etree

# ---- thresholds (calibrated; see module docstring) ------------------------------------
GROUNDING_FLOOR = 0.60
COMPLETENESS_FAIL = 0.40
COMPLETENESS_PASS = 0.65     # default; PublisherRule.fidelity_floor overrides
MASS_RATIO_FLOOR = 0.35
PDF_TOKEN_FLOOR = 2000
SHINGLE_N = 5
TOP_RUNS = 5

_LIG = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}
_MATH_TAGS = {"tex-math", "math"}          # excluded from JATS text (PDF math is glyph soup)


def norm_tokens(text):
    for k, v in _LIG.items():
        text = text.replace(k, v)
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)      # de-hyphenate line breaks
    return re.findall(r"[a-z0-9]+", text)


def alpha_tokens(toks):
    """Letter-bearing tokens only — drops line numbers, page numbers, axis ticks."""
    return [t for t in toks if any(c.isalpha() for c in t)]


def _shingle_list(toks, n=SHINGLE_N):
    return [" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)]


def jats_text(root):
    """Prose of abstract + body + back, excluding math subtrees."""
    parts = []
    for tag in ("abstract", "body", "back"):
        for el in root.iter(tag):
            skip = None
            for sub in el.iter():
                if not isinstance(sub.tag, str):        # comments / PIs
                    continue
                if skip is not None:
                    if any(a is skip for a in sub.iterancestors()):
                        continue                          # inside the skipped math subtree
                    skip = None
                if etree.QName(sub).localname in _MATH_TAGS:
                    skip = sub
                    if sub.tail:
                        parts.append(sub.tail)
                    continue
                if sub.text:
                    parts.append(sub.text)
                if sub.tail:
                    parts.append(sub.tail)
            break
    return " ".join(parts)


def pdf_text(pdf_path):
    import fitz
    doc = fitz.open(pdf_path)
    try:
        return "\n".join(p.get_text() for p in doc)
    finally:
        doc.close()


def tei_bib_count(tei_path):
    root = etree.parse(tei_path).getroot()
    return len(root.findall(".//{http://www.tei-c.org/ns/1.0}listBibl/"
                            "{http://www.tei-c.org/ns/1.0}biblStruct"))


def evaluate(jats_root, pdf_txt, tei_bibs=None, pass_floor=None):
    """Core check: converted JATS vs an independent PDF reading. Returns the verdict
    dict that ships in the sidecar (verdict, reasons, metrics, top missing runs)."""
    floor = pass_floor or COMPLETENESS_PASS
    ptoks_all = norm_tokens(pdf_txt)
    jtoks_all = norm_tokens(jats_text(jats_root))
    ptoks, jtoks = alpha_tokens(ptoks_all), alpha_tokens(jtoks_all)
    plist = _shingle_list(ptoks)
    psh, jsh = set(plist), set(_shingle_list(jtoks))

    completeness = len(psh & jsh) / len(psh) if psh else 0.0
    grounding = len(jsh & psh) / len(jsh) if jsh else 0.0
    mass_ratio = (len(jtoks) / len(ptoks)) if ptoks else 0.0
    ref_jats = sum(1 for el in jats_root.iter()
                   if isinstance(el.tag, str) and etree.QName(el).localname == "ref")

    pnums = {t for t in ptoks_all if any(c.isdigit() for c in t) and len(t) >= 2}
    jnums = {t for t in jtoks_all if any(c.isdigit() for c in t) and len(t) >= 2}
    num_recall = len(pnums & jnums) / len(pnums) if pnums else 1.0

    reasons = []
    if tei_bibs is not None and ref_jats != tei_bibs:
        reasons.append(f"ref parity broken: {ref_jats} JATS refs vs {tei_bibs} TEI biblStructs")
    if len(ptoks) < PDF_TOKEN_FLOOR:
        reasons.append(f"suspect source PDF: {len(ptoks)} letter-tokens < {PDF_TOKEN_FLOOR}")
    if mass_ratio < MASS_RATIO_FLOOR:
        reasons.append(f"body mass {mass_ratio:.2f} < {MASS_RATIO_FLOOR} of the PDF")
    if grounding < GROUNDING_FLOOR:
        reasons.append(f"grounding {grounding:.2f} < {GROUNDING_FLOOR} (wrong pairing?)")
    if completeness < COMPLETENESS_FAIL:
        reasons.append(f"completeness {completeness:.2f} < {COMPLETENESS_FAIL}")
    if reasons:
        verdict = "fail"
    elif completeness < floor:
        verdict = "flag"
        reasons.append(f"completeness {completeness:.2f} below the {floor:.2f} floor — "
                       "review the missing runs")
    else:
        verdict = "pass"

    # largest contiguous runs of PDF shingles absent from the JATS — the triage evidence
    runs, start = [], None
    for i, s in enumerate(plist):
        if s not in jsh:
            if start is None:
                start = i
        elif start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(plist)))
    runs.sort(key=lambda r: r[1] - r[0], reverse=True)
    missing_runs = [{"shingles": b - a, "at_token": a,
                     "snippet": " ".join(ptoks[a:a + 24])[:160]}
                    for a, b in runs[:TOP_RUNS] if b - a >= SHINGLE_N]

    return {
        "verdict": verdict,
        "reasons": reasons,
        "metrics": {"completeness": round(completeness, 3), "grounding": round(grounding, 3),
                    "mass_ratio": round(mass_ratio, 3), "num_recall": round(num_recall, 3),
                    "pdf_tokens": len(ptoks), "jats_tokens": len(jtoks),
                    "ref_jats": ref_jats, "ref_tei": tei_bibs,
                    "pass_floor": round(floor, 3)},
        "missing_runs": missing_runs,
    }


def check(article_xml, pdf_path=None, tei_path=None, pass_floor=None, pdf_txt=None):
    """File-level wrapper: load the package article, the PDF text (or take it directly —
    the test harness passes a committed text snapshot), and the TEI ref count."""
    root = etree.parse(article_xml).getroot()
    if pdf_txt is None:
        pdf_txt = pdf_text(pdf_path)
    bibs = tei_bib_count(tei_path) if tei_path else None
    return evaluate(root, pdf_txt, tei_bibs=bibs, pass_floor=pass_floor)


def main():
    ap = argparse.ArgumentParser(description="Lane-B fidelity gate: JATS vs PDF")
    ap.add_argument("article", help="package article.xml")
    ap.add_argument("pdf", help="source VoR pdf")
    ap.add_argument("--tei", default=None, help="GROBID TEI (enables ref-parity check)")
    ap.add_argument("--floor", type=float, default=None, help="completeness PASS floor")
    ap.add_argument("--json", action="store_true", help="emit the full JSON block")
    args = ap.parse_args()
    fid = check(args.article, args.pdf, tei_path=args.tei, pass_floor=args.floor)
    m = fid["metrics"]
    print(f"fidelity: {fid['verdict'].upper()} "
          f"(completeness={m['completeness']:.2f} grounding={m['grounding']:.2f} "
          f"mass={m['mass_ratio']:.2f} refs={m['ref_jats']}/{m['ref_tei']})")
    for r in fid["reasons"]:
        print(f"  - {r}")
    for run in fid["missing_runs"]:
        print(f"  missing {run['shingles']:4d} shingles @tok{run['at_token']}: {run['snippet']}...")
    if args.json:
        print(json.dumps(fid, indent=1))
    return 0 if fid["verdict"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
