#!/usr/bin/env python3
"""Ingest one asset-complete harvested paper end to end: figures -> crosswalk -> gates.

Given a fetched work (fetched/{route}/{id}.xml + .pdf), this proves the WHOLE chain:
  1. extract figures from the fetched PDF (workstation pdf_preprocess) into assets/figN
  2. crosswalk the publisher JATS -> house JATS (lanec/crosswalk_generic.py), rewriting graphic
     hrefs onto the extracted assets and injecting the house id + ANZSRC
  3. run the workstation gates (validate_jats Tier1+2, jats_house_lint) — where the
     "every <fig> must resolve to a real image" rule VERIFIES the assets survived.

Reads nothing from and writes nothing into the workstation; output lands in ingested/{id}/.

Usage:
  python ingest_one.py W4406231937 --mid MORE-2025-901937 \
      --for 39:Education,3903:"Education systems",390303:"Higher education"
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

import ingest_log
import sidecar

HERE = os.path.dirname(os.path.abspath(__file__))
# The gates live in vendor/scripts/ in this snapshot (see vendor/SOURCE.md);
# in the full workspace this points at the AAM workstation sibling instead.
WS = os.path.join(HERE, "vendor")


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def openalex_authors(work_id):
    """Authoritative authorships from OpenAlex, for the Lane-B author fallback (used ONLY
    when GROBID recovered none). Returns [{surname, given, orcid, affs}]; [] on any error
    (the fallback simply doesn't fire — never fabricated). Metadata-only, keyless-capable.
    Goes through harvest_openalex.get so the org key travels as the Bearer header it
    requires — as an api_key query param the key is IGNORED and the call silently falls
    into the (budget-capped) keyless pool."""
    import harvest_openalex
    try:
        data = harvest_openalex.get(f"/works/{work_id}", select="authorships")
    except Exception:
        return []
    out = []
    for a in data.get("authorships", []):
        nm = ((a.get("author") or {}).get("display_name") or "").strip()
        if not nm:
            continue
        parts = nm.split()
        surname = parts[-1]
        given = " ".join(parts[:-1])
        orcid = (a.get("author") or {}).get("orcid") or ""
        affs = [s for s in (a.get("raw_affiliation_strings") or []) if s and s.strip()]
        if not affs:
            affs = [i.get("display_name") for i in (a.get("institutions") or [])
                    if i.get("display_name")]
        out.append({"surname": surname, "given": given, "orcid": orcid, "affs": affs})
    return out


def anzsrc_xml(triples):
    """triples: list of (code,label) from division -> group -> field (nested)."""
    from xml.sax.saxutils import escape
    def part(code, label):
        # escape & < > — an ANZSRC label like "Earth sciences & related" would otherwise
        # produce a malformed fragment that fails the crosswalk/gates.
        return (f'<compound-subject>'
                f'<compound-subject-part content-type="code">{escape(str(code))}</compound-subject-part>'
                f'<compound-subject-part content-type="text">{escape(str(label))}</compound-subject-part>'
                f'</compound-subject>')
    inner = part(*triples[2])
    mid = part(*triples[1]) + f'<subj-group>{inner}</subj-group>'
    top = part(*triples[0]) + f'<subj-group>{mid}</subj-group>'
    return ('<article-categories xmlns:mml="http://www.w3.org/1998/Math/MathML">'
            '<subj-group subj-group-type="heading"><subject>Research Article</subject></subj-group>'
            f'<subj-group subj-group-type="anzsrc-for">{top}</subj-group>'
            '</article-categories>')


_CC_URL = re.compile(r"(?:https?://)?creativecommons\.org/licenses/([a-z-]+)/([0-9.]+)", re.I)
_CC_PROSE = re.compile(
    r"Creative Commons Attribution\s*([-A-Za-z ]*?)\s*(\d\.\d)?\s*"
    r"(?:Unported|International|Generic)?\s*Licen[cs]e", re.I)


def cc_license_from_pdf(pdf_path):
    """Extract the Creative Commons licence the PUBLISHER printed in the VoR PDF.

    The licence cannot come from the GROBID TEI (<licence> is empty), so we take it from
    the source the publisher stamped on the page — as elsevier_to_jats greps the source
    XML. Returns (url, prose): a canonical CC URL when we can determine flavour+version
    (from a printed URL, or from prose that STATES the version, e.g. RSC 'Attribution 3.0
    Unported Licence' -> by/3.0), else the prose statement when the version is unstated
    (e.g. Wiley 'Creative Commons Attribution License'), which licence_verdict accepts via
    its prose path. We never fabricate a version: no version stated -> no URL, prose only.
    Both None -> the licence gate fails closed and the paper escalates to attended QA."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return (None, None)
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return (None, None)
    pages = sorted(set(list(range(min(3, doc.page_count))) + [doc.page_count - 1]))
    url = prose = None
    for i in pages:
        raw = doc[i].get_text()
        # (1) a printed URL — squash whitespace first (URLs wrap across lines in PDFs)
        m = _CC_URL.search(re.sub(r"\s+", "", raw))
        if m:
            url = f"https://creativecommons.org/licenses/{m.group(1).lower()}/{m.group(2)}/"
            break
        # (1b) a LINK ANNOTATION targeting a CC licence URL. Wiley prints the licence as
        # unversioned prose but HYPERLINKS the words — the versioned URI lives in the
        # annotation, not the text. The publisher put it in the PDF, so it is the same
        # class of evidence as a printed URL (proven on the 2026-07-14 TEI pilot: all
        # five Wiley pairs carried by/4.0 this way).
        for lk in doc[i].get_links():
            lm = _CC_URL.search(lk.get("uri") or "")
            if lm:
                url = f"https://creativecommons.org/licenses/{lm.group(1).lower()}/{lm.group(2)}/"
                break
        if url:
            break
        # (2) prose statement
        pm = _CC_PROSE.search(re.sub(r"\s+", " ", raw))
        if pm and prose is None:
            extra = pm.group(1).lower().replace(" ", "").replace("-", "")
            flav = "by"
            if "noncommercial" in extra:
                flav += "-nc"
            if "noderiv" in extra:
                flav += "-nd"
            if "sharealike" in extra:
                flav += "-sa"
            if pm.group(2):                       # version stated -> canonical URL
                url = f"https://creativecommons.org/licenses/{flav}/{pm.group(2)}/"
                break
            prose = pm.group(0)                   # no version -> keep prose, keep scanning for a URL
    doc.close()
    return (url, prose)


# licence_verdict moved to gates_run.py (2026-07-18) so ingest-time and
# regate-time verdicts share ONE implementation; re-exported for compatibility.
from gates_run import licence_verdict, run_gates  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_id")
    ap.add_argument("--mid", required=True)
    ap.add_argument("--for", dest="forc", required=True,
                    help="code:label,code:label,code:label (division,group,field)")
    args = ap.parse_args()

    src = glob.glob(os.path.join(HERE, "fetched", "*", args.work_id + ".xml"))
    if not src:
        sys.exit(f"no fetched XML for {args.work_id}")
    src_xml = src[0]
    src_pdf = src_xml[:-4] + ".pdf"       # optional: only the PDF-extraction fallback needs it
    # the route is the fetched/<route>/ dir of the ORIGINAL source — capture it now,
    # before a pre-transform (Elsevier, TEI) reassigns src_xml into the build dir
    route = os.path.basename(os.path.dirname(src_xml))

    # Build into a fresh .partial dir and promote it only once the whole chain succeeds, so a
    # re-run that fails midway leaves the EXISTING good package intact (the old code rmtree'd
    # it first, then could sys.exit on a crosswalk error — leaving a broken dir while the log
    # still said 'ingested').
    final = os.path.join(HERE, "ingested", args.work_id)
    out = final + ".partial"
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "assets"))

    # Some sources aren't house-JATS and need a pre-transform to generic JATS first; then
    # the rest of the chain (figures -> crosswalk -> gates) is identical.
    tei_src = None            # set by the TEI branch; enables the fidelity gate [2e]
    tei_publisher = None
    head = open(src_xml, "rb").read(600)
    if b"//ES//DTD" in head:
        # Elsevier (ce:/ja: DTD) isn't JATS.
        print("[0/3] Elsevier XML -> JATS (elsevier_to_jats) ...")
        interm = os.path.join(out, "elsevier.jats.xml")
        r = sh(sys.executable, os.path.join(HERE, "lanec", "elsevier_to_jats.py"), src_xml, "-o", interm)
        if os.path.isfile(interm):
            src_xml = interm
        else:
            print("      " + r.stderr.strip()[:200])
    elif b"tei-c.org/ns/1.0" in head:
        # Lane B (convert_vor): the source is a GROBID TEI, not publisher XML — cross it
        # into generic JATS via tei_to_jats. Journal + publisher come from the work-tracker
        # DB (authoritative; GROBID doesn't recover them); licence from the PDF the
        # publisher printed (never the TEI, never fabricated — see cc_license_from_pdf).
        print("[0/3] GROBID TEI -> JATS (tei_to_jats) ...")
        import duckdb
        con = duckdb.connect(os.path.join(HERE, f"works_{ingest_log.year_for(args.work_id)}.duckdb"), read_only=True)
        row = con.execute("SELECT publisher, journal, title FROM works WHERE id=?", [args.work_id]).fetchone()
        con.close()
        tei_publisher, tei_journal, tei_title = row if row else (None, None, None)
        lic_url, lic_prose = cc_license_from_pdf(src_pdf) if os.path.isfile(src_pdf) else (None, None)
        lic = lic_url or lic_prose
        print(f"      publisher={tei_publisher!r} journal={tei_journal!r} "
              f"licence={lic_url or (repr(lic_prose) if lic_prose else 'NONE (gate will block)')}")
        # authoritative authorships, for the fallback when GROBID's header parse recovered
        # none (a whole class of Lane-B FAILs — 'no <contrib>' — where the body is fine).
        # tei_to_jats uses TEI authors first and only falls back on total recovery failure.
        import json as _json
        oa_authors = openalex_authors(args.work_id)
        interm = os.path.join(out, "grobid.jats.xml")
        cmd = [sys.executable, os.path.join(HERE, "lanec", "tei_to_jats.py"), src_xml, "-o", interm,
               "--journal", tei_journal or "", "--license", lic or "", "--publisher", tei_publisher or "",
               "--title", tei_title or ""]
        if oa_authors:
            cmd += ["--authors", _json.dumps(oa_authors, ensure_ascii=False)]
        r = sh(*cmd)
        if os.path.isfile(interm):
            tei_src = src_xml
            src_xml = interm
        else:
            print("      " + r.stderr.strip()[:200])

    print("[1/3] acquiring figures ...")
    # (a) publisher figure files first — exact, publisher-quality, no order-guessing
    import duckdb
    con = duckdb.connect(os.path.join(HERE, f"works_{ingest_log.year_for(args.work_id)}.duckdb"), read_only=True)
    r0 = con.execute("SELECT doi, pmcid, journal, lane, asset_route, route "
                     "FROM works WHERE id=?", [args.work_id]).fetchone()
    con.close()
    doi, pmcid, journal, lane, asset_route, db_route = r0 if r0 else (None,) * 6
    from fetch_figures import get_publisher_figures
    npub, note = get_publisher_figures(src_xml, route, {"doi": doi, "pmcid": pmcid},
                                       os.path.join(out, "assets"))
    print(f"      publisher figures: {note}")
    # (b) fall back to PDF extraction only for the figures the publisher route didn't supply
    n_fallback = 0
    _pdf_preprocess = os.path.join(WS, "scripts", "pdf_preprocess.py")
    if npub == 0 and os.path.isfile(src_pdf) and os.path.isfile(_pdf_preprocess):
        bundle = os.path.join(out, "bundle")
        sh(sys.executable, _pdf_preprocess, src_pdf, "-o", bundle)
        figs = sorted(glob.glob(os.path.join(bundle, "assets", "fig[0-9]*.*")))
        for f in figs:
            shutil.copy2(f, os.path.join(out, "assets", os.path.basename(f)))
        n_fallback = len(figs)
        print(f"      PDF-extraction fallback: {len(figs)} figure file(s)")
    elif npub == 0:
        print("      no publisher figures and no PDF fallback available "
              "(pdf_preprocess is not vendored in this snapshot) -> partial")
    asset_source = "publisher" if npub > 0 else ("pdf_extract" if n_fallback else "none")

    print("[2/3] crosswalking publisher JATS -> house JATS ...")
    triples = [(c.split(":", 1)[0], c.split(":", 1)[1].strip('"'))
               for c in _split_for(args.forc)]
    anz = os.path.join(out, "anzsrc.xml")
    open(anz, "w", encoding="utf-8").write(anzsrc_xml(triples))
    r = sh(sys.executable, os.path.join(HERE, "lanec", "crosswalk_generic.py"),
           src_xml, "-o", out, "--mid", args.mid, "--anzsrc", anz)
    print("      " + (r.stdout.strip() or r.stderr.strip()[:200]))
    if not os.path.isfile(os.path.join(out, "article.xml")):
        sys.exit("crosswalk did not produce article.xml:\n" + r.stderr)

    # repo_pdf sources are LaTeX-derived: (1) figures arrive as caption-only <fig-group>s with
    # no <graphic> — the crosswalk only rewrites existing hrefs, so wire the PDF-recovered
    # images in; (2) caption prose still carries raw LaTeX ($\gamma\gamma$, \SI, custom macros)
    # — normalise it to readable Unicode. Both run before gating. Both are no-ops on clean JATS.
    if asset_source == "pdf_extract":
        ax_path = os.path.join(out, "article.xml")
        import repair_repo_pdf_figs
        n_wired = repair_repo_pdf_figs.repair_tree_file(ax_path, out)
        if n_wired:
            print(f"[2b] wired {n_wired} PDF-recovered figure(s) into article.xml")
        import latex_caption_clean
        n_caps, _ = latex_caption_clean.clean_captions_in_file(ax_path)
        if n_caps:
            print(f"[2c] normalised LaTeX in {n_caps} caption(s)")

    # (2d) BODY LaTeX -> proper JATS (scoap3_jhep and any route whose source embeds the
    # author's LaTeX in prose): \cite -> linked <xref>, $math$ -> <inline/disp-formula>
    # <tex-math> for MathJax. Detect-and-convert: a no-op on clean JATS, so it is safe to
    # run for every route. Residual raw LaTeX (an incomplete conversion) escalates below.
    ax_path = os.path.join(out, "article.xml")
    _raw = open(ax_path, encoding="utf-8").read()
    body_residual = 0
    if "\\cite" in _raw or re.search(r"(?<!\\)\$", _raw):
        from lanec import latex_body_clean
        n_cite, n_form, body_residual = latex_body_clean.convert_file(ax_path)
        if n_cite or n_form:
            print(f"[2d] body LaTeX -> {n_cite} linked citation(s), {n_form} formula(e)"
                  f"{f'; {body_residual} raw marker(s) LEFT' if body_residual else ''}")

    # (2e) fidelity gate (Lane B): the package was built from ONE extractor's silent
    # reading (GROBID). Compare it against an independent reading of the same PDF —
    # ref parity, grounding, completeness, body mass (lanec/pdf_fidelity.py; thresholds
    # calibrated on the pilot corpus, never guessed). FAIL never ships as clean; FLAG
    # ships (real gate-green content) but carries the evidence for a human look.
    fidelity = None
    if tei_src and os.path.isfile(src_pdf):
        from lanec import pdf_fidelity, publisher_rules
        _floor = publisher_rules.for_publisher(tei_publisher).fidelity_floor
        fidelity = pdf_fidelity.check(ax_path, src_pdf, tei_path=tei_src, pass_floor=_floor)
        fm = fidelity["metrics"]
        print(f"[2e] fidelity: {fidelity['verdict'].upper()} "
              f"(completeness={fm['completeness']:.2f} grounding={fm['grounding']:.2f} "
              f"mass={fm['mass_ratio']:.2f} refs={fm['ref_jats']}/{fm['ref_tei']})")
        for _r in fidelity["reasons"]:
            print(f"      - {_r}")
    elif tei_src:
        fidelity = {"verdict": "skipped", "reasons": ["no source PDF on disk"],
                    "metrics": {}, "missing_runs": []}
        print("[2e] fidelity: SKIPPED (no source PDF on disk) — recorded, never a silent green")

    print("[3/3] running gates ...")
    # the three package-level gates + their engine fingerprints, via the shared
    # runner (gates_run.py) — the same code regate.py sweeps with
    g = run_gates(os.path.join(out, "article.xml"))
    print("      validate: " + g["validate_line"])
    print("      house-lint: " + g["lint_line"])
    for e in g["error_lines"][:8]:
        print("         " + e.strip())
    lic_ok, lic_uri = g["licence_pass"], g["licence_uri"]
    print(f"      licence: {'PASS' if lic_ok else 'FAIL'} ({g['licence_detail']})")

    # ---- sidecar: the durable intra-article record of what this run produced ----
    vpass = g["validate_pass"]
    lintpass = g["lint_pass"]
    errc = g["errors"]
    warnc = g["warnings"]
    # the raw-LaTeX guard the gates can't see: residual \cite/$ in prose means the body
    # conversion was incomplete — never let that ship as clean (it would render as source).
    if body_residual:
        lintpass = False
        errc += body_residual
        print(f"      raw-LaTeX guard: {body_residual} unconverted marker(s) in body -> not clean")
    # the fidelity gate the structural gates can't see: the package must survive an
    # independent reading of its own PDF (Lane B only; see [2e] above).
    if fidelity and fidelity["verdict"] == "fail":
        lintpass = False
        errc += 1
        print(f"      fidelity gate: FAIL ({'; '.join(fidelity['reasons'])}) -> not clean")
    elif fidelity and fidelity["verdict"] == "flag":
        warnc += 1
        print(f"      fidelity gate: FLAG ({'; '.join(fidelity['reasons'])}) -> needs a look")
    raw = open(os.path.join(out, "article.xml"), encoding="utf-8").read()
    tm = re.search(r"<article-title[^>]*>(.*?)</article-title>", raw, re.S)
    title = re.sub(r"<[^>]+>", "", tm.group(1)).strip()[:300] if tm else None
    # Flattening a title that carries <tex-math> includes its LaTeX verbatim ($W$,
    # $\sqrt{s}$). The sidecar title feeds every plain-text surface (tab titles,
    # listings, search), so normalise it to readable Unicode. The JATS keeps the
    # proper inline-formula markup untouched.
    if title and ("\\" in title or "$" in title):
        import latex_caption_clean
        title = latex_caption_clean.clean_text(title)
    levels = ["division", "group", "field"]
    anz = [{"level": levels[i], "code": c, "label": l} for i, (c, l) in enumerate(triples)]
    provisional = len(triples) > 1 and triples[1][0].endswith("99")
    sc = sidecar.write(out, work_id=args.work_id, mid=args.mid, doi=doi, journal=journal,
                       title=title, route=db_route or route, lane=lane, asset_route=asset_route,
                       anzsrc=anz, provisional_anzsrc=provisional,
                       validate_pass=vpass, lint_pass=lintpass, err_count=errc, warn_count=warnc,
                       asset_source=asset_source, provenance=f"registry+{db_route or route}",
                       licence_pass=lic_ok, licence_uri=lic_uri, fidelity=fidelity,
                       gate_engine=g["engine"], gate_checked_at=g["checked_at"])
    # Promote the completed .partial over any existing package (atomic-ish rename). Only now,
    # with a full package written, does the old one get replaced — so a mid-chain failure above
    # never destroys a good package.
    if os.path.isdir(final):
        shutil.rmtree(final)
    os.replace(out, final)
    ingest_log.index_sidecar(args.work_id, os.path.join(final, sidecar.NAME))
    print(f"      sidecar: {sc['assets']['count']} asset(s), err={errc} warn={warnc} -> {sidecar.NAME}")
    print(f"\ndone -> {final}")


def _split_for(s):
    out, buf, q = [], "", False
    for ch in s:
        if ch == '"':
            q = not q
        if ch == "," and not q:
            out.append(buf); buf = ""
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


if __name__ == "__main__":
    main()
