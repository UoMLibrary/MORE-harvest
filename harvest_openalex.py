#!/usr/bin/env python3
"""Small OpenAlex experiments for the CC-BY VoR programme (metadata-first, cheap).

Sends ONLY bibliographic queries (institution, dates, licence, counts) - never any
manuscript content. Metadata API calls ride the org Member+ key (1M calls/day,
Bearer header via get()); content-service downloads are per-file and also keyed.

Key handling: put the key in the environment variable OPENALEX_API_KEY, or in a
one-line file `openalex_key.txt` beside this script. The key file is git-ignored
by the workspace-root repo (`*_key.txt`) - NEVER paste the key into a chat or
commit it anywhere.

Subcommands:
  landscape   - the UoM CC-BY landscape: counts, journals, licences, versions,
                content availability. Saves raw JSON to harvest/ for DuckDB.
  status      - check the API key (account/credit info where available).
  fetch-one   - download PDF + GROBID TEI for ONE work by DOI (needs key; $0.02).
"""
import argparse
import glob
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.openalex.org"
MAILTO = "scott.taylor@manchester.ac.uk"          # polite-pool identification


def api_key():
    k = os.environ.get("OPENALEX_API_KEY")
    if not k:
        p = os.path.join(HERE, "openalex_key.txt")
        if os.path.isfile(p):
            k = open(p, encoding="utf-8").read().strip()
    return k or None


def get(path, **params):
    params.setdefault("mailto", MAILTO)
    headers = {"User-Agent": "MORE-harvest/0.1"}
    k = api_key()
    if k:
        # The UoM org key is Bearer-auth only; as an api_key param it is
        # ignored and the call falls into the (budget-capped) keyless pool.
        headers["Authorization"] = "Bearer " + k
    url = f"{API}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def save(name, obj):
    d = os.path.join(HERE, "harvest")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    return p


def resolve_institution(query="University of Manchester"):
    r = get("/institutions", search=query, per_page="3")
    top = r["results"][0]
    return top["id"].rsplit("/", 1)[-1], top["display_name"], top.get("works_count")


def landscape(args):
    iid, iname, iworks = resolve_institution()
    print(f"institution: {iname} ({iid}), {iworks:,} works total\n")
    base = (f"authorships.institutions.lineage:{iid},"
            f"type:article,from_publication_date:{args.since}-01-01")

    def count(filt, label):
        try:
            n = get("/works", filter=filt, per_page="1")["meta"]["count"]
            print(f"{label:58s} {n:>8,}")
            return n
        except Exception as e:
            print(f"{label:58s} ERROR {str(e)[:60]}")
            return None

    print(f"=== UoM journal articles since {args.since} ===")
    count(base, "all")
    count(base + ",open_access.is_oa:true", "open access")
    ccby = count(base + ",best_oa_location.license:cc-by", "CC-BY (best OA location)")
    count(base + ",best_oa_location.license:cc-by,best_oa_location.version:publishedVersion",
          "CC-BY AND hosted copy is the VoR (publishedVersion)")
    count(base + ",best_oa_location.license:cc-by,has_content.grobid_xml:true",
          "CC-BY with OpenAlex GROBID TEI available")
    count(base + ",best_oa_location.license:cc-by,has_content.pdf:true",
          "CC-BY with OpenAlex-hosted PDF available")

    print("\n=== group-bys over the CC-BY slice (saved to harvest/) ===")
    ccby_filter = base + ",best_oa_location.license:cc-by"
    for gb, label, fname in [
        ("primary_location.source.id", "top journals", "groupby_journals.json"),
        ("best_oa_location.version", "hosted-copy version mix", "groupby_versions.json"),
        ("best_oa_location.license", "licence mix (OA slice)", "groupby_licenses.json"),
        ("publication_year", "by year", "groupby_years.json"),
    ]:
        try:
            filt = (base + ",open_access.is_oa:true") if gb.endswith("license") else ccby_filter
            r = get("/works", filter=filt, group_by=gb, per_page="200")
            groups = r.get("group_by", [])
            save(fname, {"filter": filt, "group_by": gb, "groups": groups})
            print(f"\n-- {label} --")
            for g in groups[:10]:
                print(f"  {str(g.get('key_display_name') or g.get('key'))[:60]:62s} "
                      f"{g['count']:>7,}")
        except Exception as e:
            print(f"\n-- {label} -- ERROR {str(e)[:80]}")
    print("\nraw group-by JSON saved in harvest/ (DuckDB-readable)")


