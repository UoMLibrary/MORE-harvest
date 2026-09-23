#!/usr/bin/env python3
"""Generic publisher-JATS -> MORE house-JATS crosswalk.

Supersedes crosswalk_aps.py: handles APS (JATS Publishing + OASIS tables) AND the older
NLM-2.x flavour that PMC / Frontiers / many native OA publishers still emit. Given any
publisher JATS, produces a house-profile article.xml that validates against JATS Archiving
1.4 and passes the house lint.

On top of the APS transforms (DOCTYPE->1.4, inject manuscript-id + ANZSRC, OASIS tables ->
XHTML, graphic hrefs -> house assets) it normalises the NLM-2.x->JATS-1.x differences that
were breaking DTD validation (measured across real PMC/Frontiers papers, 2026-07-04):
  * <citation citation-type=X>        -> <mixed-citation publication-type=X>   (every ref)
  * <p> directly inside <license>      -> <license-p>
  * <custom-meta-wrap>                 -> <custom-meta-group>
  * bare <journal-title>/<abbrev-journal-title> in journal-meta -> wrapped in
    <journal-title-group>
  * children of <journal-meta> and <article-meta> re-sorted into JATS canonical order
    (fixes 'content does not follow the DTD' without caring which element was misplaced)
  * a few older funding elements (<contract-sponsor>/<contract-num>) unwrapped, content kept
"""
import argparse
import os
import re
import sys
from lxml import etree

JATS = "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD with MathML3 v1.4 20241031//EN"
DTD = "https://jats.nlm.nih.gov/archiving/1.4/JATS-archivearticle1-4-mathml3.dtd"
OASIS = "http://www.niso.org/standards/z39-96/ns/oasis-exchange/table"
XLINK = "http://www.w3.org/1999/xlink"

# mirrors the house lint's notion of an external href — anything else with no scheme is a
# LOCAL package-file reference and must resolve inside the package
EXT_SCHEMES = ("http://", "https://", "ftp://", "ftps://", "sftp://", "www.", "ftp.")


def is_local_href(h):
    h = (h or "").strip()
    if not h or h.startswith("#"):
        return False
    if h.lower().startswith(EXT_SCHEMES):
        return False
    if ":" in h.split("/")[0]:        # any other scheme'd URI (doi:, mailto:, ...)
        return False
    return True

# JATS canonical child order for the two order-sensitive metadata containers. A tuple = a
# repeatable choice-group whose members share a rank (stable sort keeps their interleaving).
JOURNAL_META_ORDER = ["journal-id", "journal-title-group",
                      ("contrib-group", "aff", "aff-alternatives"),
                      "issn", "issn-l", "isbn", "publisher", "notes", "self-uri"]
ARTICLE_META_ORDER = [
    "article-id", "article-version", "article-version-alternatives", "article-categories",
    "title-group", ("contrib-group", "aff", "aff-alternatives", "x", "author-notes"),
    "pub-date", "pub-date-not-available", "volume", "volume-id", "volume-series", "issue",
    "issue-id", "issue-title", "issue-title-group", "issue-sponsor", "issue-part",
    "volume-issue-group", "isbn", "supplement", "fpage", "elocation-id", "lpage",
    "page-range", "email", "ext-link", "uri", "product", "supplementary-material",
    "history", "pub-history", "permissions", "self-uri", "related-article", "related-object",
    "abstract", "trans-abstract", "kwd-group", "funding-group", "support-group",
    "conference", "counts", "custom-meta-group"]


def _rankmap(order):
    m = {}
    for i, item in enumerate(order):
        for name in (item if isinstance(item, tuple) else (item,)):
            m[name] = i
    return m


def ln(el):
    t = el.tag
    if not isinstance(t, str):      # comment / processing-instruction / entity node
        return ""
    return t.rsplit("}", 1)[-1] if "}" in t else t


