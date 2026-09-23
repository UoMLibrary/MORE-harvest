#!/usr/bin/env python3
"""The package-level gates — runnable AND fingerprinted, in one place.

Three gates judge a finished package's article.xml:
  validate — the workstation's validate_jats.py (Tier 1+2), by subprocess
  lint     — the workstation's jats_house_lint.py, by subprocess
  licence  — licence_verdict() below (the packaged document must declare CC-BY)

Both callers run them through run_gates() so ingest-time and regate-time
verdicts can never drift apart:
  ingest_one.py [3/3]  — at build time
  regate.py            — the standing re-lint sweep over ingested/

WHY FINGERPRINTS, NOT VERSION NUMBERS. Transform steps are hand-versioned in
pipeline_versions.py under a bump-in-the-same-commit discipline — possible
because they live in this repo. The validate/lint gates live in the
WORKSTATION's repo (we call them cross-sibling, sanctioned use #1), so no
same-commit discipline can reach them from here. Instead the gate engines are
identified by content hash, computed at run time from the gate implementations
themselves: a sidecar whose recorded `gates.engine` differs from today's
fingerprints was judged by a DIFFERENT standard than today's — stale by
definition, no human bookkeeping involved. (This is the fix for the
2026-07-14 "stale green" class: 146/150 pmc packages carried passing verdicts
that the hardened gates of that day would have failed.)
"""
import hashlib
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# The gates live in vendor/scripts/ in this snapshot (see vendor/SOURCE.md);
# in the full workspace this points at the AAM workstation sibling instead.
WS = os.path.join(HERE, "vendor")
VALIDATE = os.path.join(WS, "scripts", "validate_jats.py")
LINT = os.path.join(WS, "scripts", "jats_house_lint.py")
# The Lane-B fidelity gate's engine = the checker + the publisher floors it
# reads its thresholds from. Fingerprinted together: a floor change re-judges
# a package exactly as a checker change does.
FIDELITY = os.path.join(HERE, "lanec", "pdf_fidelity.py")
FIDELITY_RULES = os.path.join(HERE, "lanec", "publisher_rules.py")


def _sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def licence_verdict(article_xml_path):
    """Verify the produced house JATS actually declares a CC-BY licence.

    Policy: only CC-BY VoR content may be ingested. The OpenAlex route filter checks the
    licence of a *possibly different* copy's metadata; THIS checks the document we actually
    packaged. Fails closed — a missing Creative Commons licence, or any non-'by' flavour
    (nc / nd / sa), is NOT acceptable. Returns (ok: bool, uri: str|None, detail: str)."""
    try:
        raw = open(article_xml_path, encoding="utf-8").read()
    except OSError as e:
        return (False, None, f"unreadable article.xml: {e}")
    # 1) A canonical creativecommons.org URI is the strongest signal — trust its exact
    #    flavour. Scope the search to <permissions> FIRST: a CC URL merely CITED elsewhere
    #    (a data statement pointing at a CC-NC dataset, a licence discussed in the text)
    #    must never decide the ARTICLE's flavour. Whole-document is the fallback only
    #    when the permissions block carries no canonical URI.
    CC_URI = r"https?://creativecommons\.org/licenses/([a-z-]+)/([0-9.]+)"
    perm_scope = re.search(r"<permissions>.*?</permissions>", raw, re.S)
    m = (re.search(CC_URI, perm_scope.group(0), re.I) if perm_scope else None) \
        or re.search(CC_URI, raw, re.I)
    if m:
        flavour, uri = m.group(1).lower(), m.group(0)
        if flavour != "by":
            return (False, uri, f"CC-{flavour.upper()} is not CC-BY")
        return (True, uri, "CC-BY (uri)")
    # 2) No canonical URI (some publishers state the licence only in prose, e.g. Karger): fall
    #    back to the <permissions> text. Accept an explicit CC-BY statement ONLY when no
    #    restrictive term (NonCommercial / NoDerivatives / ShareAlike) is present — fail closed
    #    on anything ambiguous, so a restricted licence can never be read as CC-BY.
    perm = re.search(r"<permissions>.*?</permissions>", raw, re.S)
    blob = (perm.group(0) if perm else "").lower()
    if not blob:
        return (False, None, "no licence in article.xml")
    restrictive = re.search(r"non-?commercial|no-?derivati|share-?alike|by-nc|by-nd|by-sa", blob)
    if restrictive:
        return (False, None, "restrictive Creative Commons terms (not CC-BY)")
    if re.search(r"creative commons attribution|cc[\s\-]?by\b", blob):
        return (True, None, "CC-BY (prose)")
    return (False, None, "no recognisable CC-BY licence")


