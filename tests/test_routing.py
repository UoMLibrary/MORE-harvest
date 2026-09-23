"""Prove the extracted routing policy is behaviour-identical to the SQL it replaced.

The lane router used to be six hand-written CASE expressions inside
`harvest_openalex.build_db`. They were lifted into `routing/rules.py` so the policy
could be read and argued with on its own. That extraction is only safe if it moved
NOTHING, so this test keeps the original SQL verbatim below as the golden reference
and requires row-for-row agreement over every works_*.duckdb on disk — real corpus
data, tens of thousands of papers per year, every publisher and licence combination
we have actually met.

    python tests/test_routing.py

Needs duckdb and at least one built works DB; no network and no key. If the routing
policy is changed ON PURPOSE, this test is expected to fail: update LEGACY_SQL in
the same commit so the next change is measured against the new baseline, and record
the routing change in CHANGELOG.md.
"""

import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HARVEST = os.path.dirname(HERE)
sys.path.insert(0, HARVEST)

import routing  # noqa: E402

DERIVED = ("scoap3", "route", "route_access", "asset_route", "lane", "disposition")

# --------------------------------------------------------------------------
# The original hand-written SQL, exactly as it stood in harvest_openalex.py
# before the extraction. Do not tidy it: its value is that it is untouched.
# --------------------------------------------------------------------------

_SPRINGER = ("'Springer Science+Business Media','Springer Nature','Nature Portfolio',"
             "'BioMed Central'")
_NATIVE = ("'Multidisciplinary Digital Publishing Institute','Frontiers Media',"
           "'Public Library of Science','eLife Sciences Publications Ltd',"
           "'eLife Sciences Publications','PeerJ','Copernicus GmbH','Copernicus Publications',"
           "'Pensoft Publishers','F1000 Research Ltd','F1000 Research','The Royal Society',"
           "'Royal Society','NIHR Journals Library','Ubiquity Press',"
           "'Open Library of the Humanities'")
_ELSEVIER = "'Elsevier BV','Elsevier'"
_GATED = ("'Wiley','Oxford University Press','Taylor & Francis','SAGE Publishing',"
          "'American Chemical Society','Cambridge University Press',"
          "'Institute of Electrical and Electronics Engineers','IOP Publishing',"
          "'Institute of Physics','Royal Society of Chemistry','American Physical Society',"
          "'EDP Sciences','BMJ','BMJ Publishing Group'")
_REPO = ("'Figshare','Figshare (United Kingdom)',"
         "'European Organization for Nuclear Research','Zenodo'")
_REUSABLE = "('cc-by','cc-by-sa','public-domain','cc0')"

