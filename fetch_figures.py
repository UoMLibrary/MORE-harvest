#!/usr/bin/env python3
"""Publisher-figure fetcher — get the publisher's ACTUAL figure image files.

Better than cropping figures out of the PDF: the publisher's own renditions are higher
quality and (crucially) match the XML's <graphic> references by filename, so there is no
figure-order guessing and no vector/flowchart extraction failures.

get_publisher_figures(xml_path, route, ids, out_assets) reads the XML's <fig>/<graphic>
references in document order, fetches the matching publisher image for each, and writes it
as out_assets/fig{i}.{ext} (the slot the crosswalk expects). Returns (n_written, note).
Returns (0, reason) when the route has no publisher-figure source — the caller then falls
back to PDF extraction.

Route adapters:
  pmc    Europe PMC supplementaryFiles zip — contains the figure binaries named exactly as
         the XML references them (works over HTTPS; no FTP wall). THE big one (~1,700 papers).
  plos   per-figure image endpoint (predictable from the DOI).
  (frontiers / others: no clean per-figure URL found -> fall back to PDF extraction.)
"""
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from lxml import etree

UA = {"User-Agent": "MORE-harvest/0.1 (mailto:scott.taylor@manchester.ac.uk)"}


def _get(url, headers=None, timeout=120):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _image_hrefs(xml_path):
    """Every image referenced anywhere: <graphic> and <inline-graphic> (figures, tables
    rendered as images, inline-math images). Basenames, in document order, de-duplicated."""
    parser = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)
    raw = re.sub(rb"<!DOCTYPE.*?>", b"", open(xml_path, "rb").read(), count=1, flags=re.S)
    root = etree.fromstring(raw, parser)
    out, seen = [], set()
    for g in root.iter():
        if not isinstance(g.tag, str) or g.tag.rsplit("}", 1)[-1] not in ("graphic", "inline-graphic"):
            continue
        for k, v in g.attrib.items():
            if k.rsplit("}", 1)[-1] == "href":
                b = os.path.basename(v)
                if b and b not in seen:
                    seen.add(b); out.append(b)
    return out


def _supp_hrefs(xml_path):
    """Every LOCAL (schemeless) file referenced by <media>/<supplementary-material>/
    <inline-supplementary-material>: the supplementary binaries (ESM PDFs, spreadsheets,
    videos). The 2026-07-13 gate hardening fails any local href that doesn't ship in the
    package, and the same PMC zip that carries the figures carries these — capture them too.
    Basenames, in document order, de-duplicated."""
    parser = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)
    raw = re.sub(rb"<!DOCTYPE.*?>", b"", open(xml_path, "rb").read(), count=1, flags=re.S)
    root = etree.fromstring(raw, parser)
    out, seen = [], set()
    for el in root.iter():
        if not isinstance(el.tag, str) or el.tag.rsplit("}", 1)[-1] not in (
                "media", "supplementary-material", "inline-supplementary-material"):
            continue
        for k, v in el.attrib.items():
            if k.rsplit("}", 1)[-1] != "href":
                continue
            h = (v or "").strip()
            if not h or h.startswith("#") or ":" in h.split("/")[0] \
                    or h.lower().startswith(("www.", "ftp.")):
                continue                 # external / scheme'd — not a package file
            b = os.path.basename(h)
            if b and b not in seen:
                seen.add(b); out.append(b)
    return out


def _pmc(xml_path, pmcid, out_assets):
    if not pmcid:
        return 0, "no pmcid"
    try:
        data = _get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles")
    except Exception as e:
        return 0, f"supplementaryFiles fetch failed: {str(e)[:50]}"
    if data[:2] != b"PK":
        return 0, "supplementaryFiles is not a zip (none available)"
    z = zipfile.ZipFile(io.BytesIO(data))
    names = {os.path.basename(n): n for n in z.namelist()}
    hrefs = _image_hrefs(xml_path)      # ALL images: figures, table-images, inline-math
    n = 0
    for href in hrefs:
        if href in names:
            with open(os.path.join(out_assets, href), "wb") as f:
                f.write(z.read(names[href]))
            n += 1
    # supplementary binaries referenced by <media>/<supplementary-material> ride the same
    # zip; capture them so the crosswalk can resolve their hrefs onto assets/. The return
    # count stays images-only — it drives the caller's PDF-extraction FIGURE fallback.
    supp = [h for h in _supp_hrefs(xml_path) if h not in set(hrefs)]
    ns = 0
    for href in supp:
        if href in names:
            with open(os.path.join(out_assets, href), "wb") as f:
                f.write(z.read(names[href]))
            ns += 1
    note = f"europepmc supplementaryFiles ({n}/{len(hrefs)} images"
    if supp:
        note += f", {ns}/{len(supp)} supplementary files"
    return n, note + " matched by filename)"