def normalize_flavour(root, log):
    # 1. <citation> -> <mixed-citation>; @citation-type -> @publication-type
    n = 0
    for c in root.iter():
        if ln(c) == "citation":
            c.tag = "mixed-citation"
            ct = c.get("citation-type")
            if ct is not None and c.get("publication-type") is None:
                c.set("publication-type", ct)
            c.attrib.pop("citation-type", None)
            n += 1
    if n:
        log.append(f"citation->mixed-citation x{n}")

    # 2. <p> directly under <license> -> <license-p>
    n = 0
    for lic in (e for e in root.iter() if ln(e) == "license"):
        for p in lic:
            if ln(p) == "p":
                p.tag = "license-p"; n += 1
    if n:
        log.append(f"license/p->license-p x{n}")

    # 3. custom-meta-wrap -> custom-meta-group
    n = 0
    for e in root.iter():
        if ln(e) == "custom-meta-wrap":
            e.tag = "custom-meta-group"; n += 1
    if n:
        log.append(f"custom-meta-wrap->group x{n}")

    # 4. bare journal-title / abbrev-journal-title / journal-subtitle -> journal-title-group
    for jm in (e for e in root.iter() if ln(e) == "journal-meta"):
        bare = [c for c in jm if ln(c) in ("journal-title", "journal-subtitle",
                                           "abbrev-journal-title", "trans-title-group")]
        if bare and not any(ln(c) == "journal-title-group" for c in jm):
            grp = etree.Element("journal-title-group")
            idx = list(jm).index(bare[0])
            for b in bare:
                jm.remove(b); grp.append(b)
            jm.insert(idx, grp)
            log.append("wrapped journal-title-group")

    # 4b. normalise the CC licence onto the <license> element itself. Publishers scatter the
    # CC URI (ali:license_ref, ext-link, plain text, or the href) — the house lint wants it as
    # license-type + @xlink:href. We only ever promote a URI actually present in the source.
    n = 0
    for lic in (e for e in root.iter() if ln(e) == "license"):
        blob = etree.tostring(lic, encoding="unicode")
        m = re.search(r"https?://creativecommons\.org/licenses/[a-z-]+/[0-9.]+/?", blob)
        if m:
            uri = m.group(0).replace("http://", "https://")
            if not (lic.get("{%s}href" % XLINK) or "").strip():
                lic.set("{%s}href" % XLINK, uri)
            if lic.get("license-type") != "creative-commons":
                lic.set("license-type", "creative-commons")
            n += 1
    if n:
        log.append(f"normalised CC licence x{n}")

    # 4c. author typing: some publishers mark authorship on <contrib-group content-type=
    # "author"> and leave each <contrib> untyped. House style wants contrib-type="author" on
    # each contrib. Set it where missing, unless the group is explicitly editors.
    n = 0
    for cg in (e for e in root.iter() if ln(e) == "contrib-group"):
        if (cg.get("content-type") or "author").lower() == "editor":
            continue
        for c in cg:
            if ln(c) == "contrib" and not c.get("contrib-type"):
                c.set("contrib-type", "author"); n += 1
    if n:
        log.append(f"typed contrib author x{n}")

    # 4d. hoist figure graphics out of <alternatives>: publishers wrap the figure image in
    # <fig><alternatives><graphic .jpg/><graphic .gif/></alternatives>; house style wants ONE
    # <graphic> as a direct child of <fig>. Keep the primary (prefer non-gif), drop the rest.
    def _href(g):
        for k, v in g.attrib.items():
            if k.rsplit("}", 1)[-1] == "href":
                return v
        return ""
    n = 0
    for fig in (e for e in root.iter() if ln(e) == "fig"):
        for alt in [c for c in fig if ln(c) == "alternatives"]:
            graphics = [k for k in alt if ln(k) == "graphic"]
            if graphics and all(ln(k) in ("graphic", "media") for k in alt):
                primary = next((g for g in graphics
                                if not _href(g).lower().endswith(".gif")), graphics[0])
                i = list(fig).index(alt)
                fig.remove(alt)
                fig.insert(i, primary)
                n += 1
    if n:
        log.append(f"hoisted fig graphic x{n}")

    # 4e. ext-link hrefs: publishers leave bare DOIs (-> https://doi.org/…) and sometimes a
    # PubMed search string as a "link"; the latter isn't a URL, so unwrap it to plain text.
    nfix, nunwrap = 0, 0
    for el in [e for e in root.iter() if ln(e) == "ext-link"]:
        href = None
        for k in list(el.attrib):
            if k.rsplit("}", 1)[-1] == "href":
                href = el.attrib[k]; hk = k
        if href is None:
            continue
        h = href.strip()
        if re.match(r"^10\.\d{4,9}/\S+$", h):
            el.attrib[hk] = "https://doi.org/" + h; nfix += 1
        elif not re.match(r"^(https?|ftp|ftps|sftp)://|^www\.|^ftp\.", h):
            par = el.getparent()                      # not a URL -> unwrap to text
            if par is not None:
                txt = "".join(el.itertext())
                prev = el.getprevious()
                if prev is not None:
                    prev.tail = (prev.tail or "") + txt + (el.tail or "")
                else:
                    par.text = (par.text or "") + txt + (el.tail or "")
                par.remove(el); nunwrap += 1
    if nfix:
        log.append(f"ext-link bare-doi->https x{nfix}")
    if nunwrap:
        log.append(f"unwrapped non-url ext-link x{nunwrap}")

    # 4f. formula alternatives: publishers ship BOTH a math image (<inline-graphic>/<graphic>)
    # AND the MathML. The MathML is the archival ground truth and the image isn't in our asset
    # set, so drop the image where math is present (also clears the <alternatives> content rule).
    n = 0
    for f in (e for e in root.iter() if ln(e) in ("inline-formula", "disp-formula")):
        for alt in [c for c in f if ln(c) == "alternatives"]:
            has_math = any(ln(k) in ("math", "tex-math") for k in alt)
            if has_math:
                for img in [k for k in alt if ln(k) in ("inline-graphic", "graphic")]:
                    alt.remove(img); n += 1
    if n:
        log.append(f"dropped redundant math image x{n}")

    # 4g. licence ext-link: house lint wants the visible URI to equal @xlink:href. Publishers
    # sometimes differ by a trailing slash etc.; make the href match the text.
    for lic in (e for e in root.iter() if ln(e) == "license"):
        for el in (x for x in lic.iter() if ln(x) == "ext-link"):
            content = "".join(el.itertext()).strip()
            if content.startswith(("http://", "https://")):
                for k in list(el.attrib):
                    if k.rsplit("}", 1)[-1] == "href":
                        el.attrib[k] = content

    # 5. unwrap a few older funding elements the 1.4 DTD doesn't declare (keep their content)
    for name in ("contract-sponsor", "contract-num"):
        for e in [x for x in root.iter() if ln(x) == name]:
            par = e.getparent()
            if par is None:
                continue
            i = list(par).index(e)
            for ch in reversed(list(e)):
                par.insert(i, ch)
            if (e.text or "").strip():          # keep any text on a trailing sibling's tail
                prev = e.getprevious()
                if prev is not None:
                    prev.tail = (prev.tail or "") + e.text
            par.remove(e)
            log.append(f"unwrapped {name}")

    # 6. every <aff> needs an @id (house lint: an aff without one can't be
    # cross-referenced). PMC/NLM sometimes emits affiliations with no id;
    # synthesize stable ones, avoiding collisions with any ids already present.
    seen = {a.get("id") for a in root.iter() if ln(a) == "aff" and a.get("id")}
    ai, n = 0, 0
    for aff in (e for e in root.iter() if ln(e) == "aff"):
        if aff.get("id"):
            continue
        ai += 1
        nid = f"aff{ai}"
        while nid in seen:
            ai += 1
            nid = f"aff{ai}"
        aff.set("id", nid)
        seen.add(nid)
        n += 1
    if n:
        log.append(f"assigned aff id x{n}")