def status(args):
    k = api_key()
    if not k:
        sys.exit("no API key found (set OPENALEX_API_KEY or create openalex_key.txt)")
    try:
        r = get("/works", filter="doi:10.7717/peerj.4375", per_page="1")
        print("key accepted; sample lookup ok:", r["results"][0]["display_name"][:60])
    except Exception as e:
        print("key check failed:", e)


def fetch_one(args):
    if not api_key():
        sys.exit("content download needs the API key (openalex_key.txt or env)")
    doi = args.doi.lower().removeprefix("https://doi.org/")
    r = get("/works/" + urllib.parse.quote(f"doi:{doi}"))
    wid = r["id"].rsplit("/", 1)[-1]
    print(f"work {wid}: {r['display_name'][:70]}")
    loc = r.get("best_oa_location") or {}
    hc = r.get("has_content") if isinstance(r.get("has_content"), dict) else {}
    print(f"  best OA location: version={loc.get('version')} license={loc.get('license')}")
    print(f"  has_content: pdf={hc.get('pdf')} grobid_xml={hc.get('grobid_xml')}")
    if loc.get("license") != "cc-by":
        print(f"  ** NOT cc-by ({loc.get('license')}) — NOT eligible for the CC-BY VoR "
              "programme (licence must be verified per work, not assumed) **")
        if not getattr(args, "force", False):
            print("  refusing to download non-CC-BY content (this tool acquires CC-BY VoRs only)")
            return
    d = os.path.join(HERE, "harvest", "content")
    os.makedirs(d, exist_ok=True)
    # PDF: confirmed predictable endpoint. TEI: has NO simple content URL — the flag
    # has_content.grobid_xml can be true while content.openalex.org/{id}.<ext> 404s;
    # the GROBID TEI is delivered only via the official `openalex download --content xml`
    # CLI (resolves a join-key/signed URL from the bulk archive). Wire that in later.
    url = f"https://content.openalex.org/works/{wid}.pdf?api_key={api_key()}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MORE-harvest/0.1"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        p = os.path.join(d, f"{wid}.pdf")
        open(p, "wb").write(data)
        print(f"  downloaded pdf: {len(data):,} bytes -> {p}")
    except Exception as e:
        print(f"  pdf: FAILED ({str(e)[:80]})")
    if hc.get("grobid_xml"):
        tei = fetch_grobid_tei(wid)
        if tei:
            p = os.path.join(d, f"{wid}.grobid.tei.xml")
            open(p, "wb").write(tei)
            print(f"  downloaded grobid TEI: {len(tei):,} bytes -> {p}")
        else:
            print("  grobid TEI flagged present but fetch failed")