def _plos(xml_path, doi, out_assets):
    if not doi or not doi.startswith("10.1371/"):
        return 0, "not a PLOS doi"
    hrefs = _image_hrefs(xml_path)
    n = 0
    for i, href in enumerate(hrefs, 1):
        # PLOS figure id is the graphic href stem (…g001); image endpoint keys on doi.gNNN
        m = re.search(r"\.(g\d+)", href or "")
        if not m:
            continue
        url = (f"https://journals.plos.org/plosone/article/figure/image?"
               f"id={doi}.{m.group(1)}&size=large")
        try:
            data = _get(url, timeout=120)
            if data[:3] in (b"\xff\xd8\xff", b"\x89PN"):
                with open(os.path.join(out_assets, f"fig{i}.jpg"), "wb") as f:
                    f.write(data)
                n += 1
        except Exception:
            pass
    return n, f"plos figure endpoint ({n}/{len(hrefs)})"


def _n_figs(xml_path):
    raw = re.sub(rb"<!DOCTYPE.*?>", b"", open(xml_path, "rb").read(), count=1, flags=re.S)
    root = etree.fromstring(raw, etree.XMLParser(recover=True, no_network=True))
    return sum(1 for e in root.iter() if isinstance(e.tag, str) and e.tag.rsplit("}", 1)[-1] == "fig")


def _arxiv(xml_path, arxiv_id, out_assets):
    """Physics figures from the arXiv LaTeX source tarball. CONSERVATIVE: arXiv carries the
    AUTHOR's figure files (names differ from the published ones, sub-figures are separate, plus
    logos/format-dupes), so we only use them when the de-noised figure count EXACTLY matches the
    published <fig> count — otherwise the mapping is unsafe and we decline to the PDF fallback.
    EPS/PDF figures are rasterised to PNG via ghostscript."""
    import io
    import shutil
    import subprocess
    import tarfile
    import tempfile
    if not arxiv_id:
        return 0, "no arxiv id"
    gs = shutil.which("gs")
    try:
        raw = _get(f"https://arxiv.org/e-print/{arxiv_id}", timeout=120)
        tf = tarfile.open(fileobj=io.BytesIO(raw))
    except Exception as e:
        return 0, f"arxiv e-print fetch failed: {str(e)[:40]}"
    members = [m for m in tf.getmembers() if m.isfile()]
    IMG = re.compile(r"\.(eps|pdf|png|jpe?g)$", re.I)
    RANK = {"png": 0, "jpg": 1, "jpeg": 1, "pdf": 2, "eps": 3}
    by_stem = {}
    for m in members:
        b = os.path.basename(m.name)
        if not IMG.search(b) or "logo" in b.lower():
            continue
        stem, ext = os.path.splitext(b)[0], b.rsplit(".", 1)[-1].lower()
        if stem not in by_stem or RANK[ext] < RANK[by_stem[stem][1]]:
            by_stem[stem] = (m, ext)
    need = _n_figs(xml_path)
    if not by_stem or len(by_stem) != need:
        return 0, f"arxiv has {len(by_stem)} figure files != {need} published (subfigs/extras) — declined"
    # order by \includegraphics appearance where possible, else sorted stems
    tex = "".join((tf.extractfile(m).read().decode("utf-8", "replace"))
                  for m in members if m.name.endswith(".tex") and tf.extractfile(m))
    order = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
    order_stems = [os.path.splitext(os.path.basename(o))[0] for o in order]
    stems = [s for s in order_stems if s in by_stem] or sorted(by_stem)
    stems = list(dict.fromkeys(stems))
    if len(stems) != need:
        return 0, "arxiv figure order ambiguous — declined"
    n = 0
    with tempfile.TemporaryDirectory() as td:
        for i, stem in enumerate(stems, 1):
            m, ext = by_stem[stem]
            data = tf.extractfile(m).read()
            if ext in ("png", "jpg", "jpeg"):
                open(os.path.join(out_assets, f"fig{i}.{ext}"), "wb").write(data)
                n += 1
            elif gs:
                src = os.path.join(td, f"in{i}.{ext}")
                open(src, "wb").write(data)
                outp = os.path.join(out_assets, f"fig{i}.png")
                r = subprocess.run([gs, "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE",
                                    "-sDEVICE=png16m", "-r300", "-dEPSCrop", "-dFirstPage=1",
                                    "-dLastPage=1", f"-sOutputFile={outp}", src],
                                   capture_output=True)
                if os.path.isfile(outp) and os.path.getsize(outp) > 0:
                    n += 1
    return n, f"arxiv source {arxiv_id} ({n}/{need} figs, rasterised)"


