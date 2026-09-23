#!/usr/bin/env python3
"""Per-route XML fetcher — turns the DuckDB lane router's decision into a download.

Reads works_YYYY.duckdb (route/route_access/pmcid columns), dispatches each paper to the
adapter for its route, and writes fetched XML to fetched/{route}/{work_id}.xml plus a
manifest. Bibliographic identifiers only ever leave the machine; per-work licence was
already verified by the router (route is only set for cc-by).

Adapters (one per route):
  pmc               Europe PMC fullTextXML (keyless) with NCBI efetch fallback
  scoap3_aps /      SCOAP3 repo API by DOI -> direct S3 xml
  scoap3_other
  springer_oa_api   Springer Nature OpenAccess JATS API (free key in springer_key.txt)
  jats_native_open  per-publisher URL conventions (PLOS, eLife, F1000-family, PeerJ,
                    Royal Society, MDPI, Frontiers, Copernicus) — honest failure notes
                    where a publisher bot-gates
  elsevier_entitlement  ScienceDirect Article Retrieval (key in elsevier_key.txt;
                    keyless returns a metadata stub, which we detect and reject)

Usage:
  python fetch_router.py --doi 10.3390/nano15010078          # one paper, route auto-looked-up
  python fetch_router.py --route jats_native_open --limit 5  # sample a route
  python fetch_router.py --route pmc --limit 3 --year 2025
"""
import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MAILTO = "scott.taylor@manchester.ac.uk"
UA = {"User-Agent": "MORE-harvest/0.1 (mailto:%s)" % MAILTO}
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def _get(url, headers=None, timeout=90):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def _key(name):
    p = os.path.join(HERE, name)
    return open(p, encoding="utf-8").read().strip() if os.path.isfile(p) else None


def _is_jats(data):
    head = data[:2000].decode("utf-8", "replace")
    return "<article" in head and ("JATS" in head or "jats" in head or
                                   "<front" in data[:6000].decode("utf-8", "replace")
                                   or "article-meta" in data[:6000].decode("utf-8", "replace"))


# ------------------------------------------------------------------ adapters
def fetch_pmc(row):
    pmcid = row.get("pmcid")
    if not pmcid:
        return None, "no pmcid on record"
    u = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    try:
        data = _get(u)
        if data[:100].lstrip().startswith(b"<"):
            return data, f"europepmc fullTextXML"
    except Exception as e:
        pass
    num = pmcid.replace("PMC", "")
    u2 = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" +
          urllib.parse.urlencode({"db": "pmc", "id": num, "tool": "MORE", "email": MAILTO}))
    try:
        data = _get(u2)
        return (data, "ncbi efetch") if b"<article" in data[:5000] else (None, "efetch returned no article")
    except Exception as e:
        return None, f"pmc fetch failed: {str(e)[:60]}"


# SCOAP3's search is CASE-SENSITIVE on the DOI, and OpenAlex lowercases DOIs. APS DOI
# casing is deterministic, so rebuild it (physrevlett -> PhysRevLett etc.).
_APS_CASE = {"physrevlett": "PhysRevLett", "physrevd": "PhysRevD", "physrevc": "PhysRevC",
             "physrevx": "PhysRevX", "revmodphys": "RevModPhys"}


def _scoap3_doi_variants(doi):
    yield doi
    m = re.match(r"(10\.1103)/([a-z]+)\.(.+)$", doi)
    if m and m.group(2) in _APS_CASE:
        yield f"{m.group(1)}/{_APS_CASE[m.group(2)]}.{m.group(3)}"
    m = re.match(r"(10\.1007)/jhep(\d+)\((\d+)\)(\d+)$", doi)   # Springer JHEP
    if m:
        yield f"{m.group(1)}/JHEP{m.group(2)}({m.group(3)}){m.group(4)}"


