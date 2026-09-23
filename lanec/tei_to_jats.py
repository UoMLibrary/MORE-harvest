#!/usr/bin/env python3
"""GROBID TEI -> generic JATS (the Lane-B convert_vor transform).

For the ~half of convert_vor works OpenAlex has already GROBID-parsed, we don't
reverse-engineer the PDF from scratch: GROBID's TEI is structured XML, so this rewrites
it element-by-element into a JATS <article> (front/body/back) — exactly the role
elsevier_to_jats.py plays for Elsevier XML. The OUTPUT is plain JATS and is then run
through crosswalk_generic for the house layer (manuscript-id, ANZSRC, figure hrefs,
gates).

Two house disciplines, both learned from real TEI (pilot/grobid_tei.xml):
  * GROBID does NOT reliably recover the JOURNAL title or the LICENCE (TEI <licence> is
    empty, monogr/title often missing). So both come from the AUTHORITATIVE OpenAlex
    metadata the caller passes (--journal, --license) — NEVER fabricated, NEVER trusted
    from the TEI. With no CC licence supplied, we emit no <license>, so the house lint
    and licence gate block the package rather than shipping an unverified openness claim.
  * Figures carry no image (GROBID only has the caption/figDesc), so they become
    assets/figN.png placeholders for the caller's figure step to fill (PDF extraction).

Per-publisher variation (reference style, heading numbering) comes from publisher_rules.
"""
import argparse
import json
import re
import sys
from lxml import etree

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
import publisher_rules as pr  # noqa: E402

TEI = "http://www.tei-c.org/ns/1.0"
MML = "http://www.w3.org/1998/Math/MathML"
XLINK = "http://www.w3.org/1999/xlink"
NS = {"t": TEI}
JATS = "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD with MathML3 v1.4 20241031//EN"
DTD = "https://jats.nlm.nih.gov/archiving/1.4/JATS-archivearticle1-4-mathml3.dtd"

NUM_HEAD = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(.*)$")   # "3.1 Methods" / "3. Methods"


def ln(el):
    t = el.tag
    return "" if not isinstance(t, str) else t.rsplit("}", 1)[-1]


def txt(el):
    if el is None:
        return ""
    return re.sub(r"\s+", " ", " ".join(t for t in el.itertext() if t)).strip()


def first(root, xp):
    r = root.xpath(xp, namespaces=NS)
    return r[0] if r else None


def all_(root, xp):
    return root.xpath(xp, namespaces=NS)


# ---- body: TEI div/head/p(/s) -> JATS sec/title/p, with figure & bibr xrefs ----------

def conv_p(tei_p):
    """A TEI <p> holds <s> sentence spans and inline <ref>. Flatten to a JATS <p>,
    turning ref[@type=bibr]->xref(bibr), ref[@type=figure]->xref(fig)."""
    p = etree.Element("p")
    last = None

    def emit_text(s):
        nonlocal last
        if not s:
            return
        if last is not None:
            last.tail = (last.tail or "") + s
        else:
            p.text = (p.text or "") + s

    def walk(node):
        nonlocal last
        emit_text(node.text)
        for c in node:
            name = ln(c)
            if name == "ref":
                rtype = c.get("type")
                x = etree.SubElement(p, "xref")
                target = (c.get("target") or "").lstrip("#")
                if rtype == "bibr":
                    x.set("ref-type", "bibr")
                    if target:
                        x.set("rid", target)
                elif rtype == "figure":
                    x.set("ref-type", "fig")
                    if target:
                        x.set("rid", target)
                elif rtype == "table":
                    x.set("ref-type", "table")
                    if target:
                        x.set("rid", target)
                x.text = txt(c)
                last = x
                emit_text(c.tail)
            elif name in ("s", "hi", "seg"):
                walk(c)                    # unwrap sentence/highlight spans, keep order
                emit_text(c.tail)
            elif name == "formula":
                # display/inline formula: keep its text (MathML recovery is a later pass)
                f = etree.SubElement(p, "italic")
                f.text = txt(c)
                last = f
                emit_text(c.tail)
            else:
                emit_text(txt(c))
                emit_text(c.tail)

    walk(tei_p)
    return p


