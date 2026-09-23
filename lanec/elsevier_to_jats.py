#!/usr/bin/env python3
"""Elsevier journal-article XML (ce:/ja:/sb: DTD 5.x) -> generic JATS.

The Lane-C' transform for Elsevier (Physics Letters B, Nuclear Physics B via SCOAP3). Elsevier's
vocabulary is entirely different from JATS, so this rewrites it element-by-element into a JATS
<article> (front/body/back). The OUTPUT is plain JATS — it is then run through crosswalk_generic
for the house layer (manuscript-id, ANZSRC, licence, figure-asset hrefs, gates).

Structure: Elsevier article = item-info + floats (figures/tables) + head (title/authors/abstract)
+ body (sections) + tail (bibliography). Maths is already proper MathML (mml namespace) — kept.
Figures reference external NDATA entities (no image in the XML), so their graphics are left as
fig{N} placeholders for the caller's figure step to fill (PDF extraction / publisher figures).
References (sb:reference) are flattened to <mixed-citation> preserving the reference text verbatim.
"""
import argparse
import os
import re
import sys
from lxml import etree

MML = "http://www.w3.org/1998/Math/MathML"
XLINK = "http://www.w3.org/1999/xlink"
JATS = "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD with MathML3 v1.4 20241031//EN"
DTD = "https://jats.nlm.nih.gov/archiving/1.4/JATS-archivearticle1-4-mathml3.dtd"

# Elsevier localname -> JATS localname for simple inline/block passthrough
RENAME = {
    "para": "p", "simple-para": "p", "section-title": "title", "list": "list",
    "list-item": "list-item", "bold": "bold", "italic": "italic", "emphasis": "italic",
    "underline": "underline", "sup": "sup", "inf": "sub", "sub": "sub", "hsp": None,
    "glyph": None, "small-caps": "sc", "monospace": "monospace", "sans-serif": None,
}


_FN = []          # footnotes collected during a build (-> back/fn-group so xrefs resolve)


def ln(el):
    t = el.tag
    return "" if not isinstance(t, str) else t.rsplit("}", 1)[-1]


def text_of(el):
    return " ".join(t.strip() for t in el.itertext() if t and t.strip())


def copy_math(el):
    """Deep-copy an mml:math subtree, forcing the mml prefix on every node."""
    def rec(src):
        e = etree.Element("{%s}%s" % (MML, ln(src)))
        for k, v in src.attrib.items():
            e.set(k, v)
        e.text = src.text
        for c in src:
            if isinstance(c.tag, str):
                e.append(rec(c))
                e[-1].tail = c.tail
        return e
    return rec(el)


def conv_inline(src, parent):
    """Append converted inline content of `src` into JATS `parent` (text + inline children)."""
    parent.text = (parent.text or "") + (src.text or "")
    last = None
    for c in src:
        if not isinstance(c.tag, str):
            continue
        name = ln(c)
        if name == "math":
            j = copy_math(c)
            wrap = etree.SubElement(parent, "inline-formula")
            wrap.append(j)
            last = wrap
        elif name == "footnote":
            fid = c.get("id") or "fn%d" % (len(_FN) + 1)
            fn = etree.Element("fn"); fn.set("id", fid)
            lab = next((text_of(x) for x in c if ln(x) == "label"), None)
            if lab:
                etree.SubElement(fn, "label").text = lab
            for pp in c:
                if ln(pp) in ("note-para", "para", "simple-para"):
                    fn.append(conv_para(pp))
            if len(fn) == 0:
                etree.SubElement(fn, "p").text = text_of(c)
            _FN.append(fn)
            x = etree.SubElement(parent, "xref"); x.set("ref-type", "fn"); x.set("rid", fid)
            x.text = lab or "*"
            last = x
        elif name in ("cross-ref", "cross-refs"):
            x = etree.SubElement(parent, "xref")
            rid = c.get("refid", "").split()[0] if c.get("refid") else None
            if rid:
                x.set("rid", rid)
                if rid.startswith("fn"):
                    x.set("ref-type", "fn")
                elif rid.startswith(("fg", "fig")):
                    x.set("ref-type", "fig")
                elif rid.startswith(("tbl", "tb")):
                    x.set("ref-type", "table")
                elif rid.startswith(("br", "bib")):
                    x.set("ref-type", "bibr")
            conv_inline(c, x)
            last = x
        elif name in ("inter-ref", "e-address"):
            a = etree.SubElement(parent, "ext-link")
            href = c.get("{%s}href" % XLINK) or c.get("href") or text_of(c)
            a.set("ext-link-type", "uri"); a.set("{%s}href" % XLINK, href)
            a.text = text_of(c) or href
            last = a
        elif name == "list":
            parent.append(conv_list(c))
            last = parent[-1]
        elif RENAME.get(name):
            j = etree.SubElement(parent, RENAME[name])
            conv_inline(c, j)
            last = j
        else:                         # unknown/empty wrapper: unwrap its content, IN ORDER
            # Convert c ONCE into a scratch element, then splice its text+children in at the
            # current position. The old code both recursed AND re-appended c.text (duplicate),
            # and wrote to parent.text so the text jumped ahead of earlier siblings (reorder).
            tmp = etree.Element("tmp")
            conv_inline(c, tmp)
            if tmp.text:
                if last is not None:
                    last.tail = (last.tail or "") + tmp.text
                else:
                    parent.text = (parent.text or "") + tmp.text
            for ch in list(tmp):
                parent.append(ch)
                last = ch
        if last is not None:
            last.tail = (last.tail or "") + (c.tail or "")
        else:
            parent.text = (parent.text or "") + (c.tail or "")
    return parent


