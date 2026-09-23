#!/usr/bin/env python
"""fetch_vor_pdfs.py — capture Lane-B (convert_vor) publisher VoR PDFs, grouped by
publisher, as the substrate for a rules-based VoR->JATS pipeline.

SUPERSEDED PILOT HARNESS: production Lane-B fetching (TEI + the same archived PDF)
is fetch_router.py; keep this for ad-hoc publisher-corpus pulls.

URL sourcing (per the OpenAlex-first design):
  tier 1  OpenAlex content service   content.openalex.org/works/{id}.pdf   (reliable;
          OpenAlex's archived copy — no publisher bot-wall). Costs ~$0.01/file.
  tier 2  publisher best_oa_location.pdf_url (live from the API) — free, but many big
          publishers 403 a scripted request; used where OpenAlex has no hosted copy or
          when --prefer-direct is set (e.g. Cambridge, which serves cleanly).

Writes:  harvest/pdfs_2025/{publisher-slug}/{work_id}.pdf   (+ .grobid.xml with --with-tei)
         harvest/pdfs_2025/_manifest.json   (append/update; id, publisher, tier, url,
                                             sha256, bytes, license, has_tei, ts-less)

Resumable: skips works already on disk. Self-throttled. Never overwrites.

Usage:
  python fetch_vor_pdfs.py --plan "Wiley:20,Oxford University Press:20,Royal Society of Chemistry:20,Taylor & Francis:20"
  python fetch_vor_pdfs.py --plan "Cambridge University Press:20" --prefer-direct
  python fetch_vor_pdfs.py --plan "Wiley:5" --dry-run        # resolve only, no download
"""
import argparse, gzip, hashlib, json, re, ssl, sys, time, urllib.error, urllib.request
from pathlib import Path
import duckdb

HERE = Path(__file__).resolve().parent
DB = HERE / "works_2025.duckdb"
KEY = (HERE / "openalex_key.txt").read_text().strip()
OUT = HERE / "harvest" / "pdfs_2025"
MANIFEST = OUT / "_manifest.json"
UA = "MORE-harvest/0.1 (University of Manchester; text-mining CC-BY VoR content)"
CTX = ssl.create_default_context()
API = "https://api.openalex.org/works"
CONTENT = "https://content.openalex.org/works"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def api_get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}", "User-Agent": UA})
    with urllib.request.urlopen(req, context=CTX, timeout=40) as r:
        return json.load(r)


def resolve(publisher, want):
    """Return up to `want` plan rows: {id, tier, url, license, has_tei}.
    Prefers OpenAlex-hosted (tier 1); notes best_oa_location.pdf_url for tier 2."""
    con = duckdb.connect(str(DB), read_only=True)
    ids = [r[0].replace("https://openalex.org/", "") for r in con.execute(
        "select id from works where disposition='convert_vor' and publisher=? order by hash(id)",
        [publisher]).fetchall()]
    con.close()
    # Collect ALL candidates first, tagged by tier, so we can prefer tier-1 (hosted,
    # reliable) and fall back to tier-2 (direct, may 403) only to top up the quota.
    tier1, tier2 = [], []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = api_get(f"{API}?filter=openalex_id:{'|'.join(chunk)}&per_page=50"
                       "&select=id,doi,has_fulltext,best_oa_location")
        hd = api_get(f"{API}?filter=openalex_id:{'|'.join(chunk)},has_content.pdf:true"
                     "&per_page=50&select=id")
        hosted = {w["id"].split("/")[-1] for w in hd["results"]}
        for w in data["results"]:
            wid = w["id"].split("/")[-1]
            bol = w.get("best_oa_location") or {}
            row = {"id": wid, "license": bol.get("license"), "has_tei": bool(w.get("has_fulltext"))}
            if wid in hosted:
                tier1.append({**row, "tier": 1, "url": f"{CONTENT}/{wid}.pdf"})
            elif bol.get("pdf_url"):
                tier2.append({**row, "tier": 2, "url": bol["pdf_url"]})
        time.sleep(0.2)
        if len(tier1) >= want:
            break  # enough reliable hosted candidates; stop scanning
    return (tier1 + tier2)[:want]