def conv_section(div, rule, idx):
    sec = etree.Element("sec")
    sec.set("id", div.get("{http://www.w3.org/XML/1998/namespace}id") or f"sec{idx}")
    head = first(div, "./t:head")
    if head is not None:
        htxt = txt(head)
        n = head.get("n")
        # split a numeric prefix into <label> when the publisher numbers its headings.
        # JATS <sec> content order is (label?, title?), so the label is added FIRST.
        m = NUM_HEAD.match(htxt)
        title_text = htxt
        if rule.headings_numbered and (n or m):
            label = (n or (m.group(1) if m else "")).rstrip(".")  # "2.1." -> "2.1"
            if label:
                etree.SubElement(sec, "label").text = label
            title_text = m.group(2) if m else htxt
        etree.SubElement(sec, "title").text = title_text
    for p in all_(div, "./t:p"):
        sec.append(conv_p(p))
    return sec


def conv_figure(fig, idx, is_table=False):
    if is_table:
        el = etree.Element("table-wrap")
        el.set("id", fig.get("{http://www.w3.org/XML/1998/namespace}id") or f"tbl{idx}")
    else:
        el = etree.Element("fig")
        el.set("id", fig.get("{http://www.w3.org/XML/1998/namespace}id") or f"fig{idx}")
    head = first(fig, "./t:head")
    desc = first(fig, "./t:figDesc")
    if head is not None and txt(head):
        etree.SubElement(el, "label").text = txt(head)
    cap = etree.SubElement(el, "caption")
    etree.SubElement(cap, "p").text = txt(desc) if desc is not None else (txt(head) or "")
    if not is_table:
        g = etree.SubElement(el, "graphic")
        g.set("{%s}href" % XLINK, "assets/fig%d.png" % idx)   # filled by the figure step
    return el


def conv_reference(bibl, idx, style):
    ref = etree.Element("ref")
    ref.set("id", bibl.get("{http://www.w3.org/XML/1998/namespace}id") or f"b{idx}")
    if style == "numbered":
        etree.SubElement(ref, "label").text = str(idx)
    mc = etree.SubElement(ref, "mixed-citation")
    # verbatim citation text (safe, lossless) — element-citation structuring is a later pass
    mc.text = txt(bibl)
    doi = first(bibl, './/t:idno[@type="DOI"]')
    if doi is not None and txt(doi):
        pid = etree.SubElement(mc, "pub-id")
        pid.set("pub-id-type", "doi")
        pid.text = txt(doi)
    return ref


CITE_CORE = re.compile(r"[0-9A-Za-z]+")


def _clean_numbered_xref_text(art):
    """Numbered citations: GROBID leaves bracket/comma inside the xref ('[2,', '3]').
    Move the punctuation OUTSIDE so the xref content is just the token ('2', '3') — the
    house lint requires separators to sit between, not inside, xrefs. Guarded to
    NUMERIC-cored xrefs only, so it is safe to run for every publisher: an author-year
    citation ('(Smith et al., 2020)') must never be truncated to its first token."""
    for x in art.iter("xref"):
        if x.get("ref-type") not in ("bibr", "fig", "table"):
            continue
        raw = x.text or ""
        if re.search(r"[A-Za-z]", raw):
            continue
        m = CITE_CORE.search(raw)
        if not m:
            continue
        lead, core, trail = raw[:m.start()], m.group(0), raw[m.end():]
        x.text = core
        if lead:
            prev = x.getprevious()
            if prev is not None:
                prev.tail = (prev.tail or "") + lead
            else:
                x.getparent().text = (x.getparent().text or "") + lead
        if trail:
            x.tail = trail + (x.tail or "")


def _relink_numbered_bibr(art):
    """Re-link any bibr xref GROBID left without a target, by matching its number to the
    reference label (RSC refs are numbered, so label == citation number)."""
    by_label = {}
    for i, r in enumerate(art.iter("ref")):
        lab = (r.findtext("label") or "").strip()
        if lab.isdigit():
            by_label.setdefault(lab, r.get("id"))
        by_label.setdefault(str(i + 1), r.get("id"))   # positional fallback
    n = 0
    for x in art.iter("xref"):
        if x.get("ref-type") != "bibr" or x.get("rid"):
            continue
        num = (x.text or "").strip()
        if num.isdigit() and num in by_label:
            x.set("rid", by_label[num])
            n += 1
    return n


