#!/usr/bin/env python
"""fetch_tei.py — grab OpenAlex GROBID TEI (.grobid-xml) for works we already hold the
PDF for, giving PDF+TEI pairs to build/test per-publisher TEI->JATS crosswalks.

SUPERSEDED PILOT HARNESS: this captured the original pilot pairs; production Lane-B
fetching is fetch_router.py (the org Member+ key removed the budget constraint the
X-RateLimit floor here guarded against — the floor logic is kept only because the
content service still meters per-file). TEI written next to the PDF as
{id}.grobid.xml; manifest updated with tei_bytes. Resumable (skips TEI on disk).

Usage: python fetch_tei.py --per 5 [--floor 0.02]
"""
import argparse, gzip, json, ssl, time, urllib.request, urllib.error
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY = (HERE / "openalex_key.txt").read_text().strip()
OUT = HERE / "harvest" / "pdfs_2025"
MANIFEST = OUT / "_manifest.json"
UA = "MORE-harvest/0.1 (University of Manchester; text-mining CC-BY VoR content)"
CTX = ssl.create_default_context()
CONTENT = "https://content.openalex.org/works"


API = "https://api.openalex.org/works"


def remaining_usd():
    """Cheap ($0.0001) budget probe."""
    req = urllib.request.Request(f"{API}?per_page=1",
                                 headers={"Authorization": f"Bearer {KEY}", "User-Agent": UA})
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        rem = r.headers.get("X-RateLimit-Remaining-USD")
    return float(rem) if rem else None


def fetch_tei(wid):
    """Return (bytes, remaining_usd). TEI objects are stored gzipped — decompress."""
    req = urllib.request.Request(f"{CONTENT}/{wid}.grobid-xml?api_key={KEY}",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
        body = r.read()
        rem = r.headers.get("X-RateLimit-Remaining-USD")
        enc = (r.headers.get("Content-Encoding") or "").lower()
    if body[:2] == b"\x1f\x8b" or enc == "gzip":
        body = gzip.decompress(body)
    return body, (float(rem) if rem else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=5, help="TEIs per publisher")
    ap.add_argument("--floor", type=float, default=0.02, help="stop when remaining USD < floor")
    args = ap.parse_args()

    manifest = {r["id"]: r for r in json.loads(MANIFEST.read_text())}
    by_pub = defaultdict(list)
    for r in manifest.values():
        if r.get("has_tei"):
            by_pub[r["publisher_slug"]].append(r)

    # Pre-flight: one cheap probe. TEI = $0.01/file; stop before we can't afford one.
    rem = remaining_usd()
    print(f"budget remaining: ${rem}")
    if rem is not None and rem < 0.01 + args.floor:
        print(f"STOP: ${rem} is below one file ($0.01) + floor (${args.floor}). "
              "Wait for daily reset or use the org key.")
        return

    got = 0
    for slug, rows in sorted(by_pub.items()):
        taken = 0
        for r in rows:
            if taken >= args.per:
                break
            wid = r["id"]
            dest = OUT / slug / f"{wid}.grobid.xml"
            if dest.exists():
                taken += 1
                continue
            # only pay if we can afford this file plus the floor
            if rem is not None and rem < 0.01 + args.floor:
                print(f"\nSTOP: remaining ${rem} < $0.01 + floor. fetched {got} TEIs.")
                MANIFEST.write_text(json.dumps(list(manifest.values()), indent=1))
                return
            try:
                body, rem = fetch_tei(wid)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print(f"  ! 429 (budget/rate). stopping. fetched {got}.")
                    MANIFEST.write_text(json.dumps(list(manifest.values()), indent=1))
                    return
                print(f"  ! {wid} HTTP {e.code}")
                continue
            except Exception as e:
                print(f"  ! {wid} FAILED: {e}")
                continue
            if not body.lstrip().startswith(b"<"):
                print(f"  ! {wid} not XML after decode ({body[:40]!r})")
                continue
            dest.write_bytes(body)
            r["tei_bytes"] = len(body)
            got += 1
            taken += 1
            print(f"  + {slug:34s} {wid} {len(body)/1e3:6.1f}KB   remaining ${rem}")
            MANIFEST.write_text(json.dumps(list(manifest.values()), indent=1))
            if rem is not None and rem < args.floor:
                print(f"\nSTOP: remaining ${rem} < floor ${args.floor}. fetched {got} TEIs.")
                return
            time.sleep(0.4)
    print(f"\nDONE. fetched {got} TEIs.")


if __name__ == "__main__":
    main()