LEGACY_SQL = [
    r"""UPDATE works SET scoap3 = CASE
        WHEN lower(journal) LIKE 'physical review. d%' OR lower(journal) LIKE 'physical review d%'
             OR lower(journal) LIKE 'physical review. c%' OR lower(journal) LIKE 'physical review c%'
             OR lower(journal) LIKE 'physical review letters%'
          THEN 'aps'
        WHEN lower(journal) LIKE '%high energy physics%'
             OR lower(journal) LIKE '%european physical journal c%'
             OR lower(journal) LIKE '%physics letters b%' OR lower(journal) LIKE '%nuclear physics b%'
             OR lower(journal) LIKE '%chinese physics c%'
             OR lower(journal) LIKE '%theoretical and experimental physics%'
             OR lower(journal) LIKE '%acta physica polonica b%'
          THEN 'other'
        ELSE NULL END""",

    f"""UPDATE works SET route = CASE
        WHEN license <> 'cc-by' OR license IS NULL   THEN 'out_of_scope'
        WHEN in_pmc                                  THEN 'pmc'
        WHEN scoap3 = 'aps'                          THEN 'scoap3_aps'
        WHEN scoap3 = 'other' AND lower(journal) LIKE '%high energy physics%'
                                                     THEN 'scoap3_jhep'
        WHEN scoap3 = 'other' AND lower(journal) LIKE '%european physical journal c%'
                                                     THEN 'springer_oa_api'
        WHEN scoap3 = 'other' AND (lower(journal) LIKE '%physics letters b%'
                                   OR lower(journal) LIKE '%nuclear physics b%')
                                                     THEN 'scoap3_elsevier'
        WHEN scoap3 = 'other'                        THEN 'scoap3_other'
        WHEN publisher IN ({_SPRINGER})               THEN 'springer_oa_api'
        WHEN publisher IN ({_NATIVE})                 THEN 'jats_native_open'
        WHEN publisher IN ({_ELSEVIER})               THEN 'elsevier_entitlement'
        WHEN publisher IN ({_GATED})                  THEN 'gated_commercial'
        WHEN publisher IN ({_REPO}) OR publisher IS NULL THEN 'repository'
        ELSE 'convert' END""",

    """UPDATE works SET route_access = CASE route
        WHEN 'pmc' THEN 'open'         WHEN 'scoap3_aps' THEN 'open'
        WHEN 'scoap3_other' THEN 'open' WHEN 'jats_native_open' THEN 'open'
        WHEN 'scoap3_jhep' THEN 'open' WHEN 'scoap3_elsevier' THEN 'open'
        WHEN 'springer_oa_api' THEN 'free_key'
        WHEN 'elsevier_entitlement' THEN 'entitlement'
        WHEN 'gated_commercial' THEN 'gated'   WHEN 'repository' THEN 'repository'
        WHEN 'convert' THEN 'none'     ELSE 'na' END""",

    """UPDATE works SET asset_route = CASE
        WHEN route = 'pmc'                                   THEN 'publisher_package'
        WHEN route IN ('scoap3_aps','scoap3_other','scoap3_jhep','scoap3_elsevier')
                                                             THEN 'repo_pdf'
        WHEN route = 'elsevier_entitlement'                  THEN 'entitlement_pdf'
        WHEN route IN ('jats_native_open','springer_oa_api')
             AND pdf_url IS NOT NULL                         THEN 'oa_pdf'
        WHEN route IN ('jats_native_open','springer_oa_api') THEN 'publisher_urls'
        WHEN route IN ('gated_commercial','repository','convert')
             AND (pdf_url IS NOT NULL OR has_pdf)            THEN 'pdf_extract_laneB'
        WHEN route = 'out_of_scope'                          THEN 'na'
        ELSE 'none' END""",

    """UPDATE works SET lane = CASE
        WHEN route IN ('pmc','scoap3_aps','scoap3_jhep','jats_native_open','springer_oa_api') THEN 'C_ingest'
        WHEN route IN ('scoap3_elsevier','scoap3_other','elsevier_entitlement')  THEN 'Cprime_transform'
        WHEN route IN ('gated_commercial','repository','convert')               THEN 'B_convert'
        ELSE 'out_of_scope' END""",

    f"""UPDATE works SET disposition = CASE
        WHEN license='cc-by' AND lane IN ('C_ingest','Cprime_transform') THEN 'automated'
        WHEN license IN {_REUSABLE}                                       THEN 'convert_vor'
        ELSE 'source_aam' END""",
]


def _fresh(dbpath):
    """An in-memory `works` table copied from dbpath, with the derived columns dropped."""
    import duckdb
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{dbpath}' AS src (READ_ONLY)")
    cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='works' AND table_catalog='src'").fetchall()]
    keep = [c for c in cols if c not in DERIVED]
    con.execute(f"CREATE TABLE works AS SELECT {', '.join(keep)} FROM src.works")
    con.execute("DETACH src")
    return con


def check(dbpath):
    import duckdb  # noqa: F401
    old = _fresh(dbpath)
    for col in DERIVED:
        old.execute(f"ALTER TABLE works ADD COLUMN {col} VARCHAR")
    for stmt in LEGACY_SQL:
        old.execute(stmt)

    new = _fresh(dbpath)
    routing.apply(new)

    n = old.execute("SELECT count(*) FROM works").fetchone()[0]
    failures = []
    for col in DERIVED:
        rows = old.execute(f"SELECT id, {col} FROM works ORDER BY id").fetchall()
        rows2 = new.execute(f"SELECT id, {col} FROM works ORDER BY id").fetchall()
        diff = [(a[0], a[1], b[1]) for a, b in zip(rows, rows2) if a[1] != b[1]]
        if diff:
            failures.append((col, diff))
    old.close()
    new.close()
    return n, failures


def main():
    dbs = sorted(glob.glob(os.path.join(HARVEST, "works_*.duckdb")))
    if not dbs:
        sys.exit("no works_*.duckdb found — build one first "
                 "(python harvest_openalex.py build-db --year 2025)")

    total, bad = 0, 0
    for db in dbs:
        n, failures = check(db)
        total += n
        name = os.path.basename(db)
        if failures:
            bad += 1
            print(f"FAIL {name}: {n} works")
            for col, diff in failures:
                print(f"     {col}: {len(diff)} row(s) differ; first 5:")
                for wid, a, b in diff[:5]:
                    print(f"       {wid}  legacy={a!r}  routing={b!r}")
        else:
            print(f"ok   {name}: {n} works, all 6 routing columns identical")

    print(f"\n{len(dbs)} database(s), {total} works compared")
    if bad:
        sys.exit(f"FAILED: routing differs from the legacy SQL in {bad} database(s)")
    print("PASS: the extracted policy reproduces the original SQL exactly")


if __name__ == "__main__":
    main()
