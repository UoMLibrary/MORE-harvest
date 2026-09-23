#!/usr/bin/env python3
"""Repair pass for the repo_pdf asset route: wire recovered figures into article.xml.

WHY THIS EXISTS
    The scoap3_jhep (and any repo_pdf) route ingests a LaTeX-derived JATS whose figures
    arrive as caption-only <fig-group> blocks with NO <graphic> child. The actual images
    are recovered separately by the PDF-extraction fallback (pdf_preprocess -> bundle/
    figures.json + assets/figN.png) but crosswalk_generic.py's pass B only ever REWRITES
    the href of an *existing* <graphic> — it never CREATES a missing one. So the images sit
    on disk, unreferenced, and any HTML rendered from article.xml shows captions but no
    figures. The house gate misses it too: jats_house_lint only inspects <fig>, so a
    caption-only <fig-group> never trips the "no <graphic>" error.

WHAT IT DOES  (per package, idempotent)
    For each caption-only figure container (a <fig-group>, or a <fig> lacking a <graphic>),
    in document order, matched 1:1 against bundle/figures.json (fallback: sorted assets/
    figN.*):
      - retag  <fig-group> -> <fig>          (a single recovered image = one <fig>; valid JATS)
      - ensure @id            (Fig{N}, matching the ingested-corpus publisher-id style)
      - ensure <label>        (Figure {N}, from the figures.json caption prefix)
      - append <graphic xlink:href="assets/figN.png"/>   (the deposited image)
    Then re-runs the workstation gates (validate_jats + jats_house_lint) as proof, exactly
    like ingest_one.py step [3/3].

    Writes nothing into the workstation and touches only this package's own article.xml +
    metadata.json (harvest repairing its own output).

USAGE
    python repair_repo_pdf_figs.py W4400601332 [W4401306919 ...]   # named packages
    python repair_repo_pdf_figs.py --all                            # every repo_pdf pkg with orphans
    python repair_repo_pdf_figs.py --all --dry-run                  # report, change nothing
    python repair_repo_pdf_figs.py W4400601332 --no-gates           # skip re-validation
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys

from lxml import etree

# reuse the exact serialization contract crosswalk_generic.py writes, so a repaired
# file is byte-compatible with a freshly crosswalked one.
JATS = "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD with MathML3 v1.4 20241031//EN"
DTD = "https://jats.nlm.nih.gov/archiving/1.4/JATS-archivearticle1-4-mathml3.dtd"
XLINK = "http://www.w3.org/1999/xlink"

HERE = os.path.dirname(os.path.abspath(__file__))
# The gates live in vendor/scripts/ in this snapshot (see vendor/SOURCE.md);
# in the full workspace this points at the AAM workstation sibling instead.
WS = os.path.join(HERE, "vendor")
INGESTED = os.path.join(HERE, "ingested")


def ln(el):
    """local name of an element tag (namespace-agnostic)."""
    t = el.tag
    return t.rsplit("}", 1)[-1] if isinstance(t, str) else t


def _norm(s):
    """lowercase alphanumeric skeleton for cheap caption cross-checking."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def load_recovered(pkg):
    """Authoritative fig -> file mapping. Prefer bundle/figures.json (it carries the caption
    for a sanity cross-check); fall back to sorted assets/figN.* on disk."""
    fj = os.path.join(pkg, "bundle", "figures.json")
    if os.path.isfile(fj):
        try:
            data = json.load(open(fj, encoding="utf-8"))
            out = []
            for e in data:
                f = e.get("file") or ("assets/fig%s.png" % e.get("fig"))
                out.append({"file": f.replace("\\", "/"),
                            "caption": e.get("caption", ""),
                            "num": str(e.get("fig", len(out) + 1))})
            return out, "figures.json"
        except Exception as ex:  # noqa: BLE001 - corrupt json -> fall through to disk scan
            print("      figures.json unreadable (%s); scanning assets/" % ex)
    files = sorted(glob.glob(os.path.join(pkg, "assets", "fig[0-9]*.*")),
                   key=lambda p: int(re.search(r"fig(\d+)\.", os.path.basename(p)).group(1)))
    out = [{"file": "assets/" + os.path.basename(f), "caption": "",
            "num": re.search(r"fig(\d+)\.", os.path.basename(f)).group(1)} for f in files]
    return out, "assets-scan"


def caption_of(el):
    cap = el.find("{*}caption")
    return "".join(cap.itertext()) if cap is not None else ""


def _delatex(s):
    """Strip LaTeX math/markup so a source caption compares against a PDF-rendered one."""
    s = re.sub(r"\$[^$]*\$", " ", s)      # inline math: $H^\pm$
    s = re.sub(r"\\[a-zA-Z]+", " ", s)    # commands: \rightarrow
    s = re.sub(r"[{}\\^_]", " ", s)
    return s