def fetch_scoap3(row):
    doi = row["doi"]
    try:
        # the API has an exact (case-sensitive) doi= param — far better than fuzzy search=
        for cand in _scoap3_doi_variants(doi):
            u = ("https://repo.scoap3.org/api/records?" +
                 urllib.parse.urlencode({"doi": cand, "size": "2"}))
            try:
                r = json.loads(_get(u))
            except urllib.error.HTTPError as e:
                if e.code == 403:            # polite backoff on rate limit, one retry
                    time.sleep(5)
                    r = json.loads(_get(u))
                else:
                    raise
            for rec in (r.get("hits", {}) or {}).get("hits", []):
                dois = [d.get("value", "").lower() for d in rec.get("metadata", {}).get("dois", [])]
                if doi.lower() in dois:
                    for f in rec["metadata"].get("_files", []):
                        if f.get("filetype") == "xml":
                            data = _get(f["file"])
                            return _resolve_bodyref(data)
            time.sleep(0.5)
        return None, "doi not found in scoap3"
    except Exception as e:
        return None, f"scoap3 failed: {str(e)[:60]}"


def _resolve_bodyref(data):
    """Springer (JHEP/EPJC) deposits an A++ HEADER whose <BodyRef> points at the full-text
    JATS on the publisher server. APS deposits full JATS directly. Detect the header-only A++
    case and follow the BodyRef to the real JATS; otherwise return the XML as-is."""
    head = data[:400].decode("utf-8", "replace")
    if "<article" in head:                     # already JATS (APS, or resolved)
        return data, "scoap3 s3 (jats)"
    m = re.search(rb'<BodyRef[^>]*FileRef="([^"]+\.ft\.xml)"', data)
    if m:
        url = m.group(1).decode()
        try:
            ft = _get(url)
            if b"<article" in ft[:400]:
                return ft, f"scoap3 A++ -> full-text JATS ({url.split('/')[-1]})"
        except Exception as e:
            return None, f"BodyRef fetch failed: {str(e)[:50]}"
    return data, "scoap3 s3 (A++ header only, no BodyRef JATS)"


def fetch_springer_oa(row):
    key = _key("springer_key.txt")
    if not key:
        return None, "needs free Springer key -> https://dev.springernature.com (put in springer_key.txt)"
    u = ("https://api.springernature.com/openaccess/jats?" +
         urllib.parse.urlencode({"q": f"doi:{row['doi']}", "api_key": key}))
    try:
        data = _get(u)
        return (data, "springer oa api") if b"<article" in data else (None, "no article in response")
    except Exception as e:
        return None, f"springer api failed: {str(e)[:60]}"


def fetch_elsevier(row):
    key = _key("elsevier_key.txt")
    if not key:
        return None, "needs Elsevier API key + entitlement (put in elsevier_key.txt)"
    u = f"https://api.elsevier.com/content/article/doi/{urllib.parse.quote(row['doi'])}?apiKey={key}"
    try:
        data = _get(u, headers={**UA, "Accept": "text/xml"})
        if b"<ce:para" in data or b"xocs:rawtext" in data or len(data) > 20000:
            return data, "elsevier article api"
        return None, f"stub only ({len(data)}B) - key lacks full-text entitlement?"
    except Exception as e:
        return None, f"elsevier api failed: {str(e)[:60]}"