def _file_hash(*paths):
    h = hashlib.sha256()
    for path in paths:
        try:
            h.update(open(path, "rb").read())
        except OSError:
            return "missing"
    return h.hexdigest()[:16]


def _licence_source_hash():
    """Hash of licence_verdict's own source segment — so editing anything ELSE in
    this file does not falsely mark every sidecar's licence verdict stale."""
    import ast
    try:
        src = open(__file__, encoding="utf-8").read()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == "licence_verdict":
                seg = ast.get_source_segment(src, node) or ""
                return hashlib.sha256(seg.encode("utf-8")).hexdigest()[:16]
    except Exception:
        pass
    return "unknown"


def gate_fingerprints():
    """The identity of TODAY's gate engines: {gate: content-hash16}.

    `fidelity` identifies the Lane-B fidelity engine (checker + publisher
    floors); it is stamped into a sidecar ONLY when the package actually
    carries a fidelity verdict (sidecar.py / regate.py filter it)."""
    return {
        "validate": _file_hash(VALIDATE),
        "lint": _file_hash(LINT),
        "licence": _licence_source_hash(),
        "fidelity": _file_hash(FIDELITY, FIDELITY_RULES),
    }


def stale_gates(sc):
    """Which of this sidecar's gate verdicts were issued by a different engine
    than today's? Returns {gate: (recorded, current)} — the whole set when the
    package pre-dates gate stamping (recorded 'unstamped'), mirroring
    pipeline_versions.stale_steps' treatment of pre-stamping packages.
    `fidelity` is judged only for packages that carry a fidelity verdict —
    a Lane-C package can never be stale on a gate that does not apply to it."""
    recorded = ((sc or {}).get("gates") or {}).get("engine") or {}
    out = {}
    for gate, cur in gate_fingerprints().items():
        if gate == "fidelity" and not (sc or {}).get("fidelity"):
            continue
        rec = recorded.get(gate, "unstamped")
        if rec != cur:
            out[gate] = (rec, cur)
    return out


def run_gates(article_xml_path):
    """Run all three package-level gates on a finished article.xml.

    Returns the parsed verdicts plus the raw display lines the ingest console
    prints, and the engine fingerprints of the gates that just ran:
      {validate_pass, validate_line, lint_pass, lint_line, errors, warnings,
       error_lines, licence_pass, licence_uri, licence_detail,
       engine: {...}, checked_at}
    Parsing is verbatim from the original ingest_one [3/3] block — this module
    exists so that block and regate.py share ONE implementation."""
    v = _sh(sys.executable, VALIDATE, article_xml_path)
    vlast = (v.stdout.strip().splitlines() or ["?"])[-1]
    hl = _sh(sys.executable, LINT, article_xml_path)
    line = [l for l in hl.stdout.splitlines() if l.startswith("Result")]
    errs = [l for l in hl.stdout.splitlines() if "ERROR" in l]
    ec = re.search(r"\((\d+)\s+error", hl.stdout)
    wc = re.search(r"(\d+)\s+warning", hl.stdout)
    lic_ok, lic_uri, lic_detail = licence_verdict(article_xml_path)
    return {
        "validate_pass": "PASS" in vlast and "FAIL" not in vlast,
        "validate_line": vlast,
        "lint_pass": bool(line) and "Result: PASS" in line[0],
        "lint_line": line[0] if line else hl.stdout.strip()[:120],
        "errors": int(ec.group(1)) if ec else len(errs),
        "warnings": int(wc.group(1)) if wc else 0,
        "error_lines": errs,
        "licence_pass": lic_ok,
        "licence_uri": lic_uri,
        "licence_detail": lic_detail,
        "engine": gate_fingerprints(),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
