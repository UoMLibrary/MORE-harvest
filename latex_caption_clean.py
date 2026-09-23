#!/usr/bin/env python3
r"""Clean raw LaTeX out of figure/table captions in repo_pdf-route house-JATS packages.

The scoap3_jhep (repo_pdf) route ingests LaTeX-derived JATS whose <caption> prose still
carries source markup: inline math ($\gamma\gamma$), Greek/arrows/relations, siunitx units
(\SI{100}{\GeV}), sub/superscripts, and ~15 custom ATLAS macros (\mX, \Zp, \BRxgg ...). No
off-the-shelf converter expands the custom macros without the paper preamble, so this is a
purpose-built LaTeX -> Unicode text normaliser: it produces clean, readable plain-text
captions (gamma-gamma -> "gamma-gamma" as "γγ", H\\pm -> "H±", \SI{13}{\TeV} -> "13 TeV").

It is deliberately TEXT normalisation, not semantic MathML: math becomes readable Unicode,
not <inline-formula>. Scope is <caption> text only; body-level LaTeX leakage (\end{figure},
\includegraphics ...) is a separate, larger clean-up.

USAGE
    python latex_caption_clean.py W4400601332 [W4401306919 ...]   # named packages
    python latex_caption_clean.py --all                            # every repo_pdf package
    python latex_caption_clean.py W4400601332 --dry-run            # preview, write nothing
    python latex_caption_clean.py --all --no-gates
"""
import argparse
import json
import os
import re
import subprocess
import sys

from lxml import etree

MACRON = "̄"  # combining macron, for \bar / \=

HERE = os.path.dirname(os.path.abspath(__file__))
# The gates live in vendor/scripts/ in this snapshot (see vendor/SOURCE.md);
# in the full workspace this points at the AAM workstation sibling instead.
WS = os.path.join(HERE, "vendor")
INGESTED = os.path.join(HERE, "ingested")

# ---- symbol tables -------------------------------------------------------------------------
GREEK = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ", r"\vartheta": "ϑ", r"\iota": "ι", r"\kappa": "κ",
    r"\lambda": "λ", r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ",
    r"\pi": "π", r"\rho": "ρ", r"\varrho": "ϱ", r"\sigma": "σ",
    r"\tau": "τ", r"\upsilon": "υ", r"\phi": "φ", r"\varphi": "φ",
    r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω",
    r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ",
    r"\Xi": "Ξ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Upsilon": "Υ",
    r"\Phi": "Φ", r"\Psi": "Ψ", r"\Omega": "Ω",
}
SYMBOL = {
    r"\rightarrow": "→", r"\to": "→", r"\longrightarrow": "⟶",
    r"\leftarrow": "←", r"\Rightarrow": "⇒", r"\Leftarrow": "⇐",
    r"\leftrightarrow": "↔", r"\mapsto": "↦",
    r"\pm": "±", r"\mp": "∓", r"\times": "×", r"\cdot": "·",
    r"\ast": "∗", r"\star": "⋆", r"\circ": "∘", r"\bullet": "•",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\simeq": "≃",
    r"\sim": "∼", r"\equiv": "≡", r"\propto": "∝", r"\ll": "≪",
    r"\gg": "≫", r"\infty": "∞", r"\partial": "∂", r"\nabla": "∇",
    r"\in": "∈", r"\notin": "∉", r"\subset": "⊂", r"\cap": "∩",
    r"\cup": "∪", r"\forall": "∀", r"\exists": "∃", r"\langle": "⟨",
    r"\rangle": "⟩", r"\pi": "π", r"\ell": "ℓ", r"\hbar": "ℏ",
    r"\dagger": "†", r"\prime": "′", r"\emptyset": "∅", r"\perp": "⊥",
    r"\parallel": "∥", r"\oplus": "⊕", r"\otimes": "⊗", r"\sum": "∑",
    r"\prod": "∏", r"\int": "∫", r"\pm ": "±", r"\%": "%",
}
# custom ATLAS / physics macros seen in this corpus. Outputs use braced _{}/^{} scripts so the
# single script pass renders them uniformly (and never leaves a literal underscore behind).
MACRO = {
    r"\GeV": "GeV", r"\TeV": "TeV", r"\MeV": "MeV", r"\keV": "keV", r"\eV": "eV",
    r"\ifb": "fb^{-1}", r"\fbinv": "fb^{-1}", r"\ipb": "pb^{-1}",
    r"\fb": "fb", r"\pb": "pb",
    r"\mX": "m_{X}", r"\mH": "m_{H}", r"\mgg": "m_{γγ}", r"\mj": "m_{j}",
    r"\mll": "m_{ll}", r"\mtt": "m_{tt}", r"\ptop": "p_{T}", r"\pt": "p_{T}",
    r"\MET": "E_{T}^{miss}",
    r"\Zp": "Z′", r"\Zprime": "Z′", r"\Zboson": "Z", r"\Wboson": "W",
    r"\qqbar": "qq" + MACRON, r"\ttbar": "tt" + MACRON, r"\bbbar": "bb" + MACRON,
    r"\BRxgg": "BR(X→γγ)", r"\BRhgg": "BR(H→γγ)",
    r"\xsecBR": "σ×BR", r"\ddtcorr": "DDT-corrected",
    r"\yv": "y", r"\yz": "y_{0}", r"\pp": "pp", r"\sqrts": "√s",
}
SPACING = [r"\,", r"\;", r"\:", r"\!", r"\ ", r"\quad", r"\qquad", r"\thinspace"]

