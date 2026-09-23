#!/usr/bin/env python3
r"""Convert raw LaTeX left in BODY prose into proper JATS — for the scoap3_jhep
(and any repo_pdf) route, whose A++ BodyRef full-text embeds the author's LaTeX in
the text nodes instead of marking it up.

Two structural conversions plus a cleanup, all inside prose containers (<p>, <title>,
list items, table cells …), never touching existing <inline-formula>/<math>/<tex-math>:

  * \cite{bibitem003,bibitem004}  ->  [<xref ref-type="bibr" rid="bibitem003">3</xref>,
                                       <xref ref-type="bibr" rid="bibitem004">4</xref>]
    The JHEP reference list already carries bibitemNNN ids, so the mapping is exact;
    the visible number is NNN (refs are numbered in order).
  * $m_H$ / $$…$$ / \[…\] / \begin{equation}…\end{equation}
        ->  <inline-formula>/<disp-formula><tex-math>…</tex-math></…>
    render_article.py extracts the tex-math and emits \(…\)/\[…\] for MathJax. Custom
    author macros MathJax can't know (\GeV, \mX …) are pre-expanded from the shared
    macro table; standard LaTeX (\alpha, \frac …) is left for MathJax.
  * the remaining prose runs (between the maths and cites) are text-normalised with the
    caption cleaner (escapes, ~, \label/\ref, stray \commands) so nothing raw survives.

`residual_latex()` reports anything the conversion couldn't reach, so ingest can flag a
package rather than ship raw LaTeX as clean (the failure mode this route had).
"""
import os
import re
import sys

from lxml import etree

# latex_caption_clean lives one level up (MORE-harvest/); reuse its symbol/escape logic
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from latex_caption_clean import clean_text, MACRO  # noqa: E402

# prose containers whose text runs we rewrite; we recurse but never descend into maths
PROSE = {"p", "title", "td", "th", "list-item", "def", "term", "label",
         "bold", "italic", "sup", "sub", "sc", "monospace", "underline", "named-content"}
SKIP = {"inline-formula", "disp-formula", "tex-math", "math", "mml:math",
        "xref", "ext-link", "graphic", "inline-graphic"}

# one scanner, display/environment forms BEFORE inline so `$$` never reads as two `$`
_TOKEN = re.compile(r"""
    (?P<env>\\begin\{(?P<envname>equation|align|gather|eqnarray|multline|displaymath)\*?\}
            (?P<envbody>.*?)\\end\{(?P=envname)\*?\})
  | (?P<ddollar>(?<!\\)\$\$(?P<ddbody>.+?)(?<!\\)\$\$)
  | (?P<dbracket>\\\[(?P<dbbody>.+?)\\\])
  | (?P<idollar>(?<!\\)\$(?P<idbody>.+?)(?<!\\)\$)
  | (?P<iparen>\\\((?P<ipbody>.+?)\\\))
  | (?P<cite>\\cite[tp]?\*?\s*\{(?P<keys>[^{}]*)\})
""", re.S | re.X)


def ln(el):
    t = el.tag
    return "" if not isinstance(t, str) else t.rsplit("}", 1)[-1]


def _expand_math_macros(expr):
    """Expand the custom author macros MathJax has no preamble for; leave the rest."""
    for k in sorted(MACRO, key=len, reverse=True):
        expr = re.sub(re.escape(k) + r"(?![a-zA-Z])", MACRO[k], expr)
    return expr.strip()


def _ref_number(key):
    """bibitem003 -> '3' (refs are numbered in order); fall back to the raw key."""
    m = re.search(r"(\d+)\s*$", key)
    return str(int(m.group(1))) if m else key


def _formula(expr, block, ref_ids):
    tag = "disp-formula" if block else "inline-formula"
    el = etree.Element(tag)
    tm = etree.SubElement(el, "tex-math")
    tm.text = _expand_math_macros(expr)
    return el


def _cite(keys, ref_ids):
    """A [<xref>…</xref>, …] group. Returns (list_of_nodes) — brackets as bare strings,
    each key an <xref> when the ref exists (else its number as plain text)."""
    parts = [k.strip() for k in keys.split(",") if k.strip()]
    nodes = ["["]
    for i, key in enumerate(parts):
        if i:
            nodes.append(", ")
        num = _ref_number(key)
        if key in ref_ids:
            x = etree.Element("xref")
            x.set("ref-type", "bibr")
            x.set("rid", key)
            x.text = num
            nodes.append(x)
        else:
            nodes.append(num)
    nodes.append("]")
    return nodes


def _tokenize(s, ref_ids):
    """A text run -> a flat list of str | Element (xref / formula)."""
    if not s or ("$" not in s and "\\" not in s):
        return [clean_text(s)] if s else []
    out = []
    last = 0
    for m in _TOKEN.finditer(s):
        if m.start() > last:
            out.append(clean_text(s[last:m.start()]))
        if m.group("env") is not None:
            out.append(_formula(m.group("envbody"), True, ref_ids))
        elif m.group("ddollar") is not None:
            out.append(_formula(m.group("ddbody"), True, ref_ids))
        elif m.group("dbracket") is not None:
            out.append(_formula(m.group("dbbody"), True, ref_ids))
        elif m.group("idollar") is not None:
            out.append(_formula(m.group("idbody"), False, ref_ids))
        elif m.group("iparen") is not None:
            out.append(_formula(m.group("ipbody"), False, ref_ids))
        elif m.group("cite") is not None:
            out.extend(_cite(m.group("keys"), ref_ids))
        last = m.end()
    if last < len(s):
        out.append(clean_text(s[last:]))
    return out