def reorder_meta(root, log):
    for tag, order in (("journal-meta", JOURNAL_META_ORDER),
                       ("article-meta", ARTICLE_META_ORDER)):
        rm = _rankmap(order)
        for meta in (e for e in root.iter() if ln(e) == tag):
            kids = [c for c in meta if isinstance(c.tag, str)]   # skip comments/PIs
            ordered = sorted(kids, key=lambda c: rm.get(ln(c), 9999))
            if [id(k) for k in kids] != [id(k) for k in ordered]:
                for k in kids:
                    meta.remove(k)
                for k in ordered:
                    meta.append(k)
                log.append(f"reordered {tag}")


# ---- (below: the APS-proven transforms, unchanged) ----
def oasis_to_xhtml(table_wrap):
    for otbl in [e for e in table_wrap.iter() if ln(e) == "table" and e.nsmap.get(e.prefix) == OASIS]:
        tgroup = next((c for c in otbl if ln(c) == "tgroup"), None)
        if tgroup is None:
            continue
        colnames = [c.get("colname") for c in tgroup if ln(c) == "colspec"]
        new = etree.Element("table")
        for sect in tgroup:
            if ln(sect) not in ("thead", "tbody"):
                continue
            xsect = etree.SubElement(new, ln(sect))
            for row in (r for r in sect if ln(r) == "row"):
                tr = etree.SubElement(xsect, "tr")
                cell = "th" if ln(sect) == "thead" else "td"
                for entry in (e for e in row if ln(e) == "entry"):
                    td = etree.SubElement(tr, cell)
                    ns, ne = entry.get("namest"), entry.get("nameend")
                    if ns and ne and ns in colnames and ne in colnames:
                        span = colnames.index(ne) - colnames.index(ns) + 1
                        if span > 1:
                            td.set("colspan", str(span))
                    if entry.get("align"):
                        td.set("align", entry.get("align"))
                    td.text = entry.text
                    for ch in entry:
                        td.append(ch)
        if len(new):
            otbl.getparent().replace(otbl, new)


