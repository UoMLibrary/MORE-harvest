---
type: source
tags: [harvest, source, landscape]
updated: 2026-07-04
---

# The Full Source Landscape

> [!abstract] The scan
> We swept the whole world of "who gives out article XML" (2026) to find sources beyond
> [PubMed Central — The Biomedical Half](PubMed%20Central%20—%20The%20Biomedical%20Half.md) and [SCOAP3 — The Physics Half](SCOAP3%20—%20The%20Physics%20Half.md). The big lesson: there
> is **no single universal source** — it's publisher-by-publisher — but there are more open routes
> than we thought, and one crucial fact reframes everything.

## The reframe: PMC is cross-publisher, not just biomedical

The most important finding. The PubMed Central open-access subset **normalises articles from many
publishers into JATS** — MDPI, Frontiers, Oxford, Wiley-OA, Springer-OA, RSC and ACS open articles
all land there, not just biomedical ones. So our existing `in_pmc` flag is already a **much broader
ingest signal** than "the biomedical half" — it's the first place to check for *any* publisher. Its
harvestable feed is the OAI-PMH `pmc-open` set (`metadataPrefix=pmc`) plus the AWS/FTP bulk packages.

## The open, no-negotiation routes (real JATS, free)

These are pure [Lane C — Ingest](../The%20Four%20Lanes/Lane%20C%20—%20Ingest.md) and need no subscription, mostly no key:

- **JATS-native open publishers** — PLOS, eLife, F1000 (+ Wellcome Open Research, Gates Open
  Research), MDPI, Copernicus/EGU, Pensoft, PeerJ, Royal Society Open Science. Uniformly CC-BY, whole-
  corpus lists or trivial per-article URLs. Two schema quirks to expect: Copernicus emits the NLM
  *archiving* flavour, Pensoft emits *TaxPub* — both real JATS, slightly divergent.
- **Springer Nature Open Access JATS API** — a genuine free-key API (7,500/day) returning real JATS
  for BMC and SpringerOpen CC-BY content. The best direct route to a big commercial name.

## The gated routes (real XML, but need our paid entitlement)

UoM's subscriptions could unlock these — a **policy/negotiation question, not just a technical one**:

- **Elsevier ScienceDirect API** — full-text XML for CC-BY (and subscribed) articles, but needs an
  API key + institutional token, and it's Elsevier's own `xocs`/`ja` schema (**not JATS**) → a
  [Lane C′ — Transform](../The%20Four%20Lanes/Lane%20C′%20—%20Transform.md) with a one-time converter. This is the single **biggest** convertible chunk
  (746 of our 2025 Lane-B papers).
- **Wiley** — the awkward one. Its dedicated text-mining API returns **PDF only**; it *advertises* XML
  links in Crossref but they point at entitlement-gated Wiley-schema XML, on-network only. No open
  CC-BY feed.
- **OUP, Cambridge, Taylor & Francis, SAGE, IOP, RSC, ACS, BMJ** — all *hold* JATS but release it only
  by registration / TDM request / SFTP agreement. Not openly crawlable. (BMJ is also often CC-BY-**NC**,
  not CC-BY.)

## Discovery layers (not sources — they point, they don't hold)

- **Crossref `link[]`** — ~8 million works advertise an XML text-mining link. Useful to *discover and
  route*, but the target is usually gated and Crossref never hosts the text. Our live probe confirmed
  most big publishers advertise only a landing page or PDF here.
- **DOAJ / CORE / OpenAIRE / Internet Archive Scholar** — metadata or plain-text/PDF only. Good for
  *finding* CC-BY journals, never for article-body JATS.

## Dead ends worth knowing

- **OpenAlex XML** is GROBID (machine-made), not publisher JATS — see [OpenAlex — The Index](OpenAlex%20—%20The%20Index.md).
- **Hindawi's** once-open JATS corpus is retired into Wiley; only frozen archives remain.
- There is **no central registry** of open-JATS publishers — the de-facto list runs through PMC OA +
  the known JATS-native platforms.

## What this actually buys us — the Lane-B pile, re-examined

Of the 3,291 papers currently in [Lane B — True Conversion](../The%20Four%20Lanes/Lane%20B%20—%20True%20Conversion.md) for 2025:

| Slice | Papers | New route |
|---|---|---|
| JATS-native open publishers (MDPI, Frontiers, PLOS, PeerJ, RoySoc…) | ~183 | → Lane C, open, no key |
| Springer family (Springer, BMC, Nature-OA) | ~211 | → Lane C via Springer OA API (free key) |
| **Elsevier** | **746** | → Lane C′ via ScienceDirect entitlement + one transform |
| Gated commercials (Wiley, OUP, T&F, SAGE, ACS, Cambridge, IEEE, IOP, RSC…) | ~1,100 | entitlement negotiation, else convert |
| Repository/other (Figshare, CERN, Zenodo, unknown) | ~575 | often not journal VoRs — case-by-case |
| Genuinely unstructured, no route | remainder | stays true conversion |

> [!tip] The honest headline
> ~**400 papers** move from convert → ingest *immediately* on open/free routes. Another ~**750**
> (Elsevier) move if we use our ScienceDirect entitlement and write one transform. A further ~1,100
> sit behind commercial entitlement doors that are a *negotiation*, not a scrape. The stubborn true-
> conversion core is real but smaller than the raw Lane-B number suggests.

---
Prev: [SCOAP3 — The Physics Half](SCOAP3%20—%20The%20Physics%20Half.md) · Related: [The Four Lanes](../The%20Four%20Lanes/The%20Four%20Lanes.md) · *Facts and Figures (2025)*