def _relink_fig_xrefs(art):
    """Link fig xrefs (all publishers) by the number in the citation vs the figure label
    ('Figure 1' -> fig id)."""
    by_num = {}
    for f in art.iter("fig"):
        m = re.search(r"\d+", f.findtext("label") or "")
        if m:
            by_num.setdefault(m.group(0), f.get("id"))
    n = 0
    for x in art.iter("xref"):
        if x.get("ref-type") != "fig" or x.get("rid"):
            continue
        m = re.search(r"\d+", x.text or "")
        if m and m.group(0) in by_num:
            x.set("rid", by_num[m.group(0)])
            n += 1
    return n


def _trim_xref_boundary_punct(art):
    """Boundary punctuation belongs OUTSIDE a citation link: '(Berger et al., 2019;'
    becomes '(' + xref['Berger et al., 2019'] + ';'. Runs for every typed xref, linked
    or not — it never touches the citation text itself, only its edges."""
    for x in art.iter("xref"):
        if x.get("ref-type") not in ("bibr", "fig", "table"):
            continue
        raw = x.text or ""
        m = re.match(r"^([\s(\[]*)(.*?)([\s;,.)\]]*)$", raw, re.S)
        if not m or (not m.group(1) and not m.group(3)):
            continue
        lead, core, trail = m.groups()
        if not core:
            continue
        x.text = core
        if lead:
            prev = x.getprevious()
            if prev is not None:
                prev.tail = (prev.tail or "") + lead
            else:
                x.getparent().text = (x.getparent().text or "") + lead
        if trail:
            x.tail = trail + (x.tail or "")


def _collapse_space_runs(art):
    """GROBID sentence spans leave double spaces at element boundaries; collapse runs of
    literal spaces in prose text/tails (display whitespace only — never content)."""
    for el in art.iter():
        if el.text and "  " in el.text:
            el.text = re.sub(r" {2,}", " ", el.text)
        if el.tail and "  " in el.tail:
            el.tail = re.sub(r" {2,}", " ", el.tail)


_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_SURNAME = re.compile(r"[A-Za-zÀ-ÿ'’-]{2,}")
_NOT_SURNAMES = {"et", "al", "and", "the", "in", "see", "cf", "eg", "ie"}


def _relink_authoryear_bibr(art):
    """Link author-year citations GROBID left without a target, by matching the
    (first-surname, year) pair in the xref text against the reference list. Strictly
    conservative: a key that matches more than one reference is discarded, and an xref
    links only when its candidates hit exactly ONE reference — ambiguity stays unlinked
    (and is then unwrapped to plain text rather than shipped as a dead link)."""
    idx, dupes = {}, set()
    for r in art.iter("ref"):
        mc = r.find("mixed-citation")
        text = "".join(mc.itertext()) if mc is not None else ""
        ym = _YEAR.search(text)
        sm = _SURNAME.search(text)
        if not (ym and sm):
            continue
        key = (sm.group(0).lower(), ym.group(0))
        if key in idx and idx[key] != r.get("id"):
            dupes.add(key)
        idx.setdefault(key, r.get("id"))
    n = 0
    for x in art.iter("xref"):
        if x.get("ref-type") != "bibr" or x.get("rid"):
            continue
        t = x.text or ""
        ym = _YEAR.search(t)
        if not ym:
            continue
        hits = set()
        for cand in _SURNAME.findall(t):
            key = (cand.lower(), ym.group(0))
            if key in idx and key not in dupes and cand.lower() not in _NOT_SURNAMES:
                hits.add(idx[key])
        if len(hits) == 1:
            x.set("rid", hits.pop())
            n += 1
    return n