# Unicode super/subscripts: digits+signs always; letters where a glyph exists (q, and most
# uppercase, have none -> those groups flatten instead).
SUP = {c: s for c, s in zip("0123456789+-=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾")}
SUP.update({c: s for c, s in zip("abcdefghijklmnoprstuvwxyz",
                                 "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ")})
SUB = {c: s for c, s in zip("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")}
SUB.update({c: s for c, s in zip("aehijklmnoprstuvx", "ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")})


def _sup(group):
    """Superscript group -> Unicode iff every char maps (digits/signs); else flatten inline."""
    if group and all(ch in SUP for ch in group):
        return "".join(SUP[ch] for ch in group)
    return group


def _sub(group):
    if group and all(ch in SUB for ch in group):
        return "".join(SUB[ch] for ch in group)
    return group


def _accent(content):
    content = content.strip()
    if not content:
        return content
    return content[0] + MACRON + content[1:]


def clean_text(s):
    """LaTeX -> readable Unicode for a single run of caption text."""
    if not s or ("\\" not in s and "$" not in s and "^" not in s and "_" not in s
                 and "~" not in s and "--" not in s):
        return s

    # 1. custom macros (whole-word, longest first so \mX beats \m)
    for k in sorted(MACRO, key=len, reverse=True):
        s = re.sub(re.escape(k) + r"(?![a-zA-Z])", MACRO[k], s)

    # 2. structured commands that consume their braces
    s = re.sub(r"\\SI\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1 \2", s)   # \SI{13}{TeV} -> "13 TeV"
    s = re.sub(r"\\num\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1/\2", s)
    s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", "√" + r"\1", s)
    s = re.sub(r"\\sqrt\s+(\S)", "√" + r"\1", s)
    s = re.sub(r"\\(?:bar|overline)\s*\{([^{}]*)\}", lambda m: _accent(m.group(1)), s)
    s = re.sub(r"\\(?:bar|hat|vec|tilde|dot)\s+([A-Za-z])", lambda m: _accent(m.group(1)), s)
    s = re.sub(r"\\=\s*\{?([A-Za-z])\}?", lambda m: m.group(1) + MACRON, s)  # \=t -> t-macron

    # 3. text/math-font wrappers. First rebrace a wrapper that IS a script argument so the
    #    group survives (m^\mathrm{lep} -> m^{lep}); then strip any standalone wrapper to its
    #    bare content (\mathrm{X} -> X). Keeps scripts grouped without ever doubling braces.
    fonts = r"mathrm|textrm|text|mbox|hbox|mathcal|mathbf|mathit|mathsf|boldsymbol|operatorname|rm|it|bf"
    s = re.sub(r"([_^])\\(?:" + fonts + r")\s*\{([^{}]*)\}", r"\1{\2}", s)
    wrapper = re.compile(r"\\(?:" + fonts + r")\s*\{([^{}]*)\}")
    prev = None
    while prev != s:
        prev = s
        s = wrapper.sub(r"\1", s)

    # 4. Greek + symbols/relations/arrows (word-boundary, longest-first so \le can't eat \leq)
    for k in sorted({**GREEK, **SYMBOL}, key=len, reverse=True):
        s = re.sub(re.escape(k) + r"(?![a-zA-Z])", {**GREEK, **SYMBOL}[k], s)

    # 5. delimiters that are just noise around content
    s = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)(?=[([{)\]}|.])", "", s)

    # 6. sub/superscripts: braced group first, then a single following char (any non-space,
    #    non-brace glyph -> mappable ones go Unicode, the rest flatten inline, e.g. ^± -> ±)
    s = re.sub(r"\^\{([^{}]*)\}", lambda m: _sup(m.group(1)), s)
    s = re.sub(r"_\{([^{}]*)\}", lambda m: _sub(m.group(1)), s)
    s = re.sub(r"\^([^\s{}])", lambda m: _sup(m.group(1)), s)
    s = re.sub(r"_([^\s{}])", lambda m: _sub(m.group(1)), s)

    # 7. citations / labels / typesetting hints -> drop
    s = re.sub(r"\\(?:cite|citep|citet|ref|eqref|label|autoref)\s*\{[^{}]*\}", "", s)
    s = re.sub(r"\\looseness\s*=?\s*-?\d*", "", s)
    s = re.sub(r"\\(?:centering|noindent|par|hfill|vfill|newline|linebreak)\b", "", s)

    # 8. spacing + escaped specials, then unwrap math delimiters
    for sp in SPACING:
        s = s.replace(sp, " ")
    s = s.replace("~", " ")
    for esc, lit in ((r"\%", "%"), (r"\&", "&"), (r"\#", "#"), (r"\_", "_"), (r"\$", "$")):
        s = s.replace(esc, lit)
    s = s.replace(r"\(", "").replace(r"\)", "").replace("$", "")

    # 9. any residual unknown \command -> strip the control word (keep a note via caller)
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    s = s.replace("{", "").replace("}", "")

    # 10. punctuation / whitespace tidy
    s = s.replace("---", "—").replace("--", "–")
    s = re.sub(r"[ \t\r\n]+", " ", s)
    s = re.sub(r"\s+([,;.)\]])", r"\1", s)
    s = re.sub(r"([(\[])\s+", r"\1", s)
    return s