def _scoap3_arxiv_id(doi):
    """Read the arXiv id from the SCOAP3 record (arxiv_eprints carries [doi, arxivid])."""
    import urllib.parse
    for cand in _scoap3_doi_variants(doi):
        try:
            r = json.loads(_get("https://repo.scoap3.org/api/records?" +
                                urllib.parse.urlencode({"doi": cand, "size": "2"})))
        except Exception:
            continue
        for rec in (r.get("hits", {}) or {}).get("hits", []):
            for ae in rec.get("metadata", {}).get("arxiv_eprints", []):
                for v in (ae.get("value") if isinstance(ae.get("value"), list) else [ae.get("value")]):
                    if v and re.match(r"\d{4}\.\d{4,5}$", v):
                        return v
    return None


def _scoap3_doi_variants(doi):
    yield doi
    m = re.match(r"(10\.1103)/([a-z]+)\.(.+)$", doi)
    aps = {"physrevlett": "PhysRevLett", "physrevd": "PhysRevD", "physrevc": "PhysRevC"}
    if m and m.group(2) in aps:
        yield f"{m.group(1)}/{aps[m.group(2)]}.{m.group(3)}"


def _discover_pmcid(doi):
    """Any-route fallback: a paper may be in PMC even when its route isn't 'pmc'
    (OpenAlex misses some PMC locations). idconv resolves the DOI to a PMCID if present."""
    if not doi:
        return None
    import json
    import urllib.parse
    u = ("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?" +
         urllib.parse.urlencode({"tool": "MORE", "email": "scott.taylor@manchester.ac.uk",
                                 "ids": doi, "format": "json"}))
    try:
        rec = json.loads(_get(u, timeout=40)).get("records", [{}])[0]
        return rec.get("pmcid")
    except Exception:
        return None


def get_publisher_figures(xml_path, route, ids, out_assets):
    """ids: dict with pmcid / doi. Returns (n_written, note)."""
    os.makedirs(out_assets, exist_ok=True)
    if route == "pmc":
        return _pmc(xml_path, ids.get("pmcid"), out_assets)
    if route in ("scoap3_aps", "scoap3_other"):
        arxiv = ids.get("arxiv") or _scoap3_arxiv_id(ids.get("doi"))
        n, note = _arxiv(xml_path, arxiv, out_assets)
        return (n, note) if n else (0, note)   # 0 -> ingest_one falls back to PDF extraction
    if (ids.get("doi") or "").startswith("10.1371/"):
        n, note = _plos(xml_path, ids.get("doi"), out_assets)
        if n:
            return n, note
    # any-route fallback: is it in PMC after all? (the PMC figure zip is the best source)
    pmcid = _discover_pmcid(ids.get("doi"))
    if pmcid:
        n, note = _pmc(xml_path, pmcid, out_assets)
        if n:
            return n, note + f" [discovered {pmcid}]"
    return 0, f"no publisher-figure source for route '{route}'"


def main():
    import argparse
    import duckdb
    ap = argparse.ArgumentParser()
    ap.add_argument("work_id")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    con = duckdb.connect(os.path.join(here, "works_2025.duckdb"), read_only=True)
    row = con.execute("SELECT doi, pmcid, route FROM works WHERE id=?", [args.work_id]).fetchone()
    if not row:
        sys.exit("work not in DB")
    doi, pmcid, route = row
    import glob
    xmls = glob.glob(os.path.join(here, "fetched", "*", args.work_id + ".xml"))
    if not xmls:
        sys.exit("no fetched XML")
    out = args.out or os.path.join(here, "fig_test", args.work_id)
    n, note = get_publisher_figures(xmls[0], route, {"doi": doi, "pmcid": pmcid}, out)
    print(f"{args.work_id} [{route}]: {n} figures -> {out}\n  {note}")


if __name__ == "__main__":
    main()