def _native_urls(row):
    """Yield candidate XML URLs for JATS-native open publishers."""
    doi, pub = row["doi"], (row.get("publisher") or "").lower()
    suffix = doi.split("/", 1)[1] if "/" in doi else doi
    if doi.startswith("10.1371/"):        # PLOS
        yield (f"https://journals.plos.org/plosone/article/file?id={doi}&type=manuscript", UA)
    if doi.startswith("10.7554/"):        # eLife
        m = re.search(r"elife\.(\d+)", doi, re.I)
        if m:
            yield (f"https://elifesciences.org/articles/{m.group(1)}.xml", UA)
    if doi.startswith(("10.12688/", "10.21956/")):   # F1000 family
        yield (f"https://f1000research.com/extapi/article/xml?doi={doi}", UA)
    if doi.startswith("10.7717/"):        # PeerJ
        m = re.search(r"peerj\.(\d+)", doi, re.I)
        if m:
            yield (f"https://peerj.com/articles/{m.group(1)}.xml", BROWSER_UA)
    if doi.startswith("10.1098/"):        # Royal Society
        yield (f"https://royalsocietypublishing.org/doi/full-xml/{doi}", BROWSER_UA)
    if doi.startswith("10.3390/"):        # MDPI (bot-gated for plain clients; try browser UA)
        yield (f"https://www.mdpi.com/article/{doi}/xml", BROWSER_UA)
    if doi.startswith("10.3389/"):        # Frontiers: needs the journal slug in the path
        j = (row.get("journal") or "").lower()
        slug = re.sub(r"^frontiers (in|of) ", "", j).strip().replace(" ", "-")
        if slug:
            yield (f"https://www.frontiersin.org/journals/{slug}/articles/{doi}/xml", BROWSER_UA)
    if doi.startswith("10.5194/"):        # Copernicus: article XML beside landing page
        yield (f"https://doi.org/{doi}", None)   # resolve then append .xml — handled below


def fetch_jats_native(row):
    tried = []
    for u, hdrs in _native_urls(row):
        if hdrs is None:
            continue   # copernicus special-case not implemented in v0.1
        try:
            data = _get(u, headers=hdrs)
            if _is_jats(data):
                return data, u.split("/")[2]
            tried.append(f"{u.split('/')[2]}: not JATS ({len(data)}B)")
        except Exception as e:
            tried.append(f"{u.split('/')[2]}: {getattr(e,'code',str(e)[:30])}")
    return None, "; ".join(tried) or "no URL pattern for this publisher (see landscape note)"


# ---- Lane B (convert_vor): gated_commercial / repository / convert -------------------
# No open XML exists for these. For the works OpenAlex has GROBID-parsed (has_grobid),
# fetch the TEI from the content service; ingest_one's TEI branch (tei_to_jats ->
# crosswalk -> gates + the [2e] fidelity gate) does the rest. The PDF fetched beside it
# (pdf_laneb) is THE SAME archived file GROBID parsed, so the fidelity gate's TEI/PDF
# pairing is version-consistent by construction — never a publisher-site fetch that
# might be a different version. Works without TEI stay declined (true PDF-only
# conversion is unbuilt); wired 2026-07-15 with the Enterprise key.
LANEB_TEI_ROUTES = ("gated_commercial", "repository", "convert")


def fetch_laneb_tei(row):
    if not row.get("has_grobid"):
        return None, "no GROBID TEI in OpenAlex (true PDF-only conversion unbuilt)"
    key = _key("openalex_key.txt")
    if not key:
        return None, "needs openalex_key.txt"
    u = f"https://content.openalex.org/works/{row['id']}.grobid-xml?api_key={key}"
    try:
        data = _get(u, timeout=120)
        if b"tei-c.org/ns/1.0" in data[:800]:
            return data, "openalex content grobid-xml"
        return None, f"content api returned non-TEI ({len(data)}B)"
    except Exception as e:
        return None, f"content api tei failed: {str(e)[:60]}"


def pdf_laneb(row):
    key = _key("openalex_key.txt")
    if not key:
        return None, "needs openalex_key.txt"
    u = f"https://content.openalex.org/works/{row['id']}.pdf?api_key={key}"
    try:
        data = _get(u, timeout=180)
        return (data, "openalex content pdf") if _is_pdf(data) else (None, "not a pdf")
    except Exception as e:
        return None, f"content api pdf failed: {str(e)[:60]}"


ADAPTERS = {
    "pmc": fetch_pmc,
    "scoap3_aps": fetch_scoap3,
    "scoap3_other": fetch_scoap3,
    "scoap3_jhep": fetch_scoap3,       # JHEP: fetch_scoap3 resolves the A++ BodyRef -> full-text JATS
    "scoap3_elsevier": fetch_scoap3,   # PLB/NPB: fetched here, then elsevier_to_jats in ingest_one
    "springer_oa_api": fetch_springer_oa,
    "jats_native_open": fetch_jats_native,
    "elsevier_entitlement": fetch_elsevier,
    "gated_commercial": fetch_laneb_tei,
    "repository": fetch_laneb_tei,
    "convert": fetch_laneb_tei,
}