def clean_caption_element(cap):
    """Clean every text run inside a <caption>, preserving any child elements. Returns True
    if anything changed."""
    changed = False
    for node in cap.iter():
        for attr in ("text", "tail"):
            val = getattr(node, attr)
            if val:
                new = clean_text(val)
                if new != val:
                    setattr(node, attr, new)
                    changed = True
    return changed


JATS = "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD with MathML3 v1.4 20241031//EN"
DTD = "https://jats.nlm.nih.gov/archiving/1.4/JATS-archivearticle1-4-mathml3.dtd"


def clean_captions_in_file(path, dry_run=False):
    """Clean all <caption> elements. Returns (n_changed, previews[(before,after)])."""
    parser = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)
    root = etree.parse(path, parser).getroot()
    n = 0
    previews = []
    for cap in root.iter("{*}caption"):
        before = "".join(cap.itertext())
        if clean_caption_element(cap):
            n += 1
            after = "".join(cap.itertext())
            if len(previews) < 3:
                previews.append((before.strip(), after.strip()))
    if n and not dry_run:
        etree.cleanup_namespaces(root)
        body = etree.tostring(root, encoding="unicode")
        doc = ('<?xml version="1.0" encoding="utf-8"?>\n'
               '<!DOCTYPE article PUBLIC "%s"\n         "%s">\n%s\n' % (JATS, DTD, body))
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)
    return n, previews


def run_gates(pkg):
    ax = os.path.join(pkg, "article.xml")

    def sh(*cmd):
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    v = sh(sys.executable, os.path.join(WS, "scripts", "validate_jats.py"), ax)
    vlast = (v.stdout.strip().splitlines() or ["?"])[-1]
    hl = sh(sys.executable, os.path.join(WS, "scripts", "jats_house_lint.py"), ax)
    line = [l for l in hl.stdout.splitlines() if l.startswith("Result")]
    return vlast, (line[0] if line else hl.stdout.strip()[:120])


def is_repo_pdf(pkg):
    mp = os.path.join(pkg, "metadata.json")
    if not os.path.isfile(mp):
        return False
    try:
        return json.load(open(mp, encoding="utf-8")).get("route", {}).get("asset_route") == "repo_pdf"
    except Exception:  # noqa: BLE001
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_ids", nargs="*")
    ap.add_argument("--all", action="store_true", help="every ingested repo_pdf package")
    ap.add_argument("--dry-run", action="store_true", help="preview only; write nothing")
    ap.add_argument("--no-gates", action="store_true")
    args = ap.parse_args()

    ids = args.work_ids
    if args.all:
        ids = [d for d in sorted(os.listdir(INGESTED)) if is_repo_pdf(os.path.join(INGESTED, d))]
        print("repo_pdf packages: %s\n" % (", ".join(ids) or "(none)"))
    if not ids:
        ap.error("give one or more work ids, or --all")

    for wid in ids:
        pkg = wid if os.path.isdir(wid) else os.path.join(INGESTED, wid)
        ax = os.path.join(pkg, "article.xml")
        if not os.path.isfile(ax):
            print("[%s] no article.xml -- skipped\n" % os.path.basename(pkg))
            continue
        n, previews = clean_captions_in_file(ax, dry_run=args.dry_run)
        tag = "would clean" if args.dry_run else "cleaned"
        print("[%s] %s %d caption(s)" % (os.path.basename(pkg), tag, n))
        for b, a in previews:
            print("    - before: " + (b[:140]))
            print("      after : " + (a[:140]))
        if n and not args.dry_run and not args.no_gates:
            v, l = run_gates(pkg)
            print("    validate: %s" % v)
            print("    house-lint: %s" % l)
        print()


if __name__ == "__main__":
    main()