def _aligned(xml_cap, rec_cap):
    """True unless the two captions look genuinely unrelated. Lenient by design: the real
    guarantee is figures.json order + exact count match; this only catches gross swaps."""
    a = _norm(_delatex(xml_cap))
    b = _norm(re.sub(r"^\s*(figure|fig\.?)\s*\d+\.?", "", _delatex(rec_cap), flags=re.I))
    if not a or not b:
        return True
    head = a[:80]
    return any(head[i:i + 8] in b for i in range(0, max(1, len(head) - 8)))


def _has_resource(el):
    """A figure is NOT orphaned if it (or a nested fig) already carries a real image or
    an embedded object — a <graphic>, <media> (e.g. a supplementary PDF), or <alternatives>."""
    return any(ln(d) in ("graphic", "inline-graphic", "media", "alternatives") for d in el.iter())


def find_orphans(root):
    """Leaf figure containers, in document order, that carry a caption but NO deposited
    image: a <fig-group> or <fig> with a <caption>, no image/media/alternatives descendant,
    and no child <fig> of its own (a genuine multi-fig group is left for its children)."""
    out = []
    for el in root.iter():
        if ln(el) not in ("fig-group", "fig"):
            continue
        if el.find("{*}caption") is None:
            continue
        if _has_resource(el):
            continue
        if any(ln(c) == "fig" for c in el):   # a group wrapping real <fig> children
            continue
        out.append(el)
    return out


def make_graphic(href):
    g = etree.Element("graphic")
    g.set("{%s}href" % XLINK, href)
    return g


def repair_tree(root, recovered, work_id):
    """Mutate the tree in place. Returns (n_wired, warnings[])."""
    warns = []
    orphans = find_orphans(root)
    if not orphans:
        return 0, warns
    if len(orphans) != len(recovered):
        warns.append("count mismatch: %d orphaned figure block(s) but %d recovered image(s) "
                     "-- pairing positionally up to the shorter list" % (len(orphans), len(recovered)))

    existing_ids = {el.get("id") for el in root.iter() if el.get("id")}
    n = 0
    for i, el in enumerate(orphans):
        if i >= len(recovered):
            warns.append("no recovered image for orphaned figure block #%d -- left unwired" % (i + 1))
            continue
        rec = recovered[i]
        num = rec["num"]
        href = rec["file"]
        if not os.path.isfile(os.path.join(os.path.dirname(work_id or "."), href)):
            # resolved against pkg dir by caller; here just record the intended href
            pass
        # cheap alignment sanity check against the recovered caption (soft; positional order
        # + exact count match is the real guarantee — this only catches a gross swap)
        if rec["caption"] and not _aligned(caption_of(el), rec["caption"]):
            warns.append("figure %s: caption looks unrelated to %s (verify the crop is the "
                         "right figure)" % (num, os.path.basename(href)))

        # 1. retag fig-group -> fig
        if ln(el) == "fig-group":
            el.tag = "fig"
        # 2. ensure @id (match the corpus's publisher-id style; house-lint only WARNs on form)
        if not el.get("id"):
            fid = "Fig%s" % num
            while fid in existing_ids:
                fid += "r"
            el.set("id", fid)
            existing_ids.add(fid)
        # 3. ensure <label> before <caption>
        if el.find("{*}label") is None:
            lab = etree.Element("label")
            lab.text = "Figure %s" % num
            el.insert(0, lab)
        # 4. append the deposited <graphic>
        el.append(make_graphic(href))
        n += 1
    return n, warns


def serialize(root, outp):
    etree.cleanup_namespaces(root)
    body = etree.tostring(root, encoding="unicode")
    doc = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<!DOCTYPE article PUBLIC "%s"\n         "%s">\n%s\n' % (JATS, DTD, body))
    with open(outp, "w", encoding="utf-8") as f:
        f.write(doc)


def repair_tree_file(article_path, pkg_dir):
    """Wire recovered figures into an on-disk article.xml in place, no gating (the caller
    gates). Returns the number of figures wired. For use as a pipeline step in ingest_one.py's
    repo_pdf / PDF-extraction branch."""
    parser = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.parse(article_path, parser).getroot()
    if not find_orphans(root):
        return 0
    recovered, _ = load_recovered(pkg_dir)
    n, warns = repair_tree(root, recovered, pkg_dir)
    for w in warns:
        print("      ! " + w)
    if n:
        serialize(root, article_path)
    return n


def run_gates(pkg):
    ax = os.path.join(pkg, "article.xml")

    def sh(*cmd):
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    v = sh(sys.executable, os.path.join(WS, "scripts", "validate_jats.py"), ax)
    vlast = (v.stdout.strip().splitlines() or ["?"])[-1]
    hl = sh(sys.executable, os.path.join(WS, "scripts", "jats_house_lint.py"), ax)
    line = [l for l in hl.stdout.splitlines() if l.startswith("Result")]
    ec = re.search(r"\((\d+)\s+error", hl.stdout)
    wc = re.search(r"(\d+)\s+warning", hl.stdout)
    vpass = "PASS" in vlast and "FAIL" not in vlast
    lintpass = bool(line) and "Result: PASS" in line[0]
    return {
        "validate": vlast, "validate_pass": vpass,
        "lint": (line[0] if line else hl.stdout.strip()[:120]), "lint_pass": lintpass,
        "errors": int(ec.group(1)) if ec else 0, "warnings": int(wc.group(1)) if wc else 0,
    }