def download(url, tier):
    headers = {"User-Agent": UA, "Accept": "application/pdf"}
    if tier == 1:
        url = f"{url}?api_key={KEY}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=CTX, timeout=90) as r:
        body = r.read()
    if body[:5] != b"%PDF-":
        raise ValueError(f"not a PDF (starts {body[:8]!r})")
    return body


def load_manifest():
    if MANIFEST.exists():
        return {row["id"]: row for row in json.loads(MANIFEST.read_text())}
    return {}


def save_manifest(m):
    MANIFEST.write_text(json.dumps(list(m.values()), indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help='"Publisher:N,Publisher:N"')
    ap.add_argument("--prefer-direct", action="store_true",
                    help="use publisher pdf_url (tier 2) first, even if OpenAlex-hosted")
    ap.add_argument("--with-tei", action="store_true", help="also fetch GROBID TEI (costs credits)")
    ap.add_argument("--dry-run", action="store_true", help="resolve + print plan, no download")
    args = ap.parse_args()

    targets = []
    for part in args.plan.split(","):
        name, n = part.rsplit(":", 1)
        targets.append((name.strip(), int(n)))

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    got_total = 0

    for publisher, want in targets:
        pdir = OUT / slug(publisher)
        pdir.mkdir(exist_ok=True)
        existing = len(list(pdir.glob("*.pdf")))
        need = max(0, want - existing)
        print(f"\n== {publisher}  (have {existing}, want {want}, need {need}) ==")
        if need == 0:
            continue
        plan = resolve(publisher, want)
        if args.prefer_direct:
            for row in plan:
                bol_url = row["url"]
                if row["tier"] == 1:
                    # re-resolve a direct url for prefer-direct
                    d = api_get(f"{API}/{row['id']}?select=best_oa_location")
                    pu = (d.get("best_oa_location") or {}).get("pdf_url")
                    if pu:
                        row["tier"], row["url"] = 2, pu
        t1 = sum(1 for r in plan if r["tier"] == 1)
        print(f"   resolved {len(plan)}: tier1(content-svc)={t1} tier2(direct)={len(plan)-t1}")
        if args.dry_run:
            for r in plan:
                print(f"     {r['id']} t{r['tier']} tei={r['has_tei']} {r['license']} {r['url'][:70]}")
            continue

        got = 0
        for row in plan:
            wid = row["id"]
            dest = pdir / f"{wid}.pdf"
            if dest.exists():
                continue
            try:
                body = download(row["url"], row["tier"])
            except Exception as e:
                print(f"   ! {wid} tier{row['tier']} FAILED: {e}")
                continue
            dest.write_bytes(body)
            sha = hashlib.sha256(body).hexdigest()
            manifest[wid] = {"id": wid, "publisher": publisher, "publisher_slug": slug(publisher),
                             "tier": row["tier"], "url": row["url"], "sha256": sha,
                             "bytes": len(body), "license": row["license"],
                             "has_tei": row["has_tei"], "path": str(dest.relative_to(HERE))}
            got += 1
            got_total += 1
            print(f"   + {wid} t{row['tier']} {len(body)/1e6:5.2f}MB {row['license']}")
            save_manifest(manifest)
            time.sleep(0.4)
            if row["has_tei"] and args.with_tei:
                try:
                    req = urllib.request.Request(f"{CONTENT}/{wid}.grobid-xml?api_key={KEY}",
                                                 headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
                        tei = r.read()
                    # TEI objects are stored gzipped with NO Content-Encoding header
                    # (same endpoint behaviour fetch_tei documents) — decompress on
                    # magic bytes, never land raw gzip under a .grobid.xml name.
                    if tei[:2] == b"\x1f\x8b":
                        tei = gzip.decompress(tei)
                    (pdir / f"{wid}.grobid.xml").write_bytes(tei)
                    time.sleep(0.3)
                except Exception as e:
                    print(f"     (tei skip {wid}: {e})")
        print(f"   got {got}")
    print(f"\nDONE. new files: {got_total}. manifest: {MANIFEST.relative_to(HERE)}")


if __name__ == "__main__":
    main()