def conv_para(src):
    p = etree.Element("p")
    conv_inline(src, p)
    return p


def conv_list(src):
    import copy
    lst = etree.Element("list")
    lst.set("list-type", "order" if src.get("type") == "ordered" else "bullet")
    for it in src:
        if ln(it) != "list-item":
            continue
        li = etree.SubElement(lst, "list-item")
        paras = [c for c in it if ln(c) == "para"]
        if paras:                                    # item holds paragraphs -> one <p> each
            for pa in paras:
                li.append(conv_para(pa))
        else:                                        # item holds inline content -> wrap once
            p = etree.SubElement(li, "p")
            tmp = copy.deepcopy(it)
            for lb in [c for c in tmp if ln(c) == "label"]:
                tmp.remove(lb)
            conv_inline(tmp, p)
    return lst


def conv_section(src):
    sec = etree.Element("sec")
    if src.get("id"):
        sec.set("id", src.get("id"))
    for c in src:
        n = ln(c)
        if n == "section-title":
            t = etree.SubElement(sec, "title"); conv_inline(c, t)
        elif n == "label":
            pass
        elif n == "para":
            sec.append(conv_para(c))
        elif n == "section":
            sec.append(conv_section(c))
        elif n == "list":
            sec.append(conv_list(c))
        elif isinstance(c.tag, str) and text_of(c).strip():
            # Don't silently drop unknown block content (display formulas, floats placed
            # directly in a section): keep its text as a paragraph so nothing is lost before
            # gating — a visible <p> beats a silent omission.
            p = etree.SubElement(sec, "p"); conv_inline(c, p)
    return sec


def conv_figure(src, idx):
    fig = etree.Element("fig")
    fig.set("id", src.get("id") or "fig%d" % idx)
    for c in src:
        n = ln(c)
        if n == "label":
            lb = etree.SubElement(fig, "label"); lb.text = text_of(c)
        elif n == "caption":
            cap = etree.SubElement(fig, "caption")
            for sp in c:
                if ln(sp) in ("simple-para", "para"):
                    cap.append(conv_para(sp))
    g = etree.SubElement(fig, "graphic")
    g.set("{%s}href" % XLINK, "assets/fig%d.png" % idx)   # filled by the caller's figure step
    return fig


def conv_table(src, idx):
    tw = etree.Element("table-wrap")
    tw.set("id", src.get("id") or "tbl%d" % idx)
    for c in src:
        n = ln(c)
        if n == "label":
            lb = etree.SubElement(tw, "label"); lb.text = text_of(c)
        elif n == "caption":
            cap = etree.SubElement(tw, "caption")
            for sp in c:
                if ln(sp) in ("simple-para", "para"):
                    cap.append(conv_para(sp))
        elif n == "tgroup":
            tw.append(conv_tgroup(c))
    return tw


def conv_tgroup(tg):
    """CALS tgroup/row/entry -> JATS XHTML table."""
    colnames = [c.get("colname") for c in tg if ln(c) == "colspec"]
    table = etree.Element("table")
    for sect in tg:
        if ln(sect) not in ("thead", "tbody"):
            continue
        xs = etree.SubElement(table, ln(sect))
        for row in (r for r in sect if ln(r) == "row"):
            tr = etree.SubElement(xs, "tr")
            cell = "th" if ln(sect) == "thead" else "td"
            for entry in (e for e in row if ln(e) == "entry"):
                td = etree.SubElement(tr, cell)
                ns, ne = entry.get("namest"), entry.get("nameend")
                if ns and ne and ns in colnames and ne in colnames:
                    span = colnames.index(ne) - colnames.index(ns) + 1
                    if span > 1:
                        td.set("colspan", str(span))
                conv_inline(entry, td)
    return table