# ------------------------------------------------------- asset (PDF) fetchers
# Asset capture is NON-NEGOTIABLE (design principle 2026-07-04): XML never carries its
# figures, so each route fetches its route-native PDF as the universal asset source.
def _is_pdf(data):
    return data[:5] == b"%PDF-"


def pdf_pmc(row):
    if not row.get("pmcid"):
        return None, "no pmcid"
    u = f"https://europepmc.org/articles/{row['pmcid']}?pdf=render"
    try:
        data = _get(u, headers=BROWSER_UA, timeout=120)
        return (data, "europepmc render") if _is_pdf(data) else (None, "not a pdf")
    except Exception as e:
        return None, f"epmc pdf failed: {str(e)[:50]}"


def pdf_scoap3(row):
    doi = row["doi"]
    try:
        for cand in _scoap3_doi_variants(doi):
            u = ("https://repo.scoap3.org/api/records?" +
                 urllib.parse.urlencode({"doi": cand, "size": "2"}))
            r = json.loads(_get(u))
            for rec in (r.get("hits", {}) or {}).get("hits", []):
                dois = [d.get("value", "").lower() for d in rec.get("metadata", {}).get("dois", [])]
                if doi.lower() in dois:
                    for f in rec["metadata"].get("_files", []):
                        if f.get("filetype") == "pdf":
                            data = _get(f["file"], timeout=180)
                            return (data, "scoap3 s3") if _is_pdf(data) else (None, "not a pdf")
            time.sleep(0.5)
        return None, "no pdf in scoap3 record"
    except Exception as e:
        return None, f"scoap3 pdf failed: {str(e)[:50]}"


def pdf_generic(row):
    """OpenAlex-recorded OA pdf_url first, then per-publisher conventions."""
    cands = []
    if row.get("pdf_url"):
        cands.append((row["pdf_url"], BROWSER_UA))
    doi = row["doi"]
    if doi.startswith("10.3389/"):
        j = (row.get("journal") or "").lower()
        slug = re.sub(r"^frontiers (in|of) ", "", j).strip().replace(" ", "-")
        if slug:
            cands.append((f"https://www.frontiersin.org/journals/{slug}/articles/{doi}/pdf", BROWSER_UA))
    if doi.startswith(("10.1007/", "10.1038/", "10.1186/")):
        cands.append((f"https://link.springer.com/content/pdf/{doi}.pdf", BROWSER_UA))
    tried = []
    for u, hdrs in cands:
        try:
            data = _get(u, headers=hdrs, timeout=120)
            if _is_pdf(data):
                return data, u.split("/")[2]
            tried.append(f"{u.split('/')[2]}: not pdf")
        except Exception as e:
            tried.append(f"{u.split('/')[2]}: {getattr(e, 'code', str(e)[:25])}")
    return None, "; ".join(tried) or "no pdf source known"


PDF_FETCHERS = {
    "pmc": pdf_pmc,
    "scoap3_aps": pdf_scoap3,
    "scoap3_other": pdf_scoap3,
    "scoap3_jhep": pdf_scoap3,
    "scoap3_elsevier": pdf_scoap3,
    "springer_oa_api": pdf_generic,
    "jats_native_open": pdf_generic,
    "elsevier_entitlement": pdf_generic,   # entitlement XML route; PDF via oa link if any
    "gated_commercial": pdf_laneb,         # Lane B: the SAME archived file GROBID parsed
    "repository": pdf_laneb,
    "convert": pdf_laneb,
}