def _rebuild(el, ref_ids):
    """Rewrite el's DIRECT content (its text + each child's tail) into mixed content,
    inserting the new xref/formula elements. Existing children are kept in order."""
    orig_text = el.text
    kids = list(el)
    tails = [k.tail for k in kids]
    el.text = None
    for k in kids:
        el.remove(k)
        k.tail = None
    nodes = _tokenize(orig_text, ref_ids)
    for k, t in zip(kids, tails):
        nodes.append(k)
        nodes.extend(_tokenize(t, ref_ids))
    last_el = None
    for n in nodes:
        if isinstance(n, str):
            if last_el is None:
                el.text = (el.text or "") + n
            else:
                last_el.tail = (last_el.tail or "") + n
        else:
            el.append(n)
            last_el = n


def _walk(el, ref_ids):
    if ln(el) in SKIP:
        return
    for c in list(el):
        _walk(c, ref_ids)
    # rewrite only where prose LaTeX can live (avoid front/back metadata churn)
    if ln(el) in PROSE:
        _rebuild(el, ref_ids)


JATS = "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD with MathML3 v1.4 20241031//EN"
DTD = "https://jats.nlm.nih.gov/archiving/1.4/JATS-archivearticle1-4-mathml3.dtd"


def convert_file(path, dry_run=False):
    """Convert body LaTeX in article.xml. Returns (n_cites, n_formulae, residual)."""
    parser = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.parse(path, parser).getroot()
    ref_ids = {r.get("id") for r in root.iter("{*}ref") if r.get("id")}
    body = root.find(".//{*}body")
    if body is None:
        return (0, 0, 0)
    _walk(body, ref_ids)
    # FRONT matter (article-title, abstract): LaTeX here becomes readable UNICODE, not
    # formulas — titles flow into tab names, listings and search, where MathJax can't
    # run. Skips existing maths subtrees; a no-op on text without LaTeX.
    front = root.find(".//{*}front")
    if front is not None:
        _normalize_front(front)
    n_cites = len(root.findall(".//{*}xref[@ref-type='bibr']"))
    n_form = len(root.findall(".//{*}inline-formula")) + len(root.findall(".//{*}disp-formula"))
    resid = residual_latex(root)
    if not dry_run:
        etree.cleanup_namespaces(root, keep_ns_prefixes=("mml", "xlink"))
        out = etree.tostring(root, encoding="unicode")
        doc = ('<?xml version="1.0" encoding="utf-8"?>\n'
               '<!DOCTYPE article PUBLIC "%s"\n         "%s">\n%s\n' % (JATS, DTD, out))
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)
    return (n_cites, n_form, resid)


# a formula's whole subtree is legitimate math — never counted as residual (PMC/publisher
# tex-math wraps the expression as "\begin{document}$$…$$\end{document}", which is proper)
_FORMULA_SUBTREE = {"inline-formula", "disp-formula", "tex-math", "math", "alternatives"}


def _normalize_front(front):
    """Unicode-normalise LaTeX in front-matter text runs, skipping maths subtrees."""
    def walk(el):
        if not isinstance(el.tag, str) or ln(el) in _FORMULA_SUBTREE or ln(el).endswith("math"):
            return
        if el.text and ("\\" in el.text or "$" in el.text):
            el.text = clean_text(el.text)
        for c in el:
            walk(c)
            if c.tail and ("\\" in c.tail or "$" in c.tail):
                c.tail = clean_text(c.tail)
    walk(front)


def residual_latex(root):
    """CONVERTIBLE LaTeX still in body PROSE — the honest failure signal. Skips whole
    formula subtrees (already-marked-up maths) and comments; a lone `$` (currency, a gene
    name) has no closing partner so it never matches, and must not flag a clean paper."""
    body = root.find(".//{*}body")
    if body is None:
        return 0
    n = 0

    def walk(el):
        nonlocal n
        if not isinstance(el.tag, str):          # comment / PI
            return
        name = ln(el)
        if name in _FORMULA_SUBTREE or name.endswith("math"):
            return                               # do not descend into maths at all
        if el.text:
            n += len(_TOKEN.findall(el.text))
        for c in el:
            walk(c)
            if c.tail:
                n += len(_TOKEN.findall(c.tail))

    walk(body)
    return n


def main():
    import argparse
    import os
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="article.xml path(s)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for p in args.paths:
        if not os.path.isfile(p):
            print(f"  {p}: not found")
            continue
        c, fo, r = convert_file(p, dry_run=args.dry_run)
        print(f"  {p}: {'would link' if args.dry_run else 'linked'} {c} citation(s), "
              f"{fo} formula(e), residual raw-LaTeX markers: {r}")


if __name__ == "__main__":
    main()