def fetch_grobid_tei(work_id):
    """Fetch the GROBID TEI for a work. The content endpoint uses the '.grobid-xml'
    extension (NOT .tei.xml / .grobid.xml) and serves gzip (Content-Type
    application/gzip, no Content-Encoding header), so we gunzip explicitly."""
    import gzip
    wid = work_id.rsplit("/", 1)[-1]
    url = f"https://content.openalex.org/works/{wid}.grobid-xml?api_key={api_key()}"
    req = urllib.request.Request(url, headers={"User-Agent": "MORE-harvest/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    except Exception:
        return None
    data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    return data if data[:5] == b"<?xml" else None


WORK_SELECT = ("id,doi,display_name,publication_year,publication_date,type,"
               "primary_location,best_oa_location,open_access,has_content,locations")


def _pmc(w):
    """Return (in_pmc, pmcid) from any PubMed Central location. OpenAlex ids.pmcid is
    unreliable (empty) and the has_pmcid filter is broken, but the PMC *location* is
    present per-record and its id/urls carry the numeric PMCID."""
    for loc in w.get("locations", []) or []:
        src = (loc.get("source") or {}).get("display_name") or ""
        # Match PubMed Central specifically — bare "central" also matched "BioMed Central",
        # so every BMC paper was flagged in_pmc with no extractable PMCID, then the pmc route
        # (which wins on priority) dead-ended instead of using its working springer_oa_api route.
        if "pubmed central" in src.lower() or "pubmedcentral" in (loc.get("id") or ""):
            num = ""
            m = re.search(r"(\d{6,})", loc.get("id") or "")
            if not m:
                m = re.search(r"PMC?(\d{6,})", (loc.get("landing_page_url") or "")
                              + " " + (loc.get("pdf_url") or ""))
            if m:
                num = m.group(1)
            return True, ("PMC" + num if num else None)
    return False, None


def _flat(w):
    pl = w.get("primary_location") or {}
    src = pl.get("source") or {}
    oa = w.get("open_access") or {}
    boa = w.get("best_oa_location") or {}
    hc = w.get("has_content") if isinstance(w.get("has_content"), dict) else {}
    in_pmc, pmcid = _pmc(w)
    return {
        "in_pmc": in_pmc,
        "pmcid": pmcid,
        "id": w["id"].rsplit("/", 1)[-1],
        "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
        "title": w.get("display_name"),
        "year": w.get("publication_year"),
        "date": w.get("publication_date"),
        "type": w.get("type"),
        "journal": src.get("display_name"),
        "source_type": src.get("type"),
        "publisher": src.get("host_organization_name"),
        "is_oa": oa.get("is_oa"),
        "oa_status": oa.get("oa_status"),
        "license": boa.get("license"),
        "version": boa.get("version"),
        "pdf_url": boa.get("pdf_url"),
        "has_pdf": bool(hc.get("pdf")),
        "has_grobid": bool(hc.get("grobid_xml")),
    }


def harvest_year(args):
    iid, iname, _ = resolve_institution()
    # scope: primary research articles AND reviews (2026-07-14 — reviews are real
    # UoM outputs; they route by licence like anything else). Still excludes the
    # non-output types (editorial, letter, erratum, dataset, paratext…).
    filt = (f"authorships.institutions.lineage:{iid},type:article|review,"
            f"publication_year:{args.year}")
    print(f"harvesting {iname} articles + reviews for {args.year} (metadata only)...")
    d = os.path.join(HERE, "harvest", f"works_{args.year}")
    os.makedirs(d, exist_ok=True)
    # Clear stale pages from a previous harvest of this year: a re-harvest that yields fewer
    # pages would otherwise leave orphaned page_*.json behind, and build_db globs them all —
    # producing duplicate/stale work rows and inflated route counts.
    for old in glob.glob(os.path.join(d, "page_*.json")):
        os.remove(old)
    cursor, page, total = "*", 0, 0
    while cursor:
        r = get("/works", filter=filt, select=WORK_SELECT, per_page="200", cursor=cursor)
        results = r.get("results", [])
        if not results:
            break
        page += 1
        with open(os.path.join(d, f"page_{page:04d}.json"), "w", encoding="utf-8") as f:
            json.dump([_flat(w) for w in results], f)
        total += len(results)
        cursor = r["meta"].get("next_cursor")
        count = r["meta"].get("count")
        print(f"  page {page}: +{len(results)} ({total}/{count})", end="\r")
    print(f"\nsaved {total} work records to {d} ({page} pages, "
          f"~${page * 0.0001:.4f} in list/filter calls)")


def build_db(args):
    d = os.path.join(HERE, "harvest", f"works_{args.year}")
    pages = sorted(glob.glob(os.path.join(d, "page_*.json")))
    if not pages:
        sys.exit(f"no harvested pages in {d} - run harvest-year --year {args.year} first")
    import duckdb
    dbp = os.path.join(HERE, f"works_{args.year}.duckdb")
    if os.path.isfile(dbp):
        for attempt in range(4):
            try:
                os.remove(dbp)
                break
            except PermissionError:
                # The Platform's live reload ATTACHes every works DB read-only
                # for a moment whenever the board changes — which is exactly when
                # a resolve run is touching these files. Back off and retry; if
                # it stays held, give this year up for now: the harvest pages on
                # disk are the truth and the next resolve run rebuilds the DB.
                if attempt == 3:
                    print(f"  works_{args.year}: DB held by another process "
                          "(Platform live reload?) — skipped this cycle; the "
                          "next resolve run rebuilds it")
                    return
                time.sleep(1.5 * (attempt + 1))
    con = duckdb.connect(dbp)
    glob_json = os.path.join(d, "page_*.json").replace("\\", "/")
    # Dedup by work id (belt-and-braces alongside clearing stale pages in harvest_year): if any
    # page overlap slips through, keep one row per id rather than double-counting the work.
    con.execute(f"""CREATE TABLE works AS
                    SELECT * FROM read_json_auto('{glob_json}', format='array',
                                                 union_by_name=true)
                    QUALIFY row_number() OVER (PARTITION BY id ORDER BY id) = 1""")
    n = con.execute("SELECT count(*) FROM works").fetchone()[0]

    # Pin the router's comparison columns to their expected types. A small
    # single-year batch (the intake seam can create a year holding ONE work) can
    # make read_json_auto infer JSON for a column that is all-null in that sample
    # — and a JSON-typed `license` breaks every string comparison below
    # ("Conversion Error: Malformed JSON ... Input: cc-by", the 2026-07-17
    # works_1968 intake failure). Coerce whatever inference said.
    for _col, _typ in (("license", "VARCHAR"), ("journal", "VARCHAR"),
                       ("publisher", "VARCHAR"), ("in_pmc", "BOOLEAN"),
                       ("has_pdf", "BOOLEAN")):
        _cur = con.execute("SELECT data_type FROM information_schema.columns "
                           "WHERE table_name='works' AND column_name=?", [_col]).fetchone()
        if _cur and _cur[0] == "JSON":
            con.execute(f"ALTER TABLE works ALTER {_col} SET DATA TYPE {_typ} "
                        f"USING try_cast(json_extract_string({_col}, '$') AS {_typ})")

    # ---- lane-router columns: the routing policy, applied ----
    # WHICH ROUTE each paper takes -- and why -- is policy, and it lives in
    # routing/rules.py as an ordered, commented decision table. routing.apply()
    # compiles that table into SQL and derives all six columns in dependency
    # order: scoap3, route, route_access, asset_route, lane, disposition.
    #
    # These used to be six hand-written CASE expressions inline here. They were
    # extracted 2026-09-02 so the judgement could be read and argued with on its
    # own; tests/test_routing.py holds the original SQL verbatim and requires
    # row-for-row agreement across every works_*.duckdb, so the extraction is
    # pinned rather than trusted. Run `python -m routing --explain` for the
    # policy as a decision table.
    import routing
    routing.apply(con)

    # ---- work-tracker columns: NOT derived from metadata but from ingest OUTCOMES ----
    # The router above answers "how do I GET paper X"; these answer "what has HAPPENED to
    # paper X, and what's left to do". They live out-of-band in ingest_log.json so a
    # rebuild-from-harvest never wipes real work: build_db seeds them (pending) then
    # overlays the log; ingest_batch/ingest_log.py writes outcomes back to both.
    for col, typ in (("ingest_status", "VARCHAR"), ("gates_passed", "BOOLEAN"),
                     ("figures_status", "VARCHAR"), ("escalate_reason", "VARCHAR"),
                     ("ingest_mid", "VARCHAR"), ("ingest_ts", "VARCHAR")):
        con.execute(f"ALTER TABLE works ADD COLUMN {col} {typ}")
    con.execute("""UPDATE works SET ingest_status =
                     CASE WHEN route='out_of_scope' THEN 'out_of_scope' ELSE 'pending' END""")
    logp = os.path.join(HERE, "ingest_log.json")
    if os.path.isfile(logp):
        log = json.load(open(logp, encoding="utf-8"))
        con.execute("""CREATE TEMP TABLE _il(id VARCHAR, status VARCHAR, gates BOOLEAN,
                         figs VARCHAR, esc VARCHAR, mid VARCHAR, ts VARCHAR)""")
        for wid, r in log.items():
            con.execute("INSERT INTO _il VALUES (?,?,?,?,?,?,?)",
                        [wid, r.get("ingest_status"), r.get("gates_passed"),
                         r.get("figures_status"), r.get("escalate_reason"),
                         r.get("mid"), r.get("ts")])
        con.execute("""UPDATE works w SET ingest_status=il.status, gates_passed=il.gates,
                         figures_status=il.figs, escalate_reason=il.esc,
                         ingest_mid=il.mid, ingest_ts=il.ts
                       FROM _il il WHERE w.id=il.id""")
        print(f"overlaid {len(log)} ingest-log outcome(s) onto works")

    # ---- index the per-paper sidecars (intra-article records) into the DB projection ----
    # Each ingested/{id}/metadata.json is the source of truth; these columns are a
    # rebuildable cache (sidecar_path + the full sidecar JSON + a few convenience counts).
    import ingest_log
    ingest_log.ensure_side_cols(con)
    scs = sorted(glob.glob(os.path.join(HERE, "ingested", "*", "metadata.json")))
    for p in scs:
        try:
            sc = json.load(open(p, encoding="utf-8"))
            ingest_log.apply_sidecar(con, sc["identity"]["work_id"], p, sc)
        except Exception as e:
            print(f"  skipped sidecar {p}: {e}")
    if scs:
        print(f"indexed {len(scs)} sidecar(s) from ingested/")

    con.execute("""CREATE VIEW ccby_vor AS SELECT * FROM works
                   WHERE license='cc-by' AND version='publishedVersion' AND has_pdf""")
    print(f"built {dbp}: {n} works, view ccby_vor")
    print("\n=== LANE ROUTER: 2025 works by cost tier (lane) ===")
    con.sql("""SELECT lane, count(*) AS n,
                      round(100.0*count(*)/sum(count(*)) OVER (), 1) AS pct
               FROM works GROUP BY lane ORDER BY n DESC""").show()
    print("=== ROUTE: the cheapest actual XML mechanism per paper ===")
    con.sql("""SELECT route, any_value(route_access) AS access, count(*) AS n
               FROM works GROUP BY route ORDER BY n DESC""").show()
    print("=== how much moves out of true-conversion once we set routes up ===")
    con.sql("""SELECT route_access, count(*) AS n FROM works
               WHERE license='cc-by' GROUP BY route_access ORDER BY n DESC""").show()
    any_pmc = con.execute("SELECT count(*) FROM works WHERE in_pmc").fetchone()[0]
    ccby_pmc = con.execute("SELECT count(*) FROM works WHERE in_pmc AND license = 'cc-by'").fetchone()[0]
    print(f"in_pmc (any licence): {any_pmc}; cc-by + in_pmc: {ccby_pmc}")
    print("\n=== 2025 picture: publishers by CC-BY VoR (downloadable PDF) ===")
    con.sql("""SELECT coalesce(publisher,'(none)') AS publisher,
                      count(*) AS ccby_vor_pdfs,
                      count(*) FILTER (has_grobid) AS with_grobid_tei
               FROM ccby_vor GROUP BY 1 ORDER BY ccby_vor_pdfs DESC LIMIT 20"""
            ).show(max_width=120, max_rows=25)
    print("=== whole-year shape: OA/licence mix ===")
    con.sql("""SELECT coalesce(license,'(non-OA/none)') AS license, count(*) AS n
               FROM works GROUP BY 1 ORDER BY n DESC LIMIT 12""").show(max_rows=15)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "unknown").lower()).strip("-")[:40]