def update_metadata(pkg, n_wired, gates):
    mp = os.path.join(pkg, "metadata.json")
    if not os.path.isfile(mp):
        return
    meta = json.load(open(mp, encoding="utf-8"))
    meta.setdefault("assets", {})["figures_wired_into_xml"] = n_wired
    meta["repair"] = {
        "tool": "repair_repo_pdf_figs",
        "figures_wired": n_wired,
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    if gates:
        meta.setdefault("gates", {}).update({
            "validate_pass": gates["validate_pass"], "lint_pass": gates["lint_pass"],
            "errors": gates["errors"], "warnings": gates["warnings"],
            "both_pass": gates["validate_pass"] and gates["lint_pass"],
        })
    # atomic write (temp + replace), like sidecar.py — a crash mid-write must not truncate the
    # sidecar that records what this run produced.
    tmp = mp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    os.replace(tmp, mp)


def repair_package(work_id, do_gates=True, dry_run=False):
    pkg = work_id if os.path.isdir(work_id) else os.path.join(INGESTED, work_id)
    wid = os.path.basename(pkg.rstrip("/\\"))
    ax = os.path.join(pkg, "article.xml")
    if not os.path.isfile(ax):
        print("[%s] no article.xml -- skipped" % wid)
        return False

    parser = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.parse(ax, parser).getroot()

    orphans = find_orphans(root)
    if not orphans:
        print("[%s] nothing to repair (no caption-only figure blocks)" % wid)
        return True

    recovered, src = load_recovered(pkg)
    # verify each intended image resolves on disk (case-exact-ish; the gate is the real check)
    missing = [r["file"] for r in recovered if not os.path.isfile(os.path.join(pkg, r["file"]))]
    if missing:
        print("[%s] WARNING recovered images not on disk: %s" % (wid, ", ".join(missing[:5])))

    n, warns = repair_tree(root, recovered, pkg)
    for w in warns:
        print("[%s]   ! %s" % (wid, w))

    if dry_run:
        print("[%s] DRY-RUN would wire %d figure(s) from %s" % (wid, n, src))
        return True

    serialize(root, ax)
    print("[%s] wired %d figure(s) into article.xml (source: %s)" % (wid, n, src))

    gates = None
    if do_gates:
        gates = run_gates(pkg)
        print("[%s]   validate: %s" % (wid, gates["validate"]))
        print("[%s]   house-lint: %s (errors=%d warnings=%d)"
              % (wid, gates["lint"], gates["errors"], gates["warnings"]))
        if not (gates["validate_pass"] and gates["lint_pass"]):
            print("[%s]   *** GATE FAILURE -- inspect before trusting this package ***" % wid)
    update_metadata(pkg, n, gates)
    return True


def discover_repo_pdf_orphans():
    """Every ingested repo_pdf package that still has caption-only figure blocks. Scoped
    strictly to asset_route == repo_pdf: only the LaTeX/PDF source route drops <graphic>s.
    Publisher-package routes with a graphic-less <fig> (e.g. one wrapping a supplementary
    <media>) are a different, legitimate shape and are left alone."""
    out = []
    for wid in sorted(os.listdir(INGESTED)):
        pkg = os.path.join(INGESTED, wid)
        ax = os.path.join(pkg, "article.xml")
        mp = os.path.join(pkg, "metadata.json")
        if not (os.path.isfile(ax) and os.path.isfile(mp)):
            continue
        try:
            if json.load(open(mp, encoding="utf-8")).get("route", {}).get("asset_route") != "repo_pdf":
                continue
        except Exception:  # noqa: BLE001
            continue
        parser = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)
        root = etree.parse(ax, parser).getroot()
        if find_orphans(root):
            out.append(wid)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_ids", nargs="*", help="package ids (or paths) to repair")
    ap.add_argument("--all", action="store_true", help="repair every ingested package with orphaned figures")
    ap.add_argument("--no-gates", action="store_true", help="skip validate_jats + jats_house_lint")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = ap.parse_args()

    ids = args.work_ids
    if args.all:
        ids = discover_repo_pdf_orphans()
        print("discovered %d package(s) with orphaned figures: %s\n" % (len(ids), ", ".join(ids) or "(none)"))
        if not ids:
            print("nothing to repair.")
            return
    if not ids:
        ap.error("give one or more work ids, or --all")

    ok = 0
    for wid in ids:
        if repair_package(wid, do_gates=not args.no_gates, dry_run=args.dry_run):
            ok += 1
        print()
    print("done: %d/%d package(s) processed" % (ok, len(ids)))


if __name__ == "__main__":
    main()
