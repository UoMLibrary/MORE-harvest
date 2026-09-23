"""The lane router's POLICY — what decides how each paper is acquired.

This file is deliberately data, not plumbing. Every routing decision the pipeline
makes lives here as an ordered table of rules; `routing/__init__.py` compiles them
into the SQL that `harvest_openalex.build_db` runs. Nothing here touches a database.

Read it top to bottom and you have the whole judgement:

    scoap3        is this a SCOAP3 particle-physics journal, and which XML flavour?
    route         the CHEAPEST actual XML-acquisition mechanism for this paper
    route_access  how much friction that mechanism costs (open / key / entitlement)
    asset_route   where the figures come from (never the XML — see the guardrail)
    lane          the coarse cost tier, rolled up from route
    disposition   what a HUMAN must do with it, driven by the VoR licence

Rules are ORDERED and first-match-wins, exactly like the SQL CASE they compile to.
Reordering them changes routing. Each carries a `why` explaining the decision, and
those explanations are the point of this file — several record findings that cost a
session to discover.

To see the compiled decision table:  python -m routing --explain
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """One arm of a first-match-wins decision table.

    `when` is a SQL boolean expression over the `works` table; `then` is the value
    assigned when it matches (None emits SQL NULL); `why` is for the human reading
    the policy, and is carried through into `--explain` output.
    """
    when: str
    then: str | None
    why: str = ""


# ---------------------------------------------------------------------------
# Publisher sets — matched against OpenAlex's `publisher` string, exactly.
# OpenAlex is inconsistent about corporate naming (both "Springer Nature" and
# "Springer Science+Business Media" occur), so several names appear per house.
# ---------------------------------------------------------------------------

SPRINGER = (
    "Springer Science+Business Media", "Springer Nature",
    "Nature Portfolio", "BioMed Central",
)

# Publishers that put well-formed JATS on the open web with no key and no deal.
NATIVE_OPEN = (
    "Multidisciplinary Digital Publishing Institute", "Frontiers Media",
    "Public Library of Science",
    "eLife Sciences Publications Ltd", "eLife Sciences Publications",
    "PeerJ", "Copernicus GmbH", "Copernicus Publications",
    "Pensoft Publishers", "F1000 Research Ltd", "F1000 Research",
    "The Royal Society", "Royal Society",
    "NIHR Journals Library", "Ubiquity Press",
    "Open Library of the Humanities",
)

ELSEVIER = ("Elsevier BV", "Elsevier")

# Full-text XML exists but is behind a subscription or a deal we do not hold.
# These fall to Lane B (convert the published PDF).
GATED = (
    "Wiley", "Oxford University Press", "Taylor & Francis", "SAGE Publishing",
    "American Chemical Society", "Cambridge University Press",
    "Institute of Electrical and Electronics Engineers",
    "IOP Publishing", "Institute of Physics",
    "Royal Society of Chemistry", "American Physical Society",
    "EDP Sciences", "BMJ", "BMJ Publishing Group",
)

# Not publishers at all — repositories OpenAlex records in the publisher field.
REPOSITORY = (
    "Figshare", "Figshare (United Kingdom)",
    "European Organization for Nuclear Research", "Zenodo",
)

# Licences under which the VERSION OF RECORD may lawfully be re-expressed as JATS.
# The key test is NoDerivatives: converting a VoR into JATS is a derivative work,
# so every -nd licence is excluded, as are NC and closed.
REUSABLE_LICENCES = ("cc-by", "cc-by-sa", "public-domain", "cc0")


# ---------------------------------------------------------------------------
# scoap3 — SCOAP3 membership and XML flavour, matched on journal name.
#
# SCOAP3 journals split by what they deposit: the APS side deposits JATS we can
# ingest directly (Lane C); the rest need a one-time per-DTD transform (Lane C').
#
# SCOAP3 covers PARTICLE physics only. The APS side is Phys Rev D, Phys Rev C and
# Phys Rev Letters — NOT PR E/A/B/Research/Materials/Fluids/Applied, which are not
# in SCOAP3. Journal-name granularity slightly over-includes non-HEP PRL; the
# per-paper SCOAP3 lookup at ingest returns zero hits for those and they fall back
# to Lane B, so the over-inclusion is self-correcting.
# ---------------------------------------------------------------------------

APS_JOURNALS = (
    "physical review. d%", "physical review d%",
    "physical review. c%", "physical review c%",
    "physical review letters%",
)

OTHER_SCOAP3_JOURNALS = (
    "%high energy physics%",
    "%european physical journal c%",
    "%physics letters b%",
    "%nuclear physics b%",
    "%chinese physics c%",
    "%theoretical and experimental physics%",
    "%acta physica polonica b%",
)


def _journal_like(*patterns: str) -> str:
    return "(" + " OR ".join(f"lower(journal) LIKE '{p}'" for p in patterns) + ")"


def _publisher_in(names: tuple[str, ...]) -> str:
    return "publisher IN (" + ", ".join("'" + n.replace("'", "''") + "'" for n in names) + ")"


def _route_in(*routes: str) -> str:
    return "route IN (" + ", ".join(f"'{r}'" for r in routes) + ")"


SCOAP3_RULES = [
    Rule(_journal_like(*APS_JOURNALS), "aps",
         "APS deposits JATS — ingestable as-is (Lane C)"),
    Rule(_journal_like(*OTHER_SCOAP3_JOURNALS), "other",
         "In SCOAP3 but deposits a foreign DTD — needs a transform (Lane C')"),
]
SCOAP3_DEFAULT = None  # not a SCOAP3 journal


# ---------------------------------------------------------------------------
# route — the cheapest actual XML-acquisition mechanism, first match wins.
#
# Priority is cheapest-first: a paper in PMC is taken from PMC whatever its
# publisher, because the PMC OA subset is cross-publisher and free, before we
# bother with a publisher-specific API or a key.
# ---------------------------------------------------------------------------

ROUTE_RULES = [
    Rule("license <> 'cc-by' OR license IS NULL", "out_of_scope",
         "Not CC-BY: harvest never touches it. Licence is verified per work — "
         "our own VoRs are frequently NC-ND."),

    Rule("in_pmc", "pmc",
         "In the PMC OA subset: free, cross-publisher, no key. Always cheapest."),

    Rule("scoap3 = 'aps'", "scoap3_aps",
         "APS deposits JATS to SCOAP3 — straight ingest."),

    # SCOAP3 'other' was one coarse bucket until a source scan proved it hides
    # three different realities. Splitting it is what moved JHEP and EPJ-C out of
    # the transform lane. Order matters inside this group.
    Rule("scoap3 = 'other' AND " + _journal_like("%high energy physics%"), "scoap3_jhep",
         "JHEP: Springer A++ header -> BodyRef -> JATS, so it ingests"),
    Rule("scoap3 = 'other' AND " + _journal_like("%european physical journal c%"),
         "springer_oa_api",
         "EPJ-C: SCOAP3 carries metadata only, so go to the Springer OA API for XML"),
    Rule("scoap3 = 'other' AND " + _journal_like("%physics letters b%", "%nuclear physics b%"),
         "scoap3_elsevier",
         "Elsevier DTD -> lanec/elsevier_to_jats.py transform"),
    Rule("scoap3 = 'other'", "scoap3_other",
         "Residue: Chinese Physics C, PTEP, Acta Physica Polonica B"),

    Rule(_publisher_in(SPRINGER), "springer_oa_api",
         "Springer OA API — free key"),
    Rule(_publisher_in(NATIVE_OPEN), "jats_native_open",
         "Publisher serves JATS openly, no key"),
    Rule(_publisher_in(ELSEVIER), "elsevier_entitlement",
         "Elsevier full-text API — needs an entitled key"),
    Rule(_publisher_in(GATED), "gated_commercial",
         "XML exists but we hold no deal for it -> Lane B, convert the PDF"),
    Rule(_publisher_in(REPOSITORY) + " OR publisher IS NULL", "repository",
         "A repository, not a publisher -> Lane B"),
]
ROUTE_DEFAULT = "convert"  # no open XML anywhere -> Lane B


# ---------------------------------------------------------------------------
# route_access — how much friction the chosen route costs. A pure lookup.
# ---------------------------------------------------------------------------

ROUTE_ACCESS = {
    "pmc": "open",
    "scoap3_aps": "open",
    "scoap3_other": "open",
    "scoap3_jhep": "open",
    "scoap3_elsevier": "open",
    "jats_native_open": "open",
    "springer_oa_api": "free_key",
    "elsevier_entitlement": "entitlement",
    "gated_commercial": "gated",
    "repository": "repository",
    "convert": "none",
}
ROUTE_ACCESS_DEFAULT = "na"  # out_of_scope


# ---------------------------------------------------------------------------
# asset_route — where the NON-TEXTUAL assets come from.
#
# Design principle (2026-07-04), and a guardrail rather than a preference: asset
# capture is NON-NEGOTIABLE on every route. The XML never carries its own images,
# so every paper must have a NAMED asset source, and 'none' is an explicit
# escalation flag — never a silent gap.
#
# Note that an absent OpenAlex pdf_url does NOT mean there is no PDF: SCOAP3, PMC
# and Elsevier all hold PDFs route-natively.
# ---------------------------------------------------------------------------

ASSET_ROUTE_RULES = [
    Rule("route = 'pmc'", "publisher_package",
         "The PMC package carries the figures with it"),
    Rule(_route_in("scoap3_aps", "scoap3_other", "scoap3_jhep", "scoap3_elsevier"),
         "repo_pdf",
         "SCOAP3 holds the PDF in its repository"),
    Rule("route = 'elsevier_entitlement'", "entitlement_pdf",
         "PDF comes through the same entitled key as the XML"),
    Rule(_route_in("jats_native_open", "springer_oa_api") + " AND pdf_url IS NOT NULL",
         "oa_pdf",
         "OpenAlex knows an open PDF URL"),
    Rule(_route_in("jats_native_open", "springer_oa_api"), "publisher_urls",
         "No PDF URL: fall back to the figure URLs inside the publisher XML"),
    Rule(_route_in("gated_commercial", "repository", "convert")
         + " AND (pdf_url IS NOT NULL OR has_pdf)", "pdf_extract_laneB",
         "Lane B: figures are extracted from the PDF, an attended step"),
    Rule("route = 'out_of_scope'", "na",
         "Not ours to fetch"),
]
ASSET_ROUTE_DEFAULT = "none"  # explicit escalation flag, never a silent gap


# ---------------------------------------------------------------------------
# lane — the coarse cost tier, rolled up FROM route.
#
# The open/free routes are what lift JATS-native and Springer papers out of the
# expensive convert lane; that roll-up is the whole point of the router.
# ---------------------------------------------------------------------------

LANE_RULES = [
    Rule(_route_in("pmc", "scoap3_aps", "scoap3_jhep", "jats_native_open",
                   "springer_oa_api"), "C_ingest",
         "Publisher XML is already JATS — crosswalk it"),
    Rule(_route_in("scoap3_elsevier", "scoap3_other", "elsevier_entitlement"),
         "Cprime_transform",
         "Publisher XML is a foreign vocabulary — transform, then crosswalk"),
    Rule(_route_in("gated_commercial", "repository", "convert"), "B_convert",
         "No open XML at all — convert the published version of record"),
]
LANE_DEFAULT = "out_of_scope"


# ---------------------------------------------------------------------------
# disposition — what a HUMAN must do with each paper, driven by the VoR licence.
#
# The whole-corpus decision that completes the four-lane model:
#   automated    harvest handles it end to end (open XML: ingest or transform)
#   convert_vor  the VoR is REUSABLE but has no open XML, so convert the published
#                gold version (Lane B)
#   source_aam   the VoR is NOT reusable, so the only Green-OA path is the author's
#                Accepted Manuscript through the workstation (Lane A)
#
# source_aam is a RIGHTS decision and the cataloguer confirms it per paper.
# ---------------------------------------------------------------------------

DISPOSITION_RULES = [
    Rule("license = 'cc-by' AND " + "lane IN ('C_ingest', 'Cprime_transform')", "automated",
         "Open XML under CC-BY: the pipeline can finish this alone"),
    Rule("license IN (" + ", ".join(f"'{l}'" for l in REUSABLE_LICENCES) + ")",
         "convert_vor",
         "Reusable licence but no open XML -> convert the VoR (Lane B)"),
]
DISPOSITION_DEFAULT = "source_aam"


# The order in which the columns are derived. Later columns read earlier ones
# (asset_route, lane and disposition all depend on route), so this is a dependency
# order, not a preference.
DERIVATIONS = [
    ("scoap3", SCOAP3_RULES, SCOAP3_DEFAULT),
    ("route", ROUTE_RULES, ROUTE_DEFAULT),
    ("route_access",
     [Rule(f"route = '{r}'", a, "") for r, a in ROUTE_ACCESS.items()],
     ROUTE_ACCESS_DEFAULT),
    ("asset_route", ASSET_ROUTE_RULES, ASSET_ROUTE_DEFAULT),
    ("lane", LANE_RULES, LANE_DEFAULT),
    ("disposition", DISPOSITION_RULES, DISPOSITION_DEFAULT),
]