def conv_reference(bibref, idx):
    ref = etree.Element("ref")
    ref.set("id", bibref.get("id") or "r%d" % idx)
    label = next((text_of(c) for c in bibref if ln(c) == "label"), None)
    if label:
        lb = etree.SubElement(ref, "label"); lb.text = label.strip("[]")
    mc = etree.SubElement(ref, "mixed-citation")
    sb = next((c for c in bibref if ln(c) == "reference"), None)
    src = sb if sb is not None else bibref
    txt = " ".join(t.strip() for t in src.itertext()
                   if t and t.strip() and t.strip() != (label or ""))
    mc.text = re.sub(r"\s+", " ", txt).strip()
    # lift a DOI if present
    doi = next((text_of(c) for c in src.iter() if ln(c) == "doi"), None)
    if doi:
        cm = etree.SubElement(mc, "pub-id"); cm.set("pub-id-type", "doi"); cm.text = doi
    return ref


def _source_journal_title(raw):
    """The journal title as stated in the Elsevier source header (this transform serves
    several Elsevier journals — Physics Letters B, Nuclear Physics B, entitlement route —
    so it must not be hardcoded)."""
    for pat in (rb"<(?:\w+:)?publicationName>([^<]+)</(?:\w+:)?publicationName>",
                rb"<(?:\w+:)?srctitle>([^<]+)</(?:\w+:)?srctitle>"):
        m = re.search(pat, raw)
        if m:
            return m.group(1).decode("utf-8", "replace").strip()
    return None


