#!/usr/bin/env python3
"""
validate_jats.py - Validate a MORE JATS XML file (or a package folder) before hand-off.

Two tiers of checking:

  Tier 1 - STRUCTURAL (always runs, no DTD or network needed)
    * XML well-formedness
    * duplicate @id values
    * cross-reference integrity: every @rid token points to a real @id
    * DOI format (article-id / pub-id with pub-id-type="doi")
    * required MORE/JATS skeleton present (article > front > article-meta, body, title)

  Tier 2 - DTD VALIDITY (runs only if the JATS 1.4 DTD is vendored locally)
    * xmllint --noout --nonet --dtdvalid <local DTD> against the JATS Archive DTD 1.4
    * To enable: drop the NLM "JATS Archiving and Interchange DTD with MathML3 v1.4"
      pack into scripts/dtd/ so that this file exists:
          scripts/dtd/JATS-archivearticle1-4-mathml3.dtd
      (vendor it once locally — see scripts/dtd/README.md; the in-house pipeline
       should re-run the same DTD validation on ingest.)

Usage:
  python validate_jats.py outputs/MORE-2026-000001/article.xml
  python validate_jats.py outputs/MORE-2026-000001          # a package folder (finds article.xml)
  python validate_jats.py --quiet outputs/.../article.xml    # summary line only

Exit code: 0 = pass, 1 = problems found, 2 = usage / file error.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DTD_PATH = os.path.join(HERE, "dtd", "JATS-archivearticle1-4-mathml3.dtd")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
# attributes whose values are space-separated IDREFS pointing at @id targets
RID_ATTRS = ("rid", "rids")


def find_xmllint():
    """Find xmllint on PATH, with common Windows MSYS2 fallbacks."""
    found = shutil.which("xmllint")
    if found:
        return found
    if os.name == "nt":
        for cand in (
            r"C:\msys64\ucrt64\bin\xmllint.exe",
            r"C:\msys64\mingw64\bin\xmllint.exe",
            r"C:\msys64\usr\bin\xmllint.exe",
        ):
            if os.path.isfile(cand):
                return cand
    return None


def _localname(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def resolve_xml(path):
    """Accept a file or a package folder; return the article.xml path."""
    if os.path.isdir(path):
        cand = os.path.join(path, "article.xml")
        if os.path.isfile(cand):
            return cand
        xmls = [f for f in os.listdir(path) if f.endswith(".xml")]
        if len(xmls) == 1:
            return os.path.join(path, xmls[0])
        raise FileNotFoundError(
            f"{path} is a folder without a clear article.xml ({len(xmls)} .xml files)"
        )
    return path


def tier1_structural(xml_path):
    """Return (errors, warnings) lists of human-readable strings."""
    errors, warnings = [], []

    # well-formedness + parse
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        return ([f"NOT well-formed XML: {e}"], warnings)
    root = tree.getroot()

    if _localname(root.tag) != "article":
        errors.append(f"root element is <{_localname(root.tag)}>, expected <article>")

    # collect ids and rids in one pass
    ids, dup_ids, rid_refs = set(), set(), []
    doi_values = []
    tags_seen = set()
    for el in root.iter():
        ln = _localname(el.tag)
        tags_seen.add(ln)
        _id = el.get("id")
        if _id is not None:
            if _id in ids:
                dup_ids.add(_id)
            ids.add(_id)
        for attr in RID_ATTRS:
            v = el.get(attr)
            if v:
                for tok in v.split():
                    rid_refs.append((tok, ln))
        if ln in ("article-id", "pub-id") and el.get("pub-id-type") == "doi":
            doi_values.append((el.text or "").strip())

    # duplicate ids
    for d in sorted(dup_ids):
        errors.append(f"duplicate @id value: '{d}'")

    # xref integrity
    missing = sorted({tok for tok, _ in rid_refs if tok not in ids})
    for tok in missing:
        errors.append(f"@rid points to unknown target id: '{tok}'")

    # doi format
    for doi in doi_values:
        if not DOI_RE.match(doi):
            errors.append(f"DOI not in expected 10.xxxx/... format: '{doi}'")
    if not doi_values:
        warnings.append("no DOI (article-id pub-id-type='doi') found")

    # required skeleton
    for required in ("front", "article-meta"):
        if required not in tags_seen:
            errors.append(f"missing required element <{required}>")
    if "body" not in tags_seen:
        warnings.append("no <body> element (acceptable only for metadata-only records)")
    # The real title lives in front/article-meta/title-group — an <article-title> inside a
    # reference <element-citation> must NOT satisfy the requirement (that would let a titleless
    # package pass just because it cites a titled work).
    has_real_title = False
    for am in (e for e in root.iter() if _localname(e.tag) == "article-meta"):
        for tg in (e for e in am.iter() if _localname(e.tag) == "title-group"):
            for at in (e for e in tg.iter() if _localname(e.tag) == "article-title"):
                if "".join(at.itertext()).strip():
                    has_real_title = True
    if not has_real_title:
        errors.append("missing non-empty <article-title> in front/article-meta/title-group")

    return errors, warnings


def tier2_dtd(xml_path):
    """Return (ran, ok, detail). ran=False if DTD not vendored or xmllint absent."""
    if not os.path.isfile(DTD_PATH):
        return (False, None, f"DTD not vendored at {os.path.relpath(DTD_PATH, HERE)} - skipped")
    xmllint = find_xmllint()
    if not xmllint:
        return (False, None, "xmllint not installed - skipped")
    # Validate against the LOCAL DTD only: strip the DOCTYPE to a temp copy so xmllint does not
    # also try to fetch the DOCTYPE's remote system URL (which --nonet would just warn about).
    import re as _re, tempfile
    raw = open(xml_path, encoding="utf-8").read()
    nodoc = _re.sub(r"<!DOCTYPE(?:[^>\[]|\[[^\]]*\])*>", "", raw, count=1, flags=_re.S)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
    try:
        tmp.write(nodoc); tmp.close()
        proc = subprocess.run(
            [xmllint, "--noout", "--nonet", "--dtdvalid", DTD_PATH, tmp.name],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        # rewrite temp path back to the real filename in any diagnostics
        detail = proc.stderr.replace(tmp.name, os.path.basename(xml_path)).strip()
        return (True, proc.returncode == 0, detail)
    finally:
        os.unlink(tmp.name)


def main():
    ap = argparse.ArgumentParser(description="Validate MORE JATS XML before hand-off.")
    ap.add_argument("target", help="article.xml file or a package folder")
    ap.add_argument("--quiet", action="store_true", help="print only the summary line")
    args = ap.parse_args()

    try:
        xml_path = resolve_xml(args.target)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if not os.path.isfile(xml_path):
        print(f"ERROR: no such file: {xml_path}", file=sys.stderr)
        return 2

    t1_errors, warnings = tier1_structural(xml_path)
    dtd_ran, dtd_ok, dtd_detail = tier2_dtd(xml_path)
    errors = list(t1_errors)
    if dtd_ran and not dtd_ok:
        errors.append("DTD validation failed (see detail below)")

    passed = not errors

    if not args.quiet:
        print(f"\nValidating: {xml_path}")
        print("-" * 60)
        print(f"Tier 1 structural : {'PASS' if not t1_errors else 'FAIL'} "
              f"({len(t1_errors)} error(s), {len(warnings)} warning(s))")
        if dtd_ran:
            print(f"Tier 2 DTD 1.4    : {'PASS' if dtd_ok else 'FAIL'}")
        else:
            print(f"Tier 2 DTD 1.4    : SKIPPED - {dtd_detail}")
        for e in errors:
            print(f"  ERROR    {e}")
        for w in warnings:
            print(f"  warning  {w}")
        if dtd_ran and not dtd_ok and dtd_detail:
            print("  --- xmllint DTD output (first 15 lines) ---")
            for line in dtd_detail.splitlines()[:15]:
                print(f"    {line}")
        print("-" * 60)

    print(f"{'PASS' if passed else 'FAIL'}: {xml_path}"
          + (f" [DTD {'pass' if dtd_ok else 'fail'}]" if dtd_ran else " [DTD skipped]"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