def _unwrap_unlinked_xrefs(art):
    """An xref that links nowhere is worse than plain text: after every relink pass,
    any bibr/fig/table xref still without a @rid is unwrapped — its text stays in the
    prose, the dead element goes. (The lint would otherwise flag each one, rightly.)"""
    n = 0
    for x in list(art.iter("xref")):
        if x.get("ref-type") not in ("bibr", "fig", "table") or x.get("rid"):
            continue
        parent = x.getparent()
        if parent is None:
            continue
        text = (x.text or "") + (x.tail or "")
        prev = x.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + text
        else:
            parent.text = (parent.text or "") + text
        parent.remove(x)
        n += 1
    return n


def _drop_empty_p(art):
    """Remove padding <p> with no text and no children (GROBID artifact), preserving tail."""
    for p in list(art.iter("p")):
        if len(p) == 0 and not (p.text or "").strip():
            parent = p.getparent()
            if parent is None:
                continue
            if p.tail and p.tail.strip():
                prev = p.getprevious()
                if prev is not None:
                    prev.tail = (prev.tail or "") + p.tail
                else:
                    parent.text = (parent.text or "") + p.tail
            parent.remove(p)


def postprocess(art, rule):
    """Cleanup hooks, all evidence-based and conservative. The numeric passes are safe
    for every publisher (digit-guarded), so author-year publishers whose PDFs carry
    numeric citations GROBID misparsed still benefit; the author-year matcher runs for
    everyone too and only ever links an unambiguous (surname, year) hit. Whatever is
    STILL unlinked after all passes is unwrapped to plain text — never a dead link."""
    _drop_empty_p(art)
    _clean_numbered_xref_text(art)
    fig_linked = _relink_fig_xrefs(art)
    # number->label linking (with its positional fallback) only where the publisher's
    # style says citations ARE numbers; a stray digit under author-year must not guess
    bibr_linked = _relink_numbered_bibr(art) if rule.reference_style == "numbered" else 0
    bibr_linked += _relink_authoryear_bibr(art)
    unwrapped = _unwrap_unlinked_xrefs(art)
    _trim_xref_boundary_punct(art)
    _collapse_space_runs(art)
    return {"fig_relinked": fig_linked, "bibr_relinked": bibr_linked, "unwrapped": unwrapped}


# ---- back matter: TEI back divs -> their conventional JATS homes ---------------------
# GROBID parses funding / acknowledgements / data-availability / appendices into typed
# <back> divs; dropping them was a silent completeness hole (fidelity calibration,
# 2026-07-15: 93/93 such divs lost across the 76-pair pilot corpus, every package
# lint-green). Funding is FRONT matter in house style (<funding-group> in article-meta,
# as the PMC packages have it); the rest go to <back>. Prose is converted with conv_p so
# inline citations/fig refs become xrefs and ride the normal relink/unwrap passes.

def _back_title(div, default):
    """First head anywhere under the div (GROBID nests one wrapper div deep)."""
    h = first(div, ".//t:head")
    t = txt(h) if h is not None else ""
    return t or default


def _back_paras(div):
    """All prose <p> under a back div, converted (flat prose: funding/ack/availability)."""
    return [conv_p(p) for p in all_(div, ".//t:p") if txt(p)]


def _app_fill(app, unit):
    """Fill an <app> from an annex div, walking children IN ORDER so nothing is lost:
    p -> converted paragraph; nested div -> its head as a bold lead-in paragraph, then
    recurse (appendix sub-structure flattens, but every word survives); figures stay a
    body/attended concern and are not invented here."""
    for c in unit:
        name = ln(c)
        if name == "head":
            continue                                  # consumed as the app title
        if name == "p":
            if txt(c):
                app.append(conv_p(c))
        elif name == "div":
            h = first(c, "./t:head")
            if h is not None and txt(h):
                p = etree.SubElement(app, "p")
                etree.SubElement(p, "bold").text = txt(h)
            _app_fill(app, c)
        elif name == "figure":
            continue
        else:
            t = txt(c)
            if t:
                etree.SubElement(app, "p").text = t