def pull_pdfs(args):
    if not api_key():
        sys.exit("PDF download needs the API key")
    import duckdb
    dbp = os.path.join(HERE, f"works_{args.year}.duckdb")
    if not os.path.isfile(dbp):
        sys.exit(f"no {dbp} - run build-db --year {args.year} first")
    con = duckdb.connect(dbp, read_only=True)
    rows = con.execute(f"""
        WITH pub_counts AS (
          SELECT publisher, count(*) AS n FROM ccby_vor
          WHERE publisher IS NOT NULL GROUP BY publisher),
        top_pubs AS (
          SELECT publisher, row_number() OVER (ORDER BY n DESC, publisher) AS pub_rank
          FROM pub_counts),
        ranked AS (
          SELECT v.id, v.doi, v.title, v.publisher, v.journal, v.has_grobid,
                 row_number() OVER (PARTITION BY v.publisher ORDER BY v.id) AS rn
          FROM ccby_vor v WHERE v.publisher IS NOT NULL)
        SELECT r.id, r.doi, r.title, r.publisher, r.journal, r.has_grobid
        FROM ranked r JOIN top_pubs t USING (publisher)
        WHERE r.rn <= {args.per_publisher} AND t.pub_rank <= {args.top_publishers}
        ORDER BY r.publisher, r.id""").fetchall()
    cost = len(rows) * 0.01
    print(f"selected {len(rows)} CC-BY VoR PDFs "
          f"({args.per_publisher}/publisher x top {args.top_publishers} publishers) "
          f"~= ${cost:.2f}")
    if args.dry_run:
        for r in rows:
            print(f"  [{r[3][:35]:35s}] {r[0]} grobid={r[5]} {(r[2] or '')[:45]}")
        print("\n(dry run - no downloads; drop --dry-run to fetch)")
        return
    out = os.path.join(HERE, "harvest", f"pdfs_{args.year}")
    manifest = []
    ok = 0
    for r in rows:
        wid, doi, title, publisher, journal, has_grobid = r
        pdir = os.path.join(out, _slug(publisher))
        os.makedirs(pdir, exist_ok=True)
        p = os.path.join(pdir, f"{wid}.pdf")
        row = {"id": wid, "doi": doi, "publisher": publisher, "journal": journal,
               "has_grobid": has_grobid, "title": title, "path": None}
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            row["path"] = os.path.relpath(p, HERE); ok += 1; manifest.append(row)
            continue
        url = f"https://content.openalex.org/works/{wid}.pdf?api_key={api_key()}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MORE-harvest/0.1"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
            open(p, "wb").write(data)
            row["path"] = os.path.relpath(p, HERE); ok += 1
            print(f"  {publisher[:30]:30s} {wid}  {len(data)/1e6:.1f}MB")
        except Exception as e:
            row["error"] = str(e)[:80]
            print(f"  {publisher[:30]:30s} {wid}  FAILED {str(e)[:50]}")
        manifest.append(row)
    save(f"pdfs_{args.year}_manifest.json", manifest)
    print(f"\ndownloaded {ok}/{len(rows)} PDFs into {out} "
          f"(manifest: harvest/pdfs_{args.year}_manifest.json)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    L = sub.add_parser("landscape", help="UoM CC-BY landscape (metadata only, cheap)")
    L.add_argument("--since", default="2021", help="start publication year (default 2021)")
    L.set_defaults(fn=landscape)
    S = sub.add_parser("status", help="check the API key")
    S.set_defaults(fn=status)
    F = sub.add_parser("fetch-one", help="download PDF+TEI for one DOI (needs key)")
    F.add_argument("--doi", required=True)
    F.set_defaults(fn=fetch_one)
    H = sub.add_parser("harvest-year", help="pull ALL articles for a year (metadata, cheap)")
    H.add_argument("--year", default="2025")
    H.set_defaults(fn=harvest_year)
    B = sub.add_parser("build-db", help="build works_YYYY.duckdb from harvested pages")
    B.add_argument("--year", default="2025")
    B.set_defaults(fn=build_db)
    P = sub.add_parser("pull-pdfs", help="download a bounded CC-BY PDF subset by publisher")
    P.add_argument("--year", default="2025")
    P.add_argument("--per-publisher", type=int, default=3)
    P.add_argument("--top-publishers", type=int, default=10)
    P.add_argument("--dry-run", action="store_true", help="list the selection + cost, no downloads")
    P.set_defaults(fn=pull_pdfs)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
