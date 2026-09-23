#!/usr/bin/env python3
"""
jats_house_lint.py — DETERMINISTIC conformance gate for the MORE house JATS spec.

validate_jats.py answers "is it well-formed JATS + (when the DTD is vendored) DTD-valid".
This script answers the *next* question, deterministically: "does it follow OUR house
conventions in MORE_XML_Authoring_Guide.md" — the mechanizable subset of them. It is the
deterministic floor under the interpretive `jats-conform` subagent: anything that can be
checked by rule lives here (blocking, reproducible, re-runnable on ingest); only genuine
judgement calls are left to the agent.

Errors block (exit 1). Warnings never block (exit 0) but are reported for the human/agent.

Usage:
    python scripts/jats_house_lint.py outputs/MORE-YYYY-NNNNNN
    python scripts/jats_house_lint.py outputs/MORE-YYYY-NNNNNN/article.xml
    python scripts/jats_house_lint.py --json outputs/MORE-YYYY-NNNNNN   # machine-readable
Exit: 0 = no errors (warnings allowed), 1 = errors, 2 = usage/parse error.
"""
import argparse, datetime, json, os, re, sys
import xml.etree.ElementTree as ET

# One shared home for the house hyphenation rule (also drives the PDF de-hyphenation pass);
# used here only to SCOPE the consistency warning to compounds we would keep hyphenated.
try:
    from more_tokens import is_lexical_compound
except Exception:                       # keep the linter runnable even if the helper is absent
    def is_lexical_compound(left, right):   # pragma: no cover
        return True

XLINK = "http://www.w3.org/1999/xlink"
MID_RE   = re.compile(r"^MORE-\d{4}-\d{6}$")
# accept zero-padded (g001, guide example) and short (g1) + supplementary (gs1) forms
FIG_RE   = re.compile(r"^more\.\d{4}\.\d{6}\.g[s]?\d{1,3}$")
TBL_RE   = re.compile(r"^more\.\d{4}\.\d{6}\.t[s]?\d{1,3}$")
# sec-type vocabulary the guide uses (plus common JATS values); outside this = warning only
SEC_TYPES = {
    "intro", "materials|methods", "methods", "materials", "results", "discussion",
    "conclusions", "supplementary-material", "cases", "subjects", "abbreviations",
    "background", "appendix",
}
XREF_TYPES = {"aff", "corresp", "bibr", "fn", "fig", "table", "disp-formula",
              "boxed-text", "sec", "app", "table-fn", "author-notes"}
# external-URI prefixes (shared by the local-file resolve checks and the href-hygiene loop)
EXT_SCHEMES = ("http://", "https://", "ftp://", "ftps://", "sftp://", "www.", "ftp.")

ANZSRC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "anzsrc_2020.json")
ANZSRC_LOAD_ERROR = None
try:
    ANZSRC = json.load(open(ANZSRC_PATH, encoding="utf-8"))   # {for,seo,toa: {code:label}, coverage}
except FileNotFoundError:
    ANZSRC = None                          # not vendored — code/label validation is best-effort
except Exception as e:
    ANZSRC = None                          # vendored but BROKEN — must be surfaced, not swallowed
    ANZSRC_LOAD_ERROR = str(e)[:120]

def ln(tag):  # local name
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

def xa(el, name):  # xlink-namespaced attribute by local name
    return el.get(f"{{{XLINK}}}{name}") or el.get("xlink:" + name) or el.get(name)

def resolve_xml(path):
    if os.path.isdir(path):
        c = os.path.join(path, "article.xml")
        if os.path.isfile(c):
            return c
        xs = [f for f in os.listdir(path) if f.endswith(".xml")]
        if len(xs) == 1:
            return os.path.join(path, xs[0])
        raise FileNotFoundError(f"{path}: no clear article.xml")
    return path