def build(src_path, journal=None):
    _FN.clear()
    raw = open(src_path, "rb").read()
    raw = re.sub(rb"<!DOCTYPE(?:[^>\[]|\[[^\]]*\])*>", b"", raw, flags=re.S)
    el = etree.fromstring(raw, etree.XMLParser(recover=True, resolve_entities=False, no_network=True))
    find = lambda name: next((e for e in el.iter() if ln(e) == name), None)

    art = etree.Element("article", nsmap={"mml": MML, "xlink": XLINK})
    art.set("article-type", "research-article")
    art.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    front = etree.SubElement(art, "front")
    jm = etree.SubElement(front, "journal-meta")
    jt = etree.SubElement(jm, "journal-title-group")
    etree.SubElement(jt, "journal-title").text = (
        journal or _source_journal_title(raw) or "Unknown journal")
    etree.SubElement(jm, "publisher").append(_e("publisher-name", "Elsevier"))
    am = etree.SubElement(front, "article-meta")
    doi = find("doi")
    if doi is not None and doi.text:
        aid = etree.SubElement(am, "article-id"); aid.set("pub-id-type", "doi"); aid.text = doi.text
    tg = etree.SubElement(am, "title-group")
    title = find("title")
    at = etree.SubElement(tg, "article-title")
    if title is not None:
        conv_inline(title, at)

    # contributors + affiliations. Process ALL author-groups, not just the first: multi-group
    # (non-collaboration) papers spread their authors across several groups, and the old
    # `break` dropped everyone after the first. Dedup by element identity so an author captured
    # twice by the recursive iter (nested groups) isn't duplicated; dedup collaborations by name.
    cg = etree.SubElement(am, "contrib-group")
    affs = []
    seen_collab, seen_ids, ordered_authors = set(), set(), []
    for ag in el.iter():
        if ln(ag) != "author-group":
            continue
        for c in ag:
            if ln(c) == "collaboration":
                cname = text_of(next((t for t in c if ln(t) == "text"), c))
                if cname and cname not in seen_collab:
                    seen_collab.add(cname)
                    col = etree.SubElement(cg, "contrib"); col.set("contrib-type", "author")
                    etree.SubElement(col, "collab").text = cname
        for au in (a for a in ag.iter() if ln(a) == "author"):
            if id(au) not in seen_ids:
                seen_ids.add(id(au)); ordered_authors.append(au)
    for au in ordered_authors:
        contrib = etree.SubElement(cg, "contrib"); contrib.set("contrib-type", "author")
        if au.get("orcid"):
            cid = etree.SubElement(contrib, "contrib-id"); cid.set("contrib-id-type", "orcid")
            cid.text = "https://orcid.org/" + au.get("orcid")
        name = etree.SubElement(contrib, "name")
        sur = next((text_of(x) for x in au if ln(x) == "surname"), "")
        giv = next((text_of(x) for x in au if ln(x) == "given-name"), "")
        etree.SubElement(name, "surname").text = sur
        if giv:
            etree.SubElement(name, "given-names").text = giv
    ai = 0
    for aff in el.iter():
        if ln(aff) != "affiliation":
            continue
        ai += 1
        a = etree.SubElement(am, "aff")
        a.set("id", aff.get("id") or "aff%d" % ai)     # every aff needs an id (house rule)
        tf = next((text_of(x) for x in aff if ln(x) == "textfn"), text_of(aff))
        a.text = tf

    ab = find("abstract")
    if ab is not None:
        jab = etree.SubElement(am, "abstract")
        for sec in ab:
            for p in sec:
                if ln(p) in ("simple-para", "para"):
                    jab.append(conv_para(p))

    # permissions: derive the licence from the SOURCE — NEVER fabricate one. Elsevier
    # entitlement content is only guaranteed *readable*, not CC-BY (UoM's own VoRs are
    # frequently CC-BY-NC-ND), and SCOAP3 content, while CC-BY by consortium rule, still
    # carries its own <oa:userLicense>. So we emit ONLY the licence the source actually
    # declares. If the source carries no Creative Commons licence URI, we emit no <license>
    # at all: the house lint (which requires <license>) and the ingest licence gate then
    # block the package rather than letting it ship a fabricated open-access claim.
    perm = etree.SubElement(am, "permissions")
    cr = next((text_of(c) for c in el.iter() if ln(c) == "copyright"), None)
    if cr:
        etree.SubElement(perm, "copyright-statement").text = cr
    m = re.search(rb"https?://creativecommons\.org/licenses/[a-z-]+/[0-9.]+/?", raw, re.I)
    if m:
        uri = m.group(0).decode("ascii").replace("http://", "https://")
        flavour = uri.split("/licenses/", 1)[1].split("/", 1)[0].upper()
        lic = etree.SubElement(perm, "license")
        lic.set("license-type", "creative-commons")
        lic.set("{%s}href" % XLINK, uri)
        etree.SubElement(lic, "license-p").text = (
            f"This is an open access article distributed under the terms of the Creative "
            f"Commons {flavour} licence ({uri}).")

    # body: sections, then floats (figures/tables) appended
    body = etree.SubElement(art, "body")
    src_body = find("body")
    if src_body is not None:
        for c in src_body:
            if ln(c) == "sections":
                for s in c:
                    if ln(s) == "section":
                        body.append(conv_section(s))
            elif ln(c) == "section":
                body.append(conv_section(c))
            elif ln(c) == "para":
                body.append(conv_para(c))
    floats = find("floats")
    fi = ti = 0
    if floats is not None:
        # floats can't sit as siblings of <sec> in the body content model; house them in a
        # trailing section (they are xref'd from the text, so placement is presentational).
        secs = [c for c in body if ln(c) == "sec"]
        host = etree.SubElement(body, "sec")
        etree.SubElement(host, "title").text = "Figures and tables"
        for c in floats:
            if ln(c) == "figure":
                fi += 1; host.append(conv_figure(c, fi))
            elif ln(c) == "table":
                ti += 1; host.append(conv_table(c, ti))
        if len(host) <= 1:
            body.remove(host)

    # back: footnotes (collected during body conversion) + bibliography
    bib = find("bibliography")
    if _FN or bib is not None:
        back = etree.SubElement(art, "back")
        if _FN:
            fg = etree.SubElement(back, "fn-group")
            seen = set()
            for fn in _FN:
                if fn.get("id") not in seen:      # de-dupe by id
                    seen.add(fn.get("id")); fg.append(fn)
        if bib is not None:
            rl = etree.SubElement(back, "ref-list")
            etree.SubElement(rl, "title").text = "References"
            ri = 0
            for br in (b for b in bib.iter() if ln(b) == "bib-reference"):
                ri += 1; rl.append(conv_reference(br, ri))
    return art


def _e(tag, text):
    e = etree.Element(tag); e.text = text; return e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out", required=True, help="output JATS path")
    ap.add_argument("--journal", default=None,
                    help="journal title (authoritative, e.g. from the work-tracker DB); "
                         "falls back to the source header, then 'Unknown journal'")
    args = ap.parse_args()
    art = build(args.src, journal=args.journal)
    etree.cleanup_namespaces(art)
    body = etree.tostring(art, encoding="unicode")
    doc = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE article PUBLIC "%s"\n         "%s">\n%s\n'
           % (JATS, DTD, body))
    open(args.out, "w", encoding="utf-8").write(doc)
    n = lambda t: len(list(art.iter(t)))
    print("wrote %s (secs=%d figs=%d tables=%d refs=%d)"
          % (args.out, n("sec"), n("fig"), n("table-wrap"), n("ref")))


if __name__ == "__main__":
    main()