def build(tei_path, journal=None, license_url=None, publisher=None, title=None, authors=None):
    root = etree.parse(tei_path).getroot()
    rule = pr.for_publisher(publisher)

    art = etree.Element("article", nsmap={"mml": MML, "xlink": XLINK})
    art.set("article-type", "research-article")
    art.set("{http://www.w3.org/XML/1998/namespace}lang", "en")

    front = etree.SubElement(art, "front")
    jm = etree.SubElement(front, "journal-meta")
    jtg = etree.SubElement(jm, "journal-title-group")
    # journal title: authoritative metadata first, TEI monogr/title only as last resort
    tei_journal = txt(first(root, '//t:sourceDesc//t:monogr/t:title'))
    etree.SubElement(jtg, "journal-title").text = (
        journal or (tei_journal if rule.trust_tei_journal else None) or "Unknown journal")
    pub = etree.SubElement(jm, "publisher")
    etree.SubElement(pub, "publisher-name").text = rule.display_name

    am = etree.SubElement(front, "article-meta")
    doi = txt(first(root, '//t:sourceDesc//t:idno[@type="DOI"]'))
    if doi:
        aid = etree.SubElement(am, "article-id")
        aid.set("pub-id-type", "doi")
        aid.text = doi
    tg = etree.SubElement(am, "title-group")
    # the document's own title first; when GROBID's header parse came up empty, fall
    # back to the AUTHORITATIVE metadata title the caller passes (works.title) — same
    # discipline as journal/licence: metadata fills what the TEI failed to recover.
    etree.SubElement(tg, "article-title").text = txt(first(root, '//t:titleStmt/t:title[@type="main"]')) \
        or txt(first(root, '//t:titleStmt/t:title')) or (title or None)

    # contributors + affiliations
    cg = etree.SubElement(am, "contrib-group")
    aff_index, ai = {}, 0
    for au in all_(root, '//t:sourceDesc//t:analytic/t:author'):
        pers = first(au, "./t:persName")
        if pers is None:
            continue
        # GROBID sometimes tags affiliation daggers / footnote glyphs as name parts
        # ('|', '★', '†¥') — a name part with no letters is not a name part. A contrib
        # whose SURNAME dissolves entirely is dropped rather than fabricated.
        sur = txt(first(pers, "./t:surname"))
        giv = " ".join(txt(f) for f in all_(pers, "./t:forename")).strip()
        if not re.search(r"[^\W\d_]", sur, re.UNICODE):
            continue
        if giv and not re.search(r"[^\W\d_]", giv, re.UNICODE):
            giv = ""
        contrib = etree.SubElement(cg, "contrib")
        contrib.set("contrib-type", "author")
        orcid = first(au, './t:idno[@type="ORCID"]')
        if orcid is not None and txt(orcid):
            cid = etree.SubElement(contrib, "contrib-id")
            cid.set("contrib-id-type", "orcid")
            oid = txt(orcid)
            cid.text = oid if oid.startswith("http") else "https://orcid.org/" + oid
        name = etree.SubElement(contrib, "name")
        etree.SubElement(name, "surname").text = sur
        if giv:
            etree.SubElement(name, "given-names").text = giv
        # link affiliations (dedup by normalised text)
        for aff in all_(au, "./t:affiliation"):
            atext = txt(first(aff, './t:note[@type="raw_affiliation"]')) or txt(aff)
            if not atext:
                continue
            if atext not in aff_index:
                ai += 1
                aid2 = f"aff{ai}"
                aff_index[atext] = aid2
            x = etree.SubElement(contrib, "xref")
            x.set("ref-type", "aff")
            x.set("rid", aff_index[atext])
    # Author fallback: when GROBID recovered NO parseable authors (an empty header parse,
    # not a dissolved-name drop), fall back to the AUTHORITATIVE OpenAlex authorships the
    # caller passes — same discipline as the journal/title/licence fallbacks: authoritative
    # metadata fills what the TEI failed to recover, never fabricated. (A partial GROBID
    # author list is kept as-is; the fallback fires only on total recovery failure, so a
    # good-text package no longer hard-fails the gate for want of a contrib.)
    if len(cg) == 0 and authors:
        for au in authors:
            sur = (au.get("surname") or "").strip()
            if not re.search(r"[^\W\d_]", sur, re.UNICODE):
                continue
            contrib = etree.SubElement(cg, "contrib")
            contrib.set("contrib-type", "author")
            if au.get("orcid"):
                cid = etree.SubElement(contrib, "contrib-id")
                cid.set("contrib-id-type", "orcid")
                oid = au["orcid"]
                cid.text = oid if oid.startswith("http") else "https://orcid.org/" + oid
            name = etree.SubElement(contrib, "name")
            etree.SubElement(name, "surname").text = sur
            giv = (au.get("given") or "").strip()
            if giv:
                etree.SubElement(name, "given-names").text = giv
            for atext in au.get("affs") or []:
                atext = (atext or "").strip()
                if not atext:
                    continue
                if atext not in aff_index:
                    ai += 1
                    aff_index[atext] = f"aff{ai}"
                x = etree.SubElement(contrib, "xref")
                x.set("ref-type", "aff")
                x.set("rid", aff_index[atext])

    for atext, aid2 in aff_index.items():
        a = etree.SubElement(am, "aff")
        a.set("id", aid2)
        a.text = atext

    # permissions BEFORE abstract (JATS article-meta content order). Licence ONLY from
    # the authoritative source the caller passes (the publisher's PDF), never from TEI,
    # never faked. `license_url` may be a canonical CC URL OR a prose statement the
    # publisher printed when it gave no versioned URL.
    if license_url:
        perm = etree.SubElement(am, "permissions")
        if license_url.lower().startswith("http"):
            uri = license_url.replace("http://", "https://")
            flavour = "CC-BY"
            m = re.search(r"/licenses/([a-z-]+)/", uri)
            if m:
                flavour = "CC-" + m.group(1).upper()
            lic = etree.SubElement(perm, "license")
            lic.set("license-type", "creative-commons")
            lic.set("{%s}href" % XLINK, uri)
            etree.SubElement(lic, "license-p").text = (
                f"This is an open access article distributed under the terms of the Creative "
                f"Commons {flavour} licence ({uri}).")
        else:                                    # prose statement (no versioned URL stated)
            lic = etree.SubElement(perm, "license")
            lic.set("license-type", "open-access")
            etree.SubElement(lic, "license-p").text = license_url

    ab = first(root, '//t:profileDesc/t:abstract')
    if ab is not None:
        jab = etree.SubElement(am, "abstract")
        ps = all_(ab, './/t:p')
        if ps:
            for p in ps:
                jab.append(conv_p(p))
        else:
            etree.SubElement(jab, "p").text = txt(ab)

    # funding: article-meta funding-group (after abstract, per JATS content order); one
    # funding-statement per prose paragraph, inline refs preserved.
    n_fund = 0
    fund_divs = [d for d in all_(root, '//t:text/t:back/t:div[@type="funding"]') if txt(d)]
    if fund_divs:
        fg = etree.SubElement(am, "funding-group")
        for d in fund_divs:
            for para in _back_paras(d):
                fs = etree.SubElement(fg, "funding-statement")
                fs.text = para.text
                for c in list(para):
                    fs.append(c)
                n_fund += 1

    # body: sections, then figures/tables in a trailing float section
    body = etree.SubElement(art, "body")
    si = 0
    for div in all_(root, '//t:text/t:body/t:div'):
        si += 1
        body.append(conv_section(div, rule, si))
    figs = all_(root, '//t:text/t:body//t:figure')
    if figs:
        host = etree.SubElement(body, "sec")
        host.set("id", "sec-floats")          # every <sec> needs an @id (house rule)
        etree.SubElement(host, "title").text = "Figures and tables"
        fi = ti = 0
        for f in figs:
            if f.get("type") == "table":
                ti += 1
                host.append(conv_figure(f, ti, is_table=True))
            else:
                fi += 1
                host.append(conv_figure(f, fi))

    # back: acknowledgements, data availability, appendices, then references
    ack_divs = [d for d in all_(root, '//t:text/t:back/t:div[@type="acknowledgement"]') if txt(d)]
    avail_divs = [d for d in all_(root, '//t:text/t:back/t:div[@type="availability"]') if txt(d)]
    # An inner annex div starts a NEW appendix only when its head is a real heading
    # (contains a word of 3+ letters); GROBID's mis-split fragments (a lone 'E', an
    # equation tag '(C60)') fold into the previous appendix as content instead.
    annex_units = []
    for d in all_(root, '//t:text/t:back/t:div[@type="annex"]'):
        inner = [dv for dv in all_(d, "./t:div") if txt(dv)]
        for dv in (inner or ([d] if txt(d) else [])):
            h = first(dv, "./t:head")
            real_head = h is not None and re.search(r"[A-Za-z]{3,}", txt(h))
            if real_head or not annex_units:
                annex_units.append([dv])
            else:
                annex_units[-1].append(dv)
    bibls = all_(root, '//t:listBibl/t:biblStruct')

    n_ack = n_avail = n_app = 0
    if ack_divs or avail_divs or annex_units or bibls:
        back = etree.SubElement(art, "back")
        for d in ack_divs:
            ack = etree.SubElement(back, "ack")
            etree.SubElement(ack, "title").text = _back_title(d, "Acknowledgements")
            for para in _back_paras(d):
                ack.append(para)
            n_ack += 1
        for i, d in enumerate(avail_divs, 1):
            sec = etree.SubElement(back, "sec")
            sec.set("sec-type", "data-availability")
            sec.set("id", "sec-data-availability" if i == 1 else f"sec-data-availability{i}")
            etree.SubElement(sec, "title").text = _back_title(d, "Data availability")
            for para in _back_paras(d):
                sec.append(para)
            n_avail += 1
        if annex_units:
            ag = etree.SubElement(back, "app-group")
            for i, unit in enumerate(annex_units, 1):
                app = etree.SubElement(ag, "app")
                app.set("id", f"app{i}")
                h = first(unit[0], "./t:head")
                etree.SubElement(app, "title").text = (txt(h) if h is not None else "") or f"Appendix {i}"
                _app_fill(app, unit[0])
                for extra in unit[1:]:               # folded fragments: head rides as bold
                    hx = first(extra, "./t:head")
                    if hx is not None and txt(hx):
                        p = etree.SubElement(app, "p")
                        etree.SubElement(p, "bold").text = txt(hx)
                    _app_fill(app, extra)
                n_app += 1
        if bibls:
            rl = etree.SubElement(back, "ref-list")
            etree.SubElement(rl, "title").text = "References"
            for i, b in enumerate(bibls, 1):
                rl.append(conv_reference(b, i, rule.reference_style))

    stats = postprocess(art, rule)
    stats.update({"funding": n_fund, "ack": n_ack, "availability": n_avail, "apps": n_app})
    return art, rule, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="GROBID TEI xml")
    ap.add_argument("-o", "--out", required=True, help="output generic-JATS path")
    ap.add_argument("--journal", default=None, help="authoritative journal title (works.journal)")
    ap.add_argument("--license", default=None, help="CC licence URL from OpenAlex metadata")
    ap.add_argument("--publisher", default=None, help="OpenAlex publisher string (selects rules)")
    ap.add_argument("--title", default=None,
                    help="authoritative article title (works.title) — used only when the TEI header has none")
    ap.add_argument("--authors", default=None,
                    help='authoritative authors as JSON [{"surname","given","orcid","affs":[...]}] '
                         "(OpenAlex authorships) — used ONLY when GROBID recovered no authors")
    args = ap.parse_args()
    authors = json.loads(args.authors) if args.authors else None
    art, rule, stats = build(args.src, journal=args.journal, license_url=args.license,
                             publisher=args.publisher, title=args.title, authors=authors)
    etree.cleanup_namespaces(art)
    body = etree.tostring(art, encoding="unicode")
    doc = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE article PUBLIC "%s"\n         "%s">\n%s\n'
           % (JATS, DTD, body))
    open(args.out, "w", encoding="utf-8").write(doc)
    n = lambda t: len(list(art.iter(t)))
    print("wrote %s [rules=%s refs=%s] (secs=%d figs=%d tables=%d refs=%d contribs=%d) "
          "back{fund=%d ack=%d avail=%d apps=%d} relinked{fig=%d bibr=%d} unwrapped=%d"
          % (args.out, rule.slug, rule.reference_style,
             n("sec"), n("fig"), n("table-wrap"), n("ref"), n("contrib"),
             stats["funding"], stats["ack"], stats["availability"], stats["apps"],
             stats["fig_relinked"], stats["bibr_relinked"], stats["unwrapped"]))


if __name__ == "__main__":
    main()