def ln_attr(a):
    return a.rsplit("}", 1)[-1] if "}" in a else a


def ensure_root_ns(root, want):
    """Guarantee the root binds these prefix->uri namespaces (JATS DTD is prefix-sensitive:
    it declares xlink:href / mml:*, so an lxml-invented 'ns0' prefix fails validation)."""
    nsmap = dict(root.nsmap or {})
    if all(nsmap.get(p) == u for p, u in want.items()):
        return root
    nsmap.update(want)
    new = etree.Element(root.tag, nsmap=nsmap)
    new.text, new.tail = root.text, root.tail
    for k, v in root.attrib.items():
        new.set(k, v)
    for ch in list(root):
        new.append(ch)
    return new


def crosswalk(src, out_dir, mid, anzsrc_xml):
    parser = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)
    tree = etree.parse(src, parser)
    doc_root = tree.getroot()
    # Some Europe PMC fullTextXML responses wrap the article in a container
    # (<pmc-articleset>, <article-set>…). Descend to the real <article> so the
    # rest of the crosswalk operates on it, not the wrapper.
    if ln(doc_root) != "article":
        inner = next((c for c in doc_root.iter() if ln(c) == "article"), None)
        if inner is not None:
            doc_root = inner
    root = ensure_root_ns(doc_root,
                          {"xlink": XLINK, "mml": "http://www.w3.org/1998/Math/MathML"})
    log = []

    root.set("dtd-version", "1.4")
    root.set("article-type", root.get("article-type") or "research-article")
    lang = root.get("{http://www.w3.org/XML/1998/namespace}lang")
    root.set("{http://www.w3.org/XML/1998/namespace}lang", (lang or "en").lower())

    normalize_flavour(root, log)

    am = root.find(".//{*}article-meta")
    mid_el = etree.Element("article-id"); mid_el.set("pub-id-type", "manuscript-id"); mid_el.text = mid
    am.insert(0, mid_el)
    cats = am.find("{*}article-categories")
    anz = etree.fromstring(anzsrc_xml)
    if cats is None:
        idxs = [i for i, c in enumerate(am) if ln(c) == "article-id"]
        am.insert((idxs[-1] + 1) if idxs else 0, anz)
    else:
        for g in anz:               # merge our anzsrc groups into the existing categories
            cats.append(g)

    for tw in root.iter("{*}table-wrap"):
        oasis_to_xhtml(tw)

    adir = os.path.join(out_dir, "assets")
    have = set(os.listdir(adir)) if os.path.isdir(adir) else set()

    def _get_href(g):
        for a in g.attrib:
            if ln_attr(a) == "href":
                return g.attrib[a]
        return None

    def _set_href(g, val):
        for a in list(g.attrib):
            if ln_attr(a) == "href":
                del g.attrib[a]
        g.set("{%s}href" % XLINK, val)

    # pass A — publisher mode: every image whose basename we harvested resolves by exact name
    for g in (e for e in root.iter() if ln(e) in ("graphic", "inline-graphic")):
        cur = _get_href(g)
        if cur and os.path.basename(cur) in have:
            _set_href(g, "assets/" + os.path.basename(cur))
    # pass B — PDF-extraction fallback. Wire the extracted fig{N} images onto the <fig>
    # elements that still need a graphic — but ONLY when the two sets line up EXACTLY
    # (contiguous fig1..figN, one per needing <fig>). Otherwise DECLINE and leave them
    # unwired: a single missing or over-detected extracted figure would shift every
    # subsequent figure onto the wrong image (silent mis-captioning), so we follow the
    # arXiv adapter's "decline rather than mis-map" rule. The house-lint's "every <fig>
    # needs a resolvable <graphic>" then flags the gap honestly (-> partial/escalate).
    byfig = {int(m.group(1)): "assets/" + f for f in have
             for m in [re.match(r"fig(\d+)\.", f)] if m}
    figs_needing = []
    for fig in root.iter("{*}fig"):
        g = fig.find(".//{*}graphic")
        if g is not None and not (_get_href(g) or "").startswith("assets/"):
            figs_needing.append((fig, g))
    n_need = len(figs_needing)
    if n_need and byfig.keys() == set(range(1, n_need + 1)):
        for i, (fig, g) in enumerate(figs_needing, 1):
            _set_href(g, byfig[i])
        log.append(f"wired {n_need} PDF-extracted figure(s) by exact fig1..fig{n_need} match")
    elif n_need:
        log.append(f"DECLINED PDF-fig wiring: {n_need} <fig> need graphics but extracted "
                   f"figures were {sorted(byfig)} (not a 1:1 fig1..figN match) — left unwired "
                   f"so the lint flags the gap rather than mis-captioning")

    # pass C — LOCAL non-image package files (2026-07-13 gate hardening: every local href on
    # <media>/<supplementary-material>/<inline-supplementary-material>/<self-uri> must resolve
    # case-exact inside the package). Same contract as pass A: whatever the route's asset
    # fetch captured resolves by basename onto assets/. What it did NOT capture is left
    # untouched ON PURPOSE — the lint flags it and the paper lands partial, never a silent
    # green (the figure discipline, applied to supplementary files).
    n_re, uncaptured = 0, []
    for el in (e for e in root.iter() if ln(e) in ("media", "supplementary-material",
                                                   "inline-supplementary-material")):
        cur = _get_href(el)
        if not (cur and is_local_href(cur)):
            continue
        base = os.path.basename(cur)
        if base in have:
            if cur != "assets/" + base:
                _set_href(el, "assets/" + base); n_re += 1
        else:
            uncaptured.append(base)
    if n_re:
        log.append(f"supplementary href -> assets/ x{n_re}")
    if uncaptured:
        log.append("UNCAPTURED supplementary file(s) left for the lint to flag: "
                   + ", ".join(sorted(set(uncaptured))))
    # <self-uri> is different in kind: it is the SOURCE package's pointer to its own
    # alternate rendition (e.g. PMC's content-type="pmc-pdf" article PDF) — packaging
    # metadata about a file we deliberately do not ship, not article content. Keeping it
    # would misdescribe OUR package, so drop any local-file self-uri we don't ship, logged.
    n_drop = 0
    for su in [e for e in root.iter() if ln(e) == "self-uri"]:
        cur = _get_href(su)
        if not (cur and is_local_href(cur)):
            continue
        base = os.path.basename(cur)
        if base in have:
            if cur != "assets/" + base:
                _set_href(su, "assets/" + base); n_re += 1
        elif su.getparent() is not None:
            su.getparent().remove(su); n_drop += 1
    if n_drop:
        log.append(f"dropped local-file self-uri x{n_drop} (source-package rendition, not shipped)")

    reorder_meta(root, log)

    # keep mml declared even when the article carries no math yet — the house root
    # attributes expect the namespace present (the lint warns on its absence), and
    # cleanup_namespaces would otherwise strip it as unused
    etree.cleanup_namespaces(root, keep_ns_prefixes=("mml", "xlink"))
    body = etree.tostring(root, encoding="unicode")
    doc = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<!DOCTYPE article PUBLIC "%s"\n         "%s">\n%s\n' % (JATS, DTD, body))
    outp = os.path.join(out_dir, "article.xml")
    with open(outp, "w", encoding="utf-8") as f:
        f.write(doc)
    return outp, log, root


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--mid", required=True)
    ap.add_argument("--anzsrc", required=True)
    args = ap.parse_args()
    os.makedirs(os.path.join(args.out, "assets"), exist_ok=True)
    anz = open(args.anzsrc, encoding="utf-8").read()
    outp, log, root = crosswalk(args.src, args.out, args.mid, anz)
    nfig = len(list(root.iter("{*}fig")))
    ntbl = len(list(root.iter("{*}table-wrap")))
    nref = len(list(root.iter("{*}ref")))
    print("wrote %s  (figs=%d tables=%d refs=%d)" % (outp, nfig, ntbl, nref))
    print("  normalised: " + (", ".join(log) if log else "nothing (already clean JATS)"))


if __name__ == "__main__":
    main()