def lint(xml_path, pkg_dir):
    errors, warnings = [], []
    def err(msg): errors.append(msg)
    def warn(msg): warnings.append(msg)

    raw = open(xml_path, encoding="utf-8").read()
    raw_nodoc = re.sub(r"<!DOCTYPE(?:[^>\[]|\[[^\]]*\])*>", "", raw, flags=re.S)
    try:
        root = ET.fromstring(raw_nodoc)
    except ET.ParseError as e:
        return [f"not well-formed: {e}"], []

    # gather elements by local name
    by = {}
    for el in root.iter():
        by.setdefault(ln(el.tag), []).append(el)

    # ---- root attributes ----
    if ln(root.tag) != "article":
        err(f"root is <{ln(root.tag)}>, expected <article>")
    for a, want in (("article-type", None), ("dtd-version", "1.4")):
        v = root.get(a)
        if not v:
            err(f"<article> missing @{a}")
        elif want and v != want:
            err(f"<article> @{a} = '{v}', expected '{want}'")
    if not (root.get("{http://www.w3.org/XML/1998/namespace}lang") or root.get("xml:lang")):
        warn("<article> has no xml:lang (guide defaults to 'en')")

    # ---- DOCTYPE / namespaces (string-level, since ET drops them) ----
    if "JATS-archivearticle1-4" not in raw:
        warn("DOCTYPE does not reference the JATS 1.4 archiving DTD")
    if 'xmlns:xlink' not in raw:
        err("missing xmlns:xlink namespace declaration")
    if 'xmlns:mml' not in raw:
        warn("missing xmlns:mml (MathML) namespace declaration")

    # ---- skeleton ----
    if not by.get("front"): err("missing <front>")
    if not by.get("article-meta"): err("missing <article-meta>")
    if not by.get("body"): warn("no <body> (only acceptable for a metadata-only record)")
    # Scope the title to front/article-meta/title-group — an <article-title> inside a reference
    # citation must not satisfy this (and itertext() so a title with inline markup still counts).
    real_title = ""
    for am in (e for e in root.iter() if ln(e.tag) == "article-meta"):
        for tg in (e for e in am.iter() if ln(e.tag) == "title-group"):
            for at in (e for e in tg.iter() if ln(e.tag) == "article-title"):
                real_title = "".join(at.itertext()).strip() or real_title
    if not real_title:
        err("missing or empty <article-title> in front/article-meta/title-group")

    # ---- manuscript-id + folder match ----
    folder = os.path.basename(os.path.abspath(pkg_dir).rstrip("/\\")) if pkg_dir else None
    mids = [e for e in by.get("article-id", []) if e.get("pub-id-type") == "manuscript-id"]
    if not mids:
        err("no <article-id pub-id-type='manuscript-id'> (MORE id is required)")
    else:
        mid = (mids[0].text or "").strip()
        if not MID_RE.match(mid):
            err(f"manuscript-id '{mid}' does not match MORE-YYYY-NNNNNN")
        elif folder and folder.startswith("MORE-") and mid != folder:
            err(f"manuscript-id '{mid}' != package folder '{folder}'")

    # ---- authors / affiliations ----
    authors = [c for g in by.get("contrib-group", []) for c in g.findall("contrib")
               if c.get("contrib-type") == "author"]
    # fall back: any contrib with contrib-type author anywhere
    if not authors:
        authors = [c for c in by.get("contrib", []) if c.get("contrib-type") == "author"]
    if not authors:
        err("no <contrib contrib-type='author'>")
    for i, c in enumerate(authors, 1):
        name = c.find("name")
        collab = c.find("collab")
        if name is None and collab is None:
            err(f"author #{i} has neither <name> nor <collab>")
        elif name is not None:
            sur = name.find("surname")
            if sur is None or not (sur.text and sur.text.strip()):
                err(f"author #{i} <name> missing <surname>")
    if not any(c.get("corresp") == "yes" or c.find("xref[@ref-type='corresp']") is not None
               for c in authors):
        warn("no corresponding author marked (corresp='yes' or an <xref ref-type='corresp'>)")
    if not by.get("aff"):
        warn("no <aff> affiliation element")
    for aff in by.get("aff", []):
        if not aff.get("id"):
            err("an <aff> has no @id (cannot be cross-referenced)")

    # ---- permissions / rights (Rights Retention Policy) ----
    lic = by.get("license", [])
    if not lic:
        err("no <license> in <permissions> (rights statement required)")
    else:
        for L in lic:
            lt = L.get("license-type")
            href = xa(L, "href") or ""
            is_cc_href = "creativecommons.org" in href
            if lt != "creative-commons":
                warn(f"<license license-type='{lt}'> — guide uses 'creative-commons'")
            if not is_cc_href:
                warn("<license> @xlink:href does not point to a creativecommons.org licence URI")
            # Neither signal present = the rights statement is wrong for a Rights-Retention AAM. This
            # is the whole point of the Green-OA deposit, so block rather than merely warn.
            if lt != "creative-commons" and not is_cc_href:
                err("<license> is neither creative-commons typed nor a creativecommons.org URI "
                    "— rights statement appears wrong for a Rights-Retention AAM")
        whole = "".join(root.itertext())
        if "Rights Retention" not in whole:
            warn("licence text does not mention the (Manchester) Rights Retention Policy")
        # Published-only policy: every package has a published VoR, so the RRP licence-p that
        # references it must carry the publisher's copyright note. The guide's template reads
        # "...The published version of record (© the publisher) is available at: <DOI>". A
        # licence that names the version of record but drops "(© the publisher)" has an
        # incomplete rights statement (the VoR's publisher copyright is unattributed).
        lic_text = " ".join("".join(L.itertext()) for L in lic)
        lic_low = lic_text.lower()
        if "version of record" in lic_low and \
           "© the publisher" not in lic_text and "(c) the publisher" not in lic_low:
            warn('licence references the version of record but omits the publisher copyright '
                 'note "(© the publisher)" (guide Rights-Retention template)')
    if not by.get("copyright-holder"):
        warn("no <copyright-holder> in <permissions>")

    # ---- abstract (required for substantive article types; optional for editorial/letter/etc.) ----
    ABSTRACT_OPTIONAL = {"editorial", "correction", "retraction", "letter", "reply", "discussion",
                         "in-brief", "book-review", "news", "obituary", "article-commentary", "other"}
    if not by.get("abstract"):
        at = root.get("article-type", "")
        if at in ABSTRACT_OPTIONAL:
            warn(f"no <abstract> (acceptable for article-type='{at}')")
        else:
            err(f"no <abstract> (required for article-type='{at or 'research-article'}')")

    # ---- ANZSRC classification (DTD-valid <compound-subject> code+label) ----
    # legacy guard: <subject code="..."> is NOT DTD-valid (the DTD declares no @code on <subject>)
    for sj in by.get("subject", []):
        if sj.get("code"):
            err(f"<subject code='{sj.get('code')}'> is not DTD-valid — use "
                "<compound-subject><compound-subject-part content-type='code'>…</> (see authoring guide)")
    def _part(node, ct):
        cs = node.find("compound-subject")
        if cs is not None:
            for part in cs.findall("compound-subject-part"):
                if part.get("content-type") == ct:
                    return (part.text or "").strip()
        sj = node.find("subject")
        if sj is not None:
            return (sj.get("code") or "").strip() if ct == "code" else (sj.text or "").strip()
        return ""
    def node_code(node):  return _part(node, "code")
    def node_label(node): return _part(node, "text")
    tbl = ANZSRC or {}
    cov = tbl.get("coverage", "none")
    if ANZSRC_LOAD_ERROR:
        warn("ANZSRC 2020 table is present but UNREADABLE (%s) — code/label validation was SKIPPED; "
             "rebuild scripts/data/anzsrc_2020.json" % ANZSRC_LOAD_ERROR)
    def check_scheme(group, scheme, expect):
        codes_tbl = tbl.get(scheme, {})
        def walk(node, depth=0, parent=None):
            code, label = node_code(node), node_label(node)
            if code:
                if not code.isdigit():
                    warn(f"anzsrc-{scheme} code '{code}' is not numeric")
                if codes_tbl and code in codes_tbl:
                    off = codes_tbl[code]
                    if label and label.strip().lower() != off.strip().lower():
                        warn(f"anzsrc-{scheme} {code}: label '{label}' != official '{off}'")
                elif codes_tbl and cov == "full":
                    warn(f"anzsrc-{scheme} code '{code}' is not a valid ANZSRC 2020 {scheme.upper()} code")
                if parent and not code.startswith(parent):
                    err(f"anzsrc-{scheme} nesting: '{code}' does not extend parent '{parent}'")
                exp = expect.get(depth)
                if exp and len(code) != exp:
                    warn(f"anzsrc-{scheme} code '{code}' is {len(code)} digits, expected {exp} at this level")
            for sg in node.findall("subj-group"):
                walk(sg, depth + 1, code or parent)
        walk(group)
    cats = by.get("article-categories", [])
    if not cats:
        err("no <article-categories> (ANZSRC classification required)")
    else:
        groups = cats[0].findall("subj-group")
        if not any(g.get("subj-group-type") == "heading" for g in groups):
            warn("no <subj-group subj-group-type='heading'> (e.g. 'Research Article')")
        fors = [g for g in groups if g.get("subj-group-type") == "anzsrc-for"]
        if not fors:
            err("no <subj-group subj-group-type='anzsrc-for'> (Fields of Research required)")
        for g in fors:
            check_scheme(g, "for", {0: 2, 1: 4, 2: 6})
            deepest = g; d = 0
            while deepest.find("subj-group") is not None:
                deepest = deepest.find("subj-group"); d += 1
            if d < 2:
                warn("anzsrc-for is not nested to a 6-digit Field (division>group>field); only "
                     f"{d+1} level(s) present")
        for g in [x for x in groups if x.get("subj-group-type") == "anzsrc-seo"]:
            check_scheme(g, "seo", {0: 2, 1: 4, 2: 6})
        for g in [x for x in groups if x.get("subj-group-type") == "anzsrc-toa"]:
            check_scheme(g, "toa", {0: 1})

    # ---- figures / tables: MORE id pattern + caption ----
    for f in by.get("fig", []):
        fid = f.get("id") or ""
        if not fid:
            err("a <fig> has no @id")
        elif not FIG_RE.match(fid):
            warn(f"<fig id='{fid}'> not in house form more.YYYY.NNNNNN.g001 (naming convention)")
        if f.find("label") is None:
            warn(f"<fig id='{fid}'> has no <label>")
        # descendant search, not direct children: a <fig> whose graphic sits inside
        # <alternatives> (the house equation pattern applied to a figure) is valid
        if not any(ln(g.tag) == "graphic" for g in f.iter()):
            err(f"<fig id='{fid}'> has no <graphic> (deposited image required)")
    # A <fig-group> must carry at least one deposited image somewhere inside it. A
    # caption-only <fig-group> (labels/captions but no <fig>/<graphic>) is the scoap3_jhep
    # orphan class: the per-<fig> rule above misses it because there are no <fig> children
    # to check, so the package would otherwise pass silently green.
    for fg in by.get("fig-group", []):
        if not any(ln(g.tag) == "graphic" for g in fg.iter()):
            fgid = fg.get("id") or "(no id)"
            err(f"<fig-group id='{fgid}'> has no <graphic> anywhere "
                "(caption-only figure group; deposited image required)")
    for t in by.get("table-wrap", []):
        tid = t.get("id") or ""
        if not TBL_RE.match(tid):
            warn(f"<table-wrap id='{tid}'> does not match more.YYYY.NNNNNN.tNNN")

    # ---- graphics resolve on disk (case-EXACT: the in-house platform ingests on a case-sensitive
    # filesystem, so "Fig1.PNG" must not pass just because Windows opened fig1.png) ----
    if pkg_dir:
        pkg_real = os.path.realpath(pkg_dir)

        def _inside_package(full):
            # containment: "../other-pkg/assets/fig1.png" or an absolute path may resolve on
            # the workstation, but the file is NOT in the shipped package — escaping is as
            # broken as missing
            rp = os.path.realpath(full)
            return rp == pkg_real or rp.startswith(pkg_real + os.sep)

        def _resolves_exact(href):
            full = os.path.join(pkg_dir, href)
            if not _inside_package(full):
                return False
            if not os.path.isfile(full):
                return False
            d, base = os.path.split(full)
            try:
                return base in os.listdir(d)     # filename case must match the real on-disk name
            except OSError:
                return False
        for gph in by.get("graphic", []) + by.get("inline-graphic", []):
            tagname = ln(gph.tag)
            href = xa(gph, "href")
            if not href:
                err(f"a <{tagname}> has no @xlink:href (deposited image reference required)")
            elif not _resolves_exact(href):
                err(f"<{tagname}> href does not resolve (case-exact, inside the package) "
                    f"to a file: '{href}'")

        # ---- other LOCAL package files referenced by href must also ship in the package ----
        # <supplementary-material>/<media>/<self-uri> with a relative href were previously
        # never resolved on disk, so a missing supplementary file shipped silently green.
        # External links (http/https/ftp/doi...) are out of scope here — the href-hygiene
        # loop below owns scheme checks.
        LOCAL_HREF_TAGS = ("media", "supplementary-material",
                           "inline-supplementary-material", "self-uri")
        for tag in LOCAL_HREF_TAGS:
            for el in by.get(tag, []):
                href = xa(el, "href")
                if not href or not href.strip():
                    continue
                h = href.strip()
                if h.lower().startswith(EXT_SCHEMES) or h.startswith("#") or ":" in h.split("/")[0]:
                    continue                     # external URI / scheme'd — not a package file
                if not _resolves_exact(h):
                    err(f"<{tag}> href references a local package file that does not resolve "
                        f"(case-exact, inside the package): '{h}'")

    # ---- references ----
    reflist = by.get("ref-list", [])
    refs = by.get("ref", [])
    if not reflist:
        warn("no <ref-list> (acceptable only if the paper truly has no references)")
    for r in refs:
        if not r.get("id"):
            err("a <ref> has no @id")
    if refs:
        kinds = {("element-citation" if r.find("element-citation") is not None else
                  "mixed-citation" if r.find("mixed-citation") is not None else "other")
                 for r in refs}
        # House standard is <mixed-citation> (Reference List Architecture in the authoring guide):
        # it preserves the source text verbatim, which matters for AAM fidelity. <element-citation>
        # is also DTD-valid and accepted. Only flag a ref that is NEITHER (i.e. malformed/untagged).
        if "other" in kinds:
            warn("a <ref> uses neither <mixed-citation> nor <element-citation>; the MORE house "
                 "standard is <mixed-citation> (see the Reference List Architecture section of the guide)")
        # in-text linking
        if refs and not any((x.get("ref-type") == "bibr") for x in by.get("xref", [])):
            warn("no in-text <xref ref-type='bibr'> citation links to the reference list")

    # ---- sec-type vocabulary + xref types ----
    for s in by.get("sec", []):
        st = s.get("sec-type")
        if st and st not in SEC_TYPES:
            warn(f"<sec sec-type='{st}'> outside the house vocabulary (interpretive — confirm)")
        if not s.get("id"):
            warn("a <sec> has no @id")
    for x in by.get("xref", []):
        rt = x.get("ref-type")
        if rt and rt not in XREF_TYPES:
            warn(f"<xref ref-type='{rt}'> is an unusual ref-type")

    # ================= StyleChecker-derived rules (NLM nlm-style-5.48 diff, 2026-07-04) ========
    # Re-implemented ideas (never their XSL) from PMC's public StyleChecker — each rule below is
    # a defect class PMC saw often enough in 20 years of vendor manuscript conversion to automate.
    # Severities follow PMC's error/warning split except where the house "retain all source
    # formatting" principle demands a downgrade (noted inline).

    parent_of = {c: p for p in root.iter() for c in p}

    # ---- dates: real calendar values (day 1-31, month 1-12, day needs month, leap years) ----
    for el in root.iter():
        kids = {ln(c.tag): (c.text or "").strip() for c in el}
        if not ({"day", "month", "year"} & set(kids)):
            continue
        where = ln(el.tag)
        d, m, y = kids.get("day"), kids.get("month"), kids.get("year")
        if d is not None:
            if not d.isdigit() or not (1 <= int(d) <= 31):
                err(f"<{where}> day '{d}' is not a number between 1 and 31")
            if m is None:
                err(f"<{where}> has a <day> but no <month> (a date with a day needs a month)")
        if m is not None and m.isdigit() and not (1 <= int(m) <= 12):
            err(f"<{where}> month '{m}' is not between 1 and 12")
        if d and m and y and d.isdigit() and m.isdigit() and y.isdigit() \
                and 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            try:
                datetime.date(int(y), int(m), int(d))
            except ValueError:
                err(f"<{where}> {y}-{m}-{d} is not a valid calendar date")
    for cy in by.get("copyright-year", []):
        v = (cy.text or "").strip()
        if not re.fullmatch(r"(19|20)\d{2}", v):
            err(f"<copyright-year> '{v}' is not a valid year")

    # ---- MathML quality (the agent-recovered-MathML surface: PDF equation crops) ----
    MML_DEPRECATED = {"fontsize", "fontweight", "fontstyle", "fontfamily", "color"}
    for math in by.get("math", []):        # mml:math — 'math' has no other JATS local name
        for el in math.iter():
            bad = MML_DEPRECATED & {a.rsplit("}", 1)[-1] for a in el.attrib}
            if bad:
                err(f"mml:{ln(el.tag)} uses deprecated MathML attribute(s) {sorted(bad)} "
                    "— use mathvariant/mathsize/mathcolor")
            children = list(el)
            for a, b in zip(children, children[1:]):
                if ln(a.tag) == ln(b.tag) == "mn":
                    warn("mml:mn directly follows mml:mn — split digits? a complete number "
                         "must be one <mml:mn> (classic machine-MathML defect)")
                    break
            for a, b in zip(children, children[1:]):
                if ln(a.tag) == ln(b.tag) == "mtext":
                    warn("mml:mtext directly follows mml:mtext — should be one <mml:mtext> "
                         "holding the complete word/phrase")
                    break
            if ln(el.tag) in ("msub", "msup", "msubsup"):
                for part in el:
                    if len(part) == 0 and not "".join(part.itertext()).strip():
                        warn(f"mml:{ln(el.tag)} has an empty base or script element "
                             f"(<mml:{ln(part.tag)}/>) — check the recovered equation")
                        break
            if ln(el.tag) == "mrow" and len(children) == 1 and not (el.text or "").strip():
                warn("mml:mrow wraps a single child element — superfluous wrapper "
                     "(machine-MathML smell)")
    for df in by.get("disp-formula", []):
        for sub in df.iter():
            if sub is not df and ln(sub.tag) in ("disp-formula", "inline-formula"):
                err("<disp-formula> contains a nested formula element "
                    f"(<{ln(sub.tag)}>) — formulas must not nest")
    for inf in by.get("inline-formula", []):
        for sub in inf.iter():
            if sub is not inf and ln(sub.tag) in ("disp-formula", "inline-formula"):
                err("<inline-formula> contains a nested formula element "
                    f"(<{ln(sub.tag)}>) — formulas must not nest")

    # ---- <alternatives> discipline (house equation pattern: image ground truth + MathML) ----
    ALT_FORMULA_KIDS = {"graphic", "math", "tex-math", "media", "textual-form"}
    for alt in by.get("alternatives", []):
        par = ln(parent_of[alt].tag) if alt in parent_of else "?"
        if par in ("disp-formula", "inline-formula"):
            maths = [c for c in alt if ln(c.tag) == "math"]
            if len(maths) > 1:
                err(f"<alternatives> in <{par}> contains {len(maths)} <mml:math> elements "
                    "— alternate forms of ONE formula, so at most one MathML rendering")
            for c in alt:
                if ln(c.tag) not in ALT_FORMULA_KIDS:
                    err(f"<alternatives> in <{par}> contains <{ln(c.tag)}> — allowed children "
                        "are graphic / mml:math / tex-math / media / textual-form")
        if len(list(alt)) < 2:
            warn(f"<alternatives> in <{par}> has fewer than 2 children — superfluous wrapper")

    # ---- whole-block formatting wrap (conversion-artifact smell) ----
    # PMC blocks this; the house "retain all source formatting" principle means an all-italic
    # caption CAN be faithful — so it is a warning for the human/jats-verify, never a block.
    FORMAT_TAGS = {"bold", "italic", "underline", "sc", "monospace"}
    for tag in ("p", "title"):
        for el in by.get(tag, []):
            kids = list(el)
            if (len(kids) == 1 and ln(kids[0].tag) in FORMAT_TAGS
                    and not (el.text or "").strip() and not (kids[0].tail or "").strip()
                    and "".join(kids[0].itertext()).strip()):
                warn(f"entire content of a <{tag}> is wrapped in <{ln(kids[0].tag)}> — "
                     "styling artifact? confirm the source really formats the whole block")

    # ---- xlink:href hygiene (graphics excluded: the case-exact resolve check owns those) ----
    for el in root.iter():
        if ln(el.tag) in ("graphic", "inline-graphic"):
            continue
        href = None
        for k, v in el.attrib.items():
            if k.rsplit("}", 1)[-1] == "href" or k == "xlink:href":
                href = v
        if href is None:
            continue
        tagname = ln(el.tag)
        if not href.strip():
            err(f"<{tagname}> has an empty xlink:href")
            continue
        if href != href.strip():
            err(f"<{tagname}> xlink:href has leading/trailing whitespace: '{href}'")
        if href.strip().startswith("#"):
            err(f"<{tagname}> xlink:href starts with '#' — internal links use <xref>, "
                "not xlink:href")
        if tagname == "ext-link" and not href.strip().lower().startswith(EXT_SCHEMES):
            err(f"<ext-link> xlink:href '{href}' has no recognised scheme "
                "(http/https/ftp/www…) — link will not resolve in the review render")
    for xl in by.get("ext-link", []):
        if not xl.get("ext-link-type"):
            warn("an <ext-link> has no @ext-link-type (house renders assume 'uri'/'doi')")

    # ---- licence internal consistency (the rights statement is load-bearing for Green OA) ----
    CC_URI_RE = re.compile(r"^https?://creativecommons\.org/(licenses|publicdomain)/")
    for L in lic:
        lhref = xa(L, "href") or ""
        ltext = "".join(L.itertext())
        cc_uris = [u for u in [lhref] +
                   [xa(x, "href") or "" for x in L.iter() if ln(x.tag) == "ext-link"]
                   if "creativecommons" in u]
        for u in cc_uris:
            if "licences" in u:
                err(f"Creative Commons URL uses variant spelling 'licences' (breaks the URI): {u}")
            elif not CC_URI_RE.match(u.strip()):
                warn(f"Creative Commons URL is not a standard machine-readable licence URI: {u}")
        for x in (x for x in L.iter() if ln(x.tag) == "ext-link"):
            content = "".join(x.itertext()).strip()
            xhref = (xa(x, "href") or "").strip()
            if content.startswith(("http://", "https://", "www.")) and xhref \
                    and content != xhref:
                err("licence <ext-link> content URI and @xlink:href differ "
                    f"(content '{content}' vs href '{xhref}')")
        if re.search(r"creative\s+commons|cc[- ]by", ltext, re.I) and not cc_uris:
            err("licence text claims a Creative Commons licence but carries no "
                "creativecommons.org URI (machine-readable rights required)")

    # ---- name-part sanity + ORCID format ----
    for part_tag in ("surname", "given-names"):
        for el in by.get(part_tag, []):
            v = "".join(el.itertext()).strip()
            if v and not re.search(r"[\w]", v, re.UNICODE):
                err(f"<{part_tag}> '{v}' is punctuation-only — a stray initial or "
                    "separator tagged as a name part")
    for cid in by.get("contrib-id", []):
        if cid.get("contrib-id-type") != "orcid":
            continue
        v = (cid.text or "").strip()
        if not re.match(r"^https?://orcid\.org/", v):
            err(f"ORCID contrib-id '{v}' must be a full https://orcid.org/ URI")
        elif not re.fullmatch(r"https?://orcid\.org/\d{4}-\d{4}-\d{4}-\d{3}[\dX]", v):
            warn(f"ORCID contrib-id '{v}' does not look like a 16-digit ORCID")

    # ---- table mechanics (transcribed tables: span typos break the rendered grid) ----
    for cell_tag in ("td", "th"):
        for cell in by.get(cell_tag, []):
            for span in ("colspan", "rowspan"):
                v = cell.get(span)
                if v is not None and (not v.isdigit() or int(v) < 1):
                    err(f"<{cell_tag}> @{span}='{v}' is not a positive integer")
    for tbl in by.get("table", []):
        if len([c for c in tbl if ln(c.tag) == "tbody"]) > 1:
            warn("a <table> has more than one <tbody> — transcription artifact? "
                 "(house tables use a single body)")
    inside_twf = {id(d) for twf in by.get("table-wrap-foot", []) for d in twf.iter()}
    for tw in by.get("table-wrap", []):
        for d in tw.iter():
            if ln(d.tag) == "fn" and id(d) not in inside_twf:
                warn("a table footnote <fn> sits outside <table-wrap-foot> — "
                     "footnotes belong in the table foot")
                break

    # ---- xref hygiene ----
    for x in by.get("xref", []):
        if x.get("ref-type") and not x.get("rid"):
            warn(f"<xref ref-type='{x.get('ref-type')}'> has no @rid — unlinkable "
                 "cross-reference")
        content = "".join(x.itertext()).strip()
        if content.endswith((",", ";")):
            warn(f"<xref> content '{content}' ends in punctuation — separators between "
                 "contiguous citations belong OUTSIDE the <xref>")

    # ---- empty elements (dropped-content fossils) ----
    for tag in ("title", "label"):
        for el in by.get(tag, []):
            if len(el) == 0 and not "".join(el.itertext()).strip():
                err(f"an empty <{tag}> (no text, no children) — dropped content or "
                    "stray element")
    for el in by.get("p", []):
        if len(el) == 0 and not "".join(el.itertext()).strip():
            warn("an empty <p> (no text, no children) — padding artifact?")

    # ---- heading subj-group discipline ----
    for g in (g for g in by.get("subj-group", []) if g.get("subj-group-type") == "heading"):
        subs = [c for c in g if ln(c.tag) == "subject"]
        if len(subs) != 1:
            err(f"heading <subj-group> must contain exactly one <subject> (found {len(subs)})")
        for s in subs:
            if len(s):
                err("heading <subject> must be plain text — no emphasis or other "
                    f"child elements (<{ln(s[0].tag)}> found)")

    # ---- runs of literal spaces in mixed content (builder boundary-whitespace defects;
    #      literal spaces ONLY, so pretty-printed newlines/indents never trip it) ----
    for tag in ("p", "title", "mixed-citation"):
        hits = 0
        for el in by.get(tag, []):
            chunks = [el.text or ""] + [(c.tail or "") for c in el]
            if any(re.search(r"\S {2,}\S", ch) for ch in chunks):
                hits += 1
        if hits:
            warn(f"{hits} <{tag}> element(s) contain a run of multiple literal spaces — "
                 "element-boundary whitespace defect?")

    # ---- hyphenation consistency (house rule: keep lexical hyphens, close genuine splits) ----
    # A single compound written BOTH ways in one document ("non-listed" AND "nonlisted") is the
    # line-break-normalisation defect the PDF de-hyphenation pass now prevents (see the Hyphenation
    # section of MORE_XML_Authoring_Guide.md). Scoped to compounds the house rule would KEEP
    # hyphenated, so genuinely-distinct closed words (e.g. "recover" vs "re-cover") are not flagged.
    # Interpretive style signal for the human + jats-verify — a warning, never a block.
    body_txt = " ".join("".join(b.itertext()) for b in by.get("body", [])) or "".join(root.itertext())
    closed = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", body_txt)}
    seen = set()
    for m in re.finditer(r"\b([A-Za-z]{2,})-([A-Za-z]{2,})\b", body_txt):
        a, b = m.group(1), m.group(2)
        key = (a.lower(), b.lower())
        if key in seen:
            continue
        seen.add(key)
        if (a.lower() + b.lower()) in closed and is_lexical_compound(a, b):
            warn(f"compound '{a}-{b}' also appears closed up as '{a}{b}' — inconsistent line-break "
                 "hyphenation (house rule keeps lexical hyphens; check the PDF de-hyphenation pass)")

    return errors, warnings

def main():
    ap = argparse.ArgumentParser(description="Deterministic MORE house-style JATS linter.")
    ap.add_argument("target")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        xml_path = resolve_xml(args.target)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr); return 2
    pkg_dir = os.path.dirname(os.path.abspath(xml_path))
    if not os.path.isfile(xml_path):
        print(f"ERROR: no such file: {xml_path}", file=sys.stderr); return 2
    errors, warnings = lint(xml_path, pkg_dir)
    if args.json:
        print(json.dumps({"result": "FAIL" if errors else "PASS",
                          "errors": errors, "warnings": warnings}, indent=2))
    else:
        print(f"\nHouse-style lint: {xml_path}")
        print("-" * 60)
        verdict = "FAIL" if errors else "PASS"
        print(f"Result: {verdict} ({len(errors)} error(s), {len(warnings)} warning(s))")
        for e in errors:
            print(f"  ERROR    {e}")
        for w in warnings:
            print(f"  warning  {w}")
        print("-" * 60)
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
