#!/usr/bin/env python3
"""Per-publisher rules for the Lane-B (convert_vor) TEI->JATS pipeline.

GROBID emits the SAME TEI schema for every publisher, but how well it parsed a given
PDF — and which house decisions we must make — varies by publisher's typesetting. So
the pipeline is ONE shared core (tei_to_jats.py) plus a small per-publisher rule object
that the core consults for the handful of things that genuinely differ:

  * reference_style   'numbered' (RSC: [1]) vs 'author-year' (Wiley/OUP/CUP/T&F)
  * headings_numbered whether section <head>s carry a numeric prefix ("3.1 Methods")
                      that should be split into a <label> (True), have none (False),
                      or are mixed/unknown (None -> auto-detect per document)
  * trust_tei_license GROBID almost never recovers the licence (TEI <licence> is empty),
                      so this is False everywhere for now — licence comes from the
                      OpenAlex metadata the caller passes in, NEVER fabricated. Kept as a
                      field so a publisher whose PDF *does* carry a parseable licence can
                      opt in later.
  * trust_tei_journal same story: monogr/title is often empty; journal title comes from
                      the work-tracker DB (works.journal) the caller passes in.
  * font_hint         dominant body font(s) seen in interrogate_pdfs.py — lets us
                      AUTO-DETECT the publisher from the PDF itself, not only trust the
                      OpenAlex `publisher` string (which can be a lineage alias).

Seeded 2026-07-13 from interrogate_pdfs.py over the 100-PDF starter corpus (Wiley, OUP,
Cambridge, RSC, T&F); confirmed and calibrated against the captured TEI corpus in the
2026-07-14/15 full-corpus runs (76 pairs, tei_pilot.py + fidelity_calibrate.py).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PublisherRule:
    slug: str
    display_name: str
    reference_style: str = "author-year"     # 'numbered' | 'author-year'
    headings_numbered: object = None          # True | False | None(auto)
    trust_tei_license: bool = False
    trust_tei_journal: bool = False
    font_hint: tuple = ()
    notes: str = ""
    # completeness PASS floor for the fidelity gate (lanec/pdf_fidelity.py); None takes
    # the calibrated default. Override ONLY on fidelity_calibrate.py evidence (e.g. a
    # publisher whose PDFs are line-numbered proofs sits structurally lower) + CHANGELOG.
    fidelity_floor: object = None


# --- registry, keyed by slug (slug = tei_to_jats.slug(publisher name)) ----------------
_RULES = [
    PublisherRule(
        slug="wiley", display_name="Wiley",
        reference_style="author-year", headings_numbered=False,
        font_hint=("STIXTwoText", "AdvBOOKO-R", "AdvTimes"),
        notes="Unnumbered headings (1/8). Licence on p0 but TEI unreliable -> metadata. "
              "'N of M' running header.",
    ),
    PublisherRule(
        slug="oxford-university-press", display_name="Oxford University Press",
        reference_style="author-year", headings_numbered=True,
        font_hint=("Times-Roman", "TeXGyreTermesX-Regular", "CMR10"),
        notes="Strongly numbered headings (7/8). Big MNRAS/astronomy population. "
              "DOI sometimes missing on p0 (6/8).",
    ),
    PublisherRule(
        slug="cambridge-university-press", display_name="Cambridge University Press",
        reference_style="author-year", headings_numbered=None,
        font_hint=("NimbusRomNo9L-Regu",),
        notes="Mixed heading numbering (5/8). Direct publisher PDF fetch WORKS (no 403). "
              "Running header 'J. <Journal> (2025), vol. ...'.",
    ),
    PublisherRule(
        slug="royal-society-of-chemistry", display_name="Royal Society of Chemistry",
        reference_style="numbered", headings_numbered=True,
        font_hint=("AdvOT9b12cd41", "AdvOT999035f4", "LiberationSans"),
        notes="Numbered refs [1] and numbered headings (8/8). Chemistry, very regular "
              "layout. Best first target for an end-to-end prototype.",
    ),
    PublisherRule(
        slug="taylor-francis", display_name="Taylor & Francis",
        reference_style="author-year", headings_numbered=None,
        font_hint=("OpenSans", "Helvetica"),
        notes="Licence NOT on p0 (0/8) -> metadata licence is MANDATORY here. "
              "Distinct page size 634x833. Journal-name running header.",
    ),
]

REGISTRY = {r.slug: r for r in _RULES}

DEFAULT = PublisherRule(
    slug="_default", display_name="(unknown publisher)",
    reference_style="author-year", headings_numbered=None,
    notes="Fallback: safe generic behaviour, auto-detect heading numbering per document.",
)


def slugify(name):
    import re
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]


def for_publisher(name_or_slug):
    """Resolve a rule from an OpenAlex publisher string or an existing slug."""
    if not name_or_slug:
        return DEFAULT
    s = name_or_slug if name_or_slug in REGISTRY else slugify(name_or_slug)
    return REGISTRY.get(s, DEFAULT)


def detect_by_font(font_names):
    """Best-effort publisher guess from a PDF's dominant fonts (from interrogate_pdfs)."""
    fonts = {f for f in font_names if f}
    for rule in _RULES:
        if fonts & set(rule.font_hint):
            return rule
    return DEFAULT


if __name__ == "__main__":
    for slug, r in REGISTRY.items():
        print(f"{slug:32s} refs={r.reference_style:12s} headings={r.headings_numbered}")
    print(f"{'_default':32s} refs={DEFAULT.reference_style}")