# ------------------------------------------------------------------ driver
def rows_for(args):
    import duckdb
    con = duckdb.connect(os.path.join(HERE, f"works_{args.year}.duckdb"), read_only=True)
    cols = "id, doi, pmcid, publisher, journal, route, route_access, pdf_url, has_grobid"
    if args.doi:
        q = f"SELECT {cols} FROM works WHERE lower(doi)=lower(?)"
        rs = con.execute(q, [args.doi]).fetchall()
    else:
        q = f"SELECT {cols} FROM works WHERE route=? AND doi IS NOT NULL"
        # Lane B is TEI-gated: works without a GROBID parse have no conversion path yet,
        # so don't let them consume --limit slots on guaranteed declines
        if args.route in LANEB_TEI_ROUTES:
            q += " AND has_grobid"
        q += f" ORDER BY id LIMIT {args.limit}"
        rs = con.execute(q, [args.route]).fetchall()
    names = ["id", "doi", "pmcid", "publisher", "journal", "route", "route_access",
             "pdf_url", "has_grobid"]
    return [dict(zip(names, r)) for r in rs]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--doi")
    ap.add_argument("--route", choices=sorted(ADAPTERS))
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--year", default="2025")
    ap.add_argument("--no-pdf", action="store_true", help="skip the asset (PDF) fetch")
    args = ap.parse_args()
    if not args.doi and not args.route:
        sys.exit("give --doi or --route")
    rows = rows_for(args)
    if not rows:
        sys.exit("no matching works in the DB")
    manifest = []
    ok = 0
    for row in rows:
        route = row["route"]
        fn = ADAPTERS.get(route)
        if fn is None:
            print(f"  {row['id']}  route={route}: no adapter (by design: gated/repository/convert)")
            continue
        # already fetched -> don't hit the API again (batch runs walk the same
        # ORDER BY id prefix every time; skipping makes --limit N mean N total).
        # Lane B's unit is the TEI+PDF PAIR (the fidelity gate needs both): an xml
        # with a missing pdf falls through to complete its pair, never refetching
        # the xml. Other routes keep their existing xml-only skip.
        xml_p = os.path.join(HERE, "fetched", route, f"{row['id']}.xml")
        pdf_p = xml_p[:-4] + ".pdf"
        have_xml = os.path.isfile(xml_p)
        pair_incomplete = (route in LANEB_TEI_ROUTES and not args.no_pdf
                           and not os.path.isfile(pdf_p))
        if have_xml and not pair_incomplete:
            ok += 1
            continue
        data, note = (True, "already fetched") if have_xml else fn(row)
        rec = {**{k: row[k] for k in ("id", "doi", "route", "publisher")}, "note": note}
        d = os.path.join(HERE, "fetched", route)
        if data is True:                      # xml already on disk; completing the pair
            rec["path"] = os.path.relpath(xml_p, HERE)
            ok += 1
        elif data:
            os.makedirs(d, exist_ok=True)
            open(xml_p, "wb").write(data)
            rec["path"] = os.path.relpath(xml_p, HERE)
            rec["bytes"] = len(data)
            ok += 1
            print(f"  OK  {row['id']} [{route}] xml {len(data):>9,}B via {note}")
        else:
            print(f"  --  {row['id']} [{route}] XML FAILED: {note}")
        # asset capture (non-negotiable): route-native PDF beside the XML
        if data and not args.no_pdf and not os.path.isfile(pdf_p):
            pfn = PDF_FETCHERS.get(route)
            pdata, pnote = pfn(row) if pfn else (None, "no pdf fetcher")
            rec["asset_note"] = pnote
            if pdata:
                open(pdf_p, "wb").write(pdata)
                rec["asset_path"] = os.path.relpath(pdf_p, HERE)
                rec["asset_bytes"] = len(pdata)
                print(f"      + pdf {len(pdata):>9,}B via {pnote}")
            else:
                rec["asset_status"] = "MISSING"
                print(f"      ! ASSET MISSING: {pnote}")
        manifest.append(rec)
        time.sleep(0.4)
    mp = os.path.join(HERE, "fetched", "manifest.json")
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    old = json.load(open(mp, encoding="utf-8")) if os.path.isfile(mp) else []
    json.dump(old + manifest, open(mp, "w", encoding="utf-8"), indent=1)
    print(f"\n{ok}/{len(rows)} fetched -> fetched/ (manifest appended)")


if __name__ == "__main__":
    main()
