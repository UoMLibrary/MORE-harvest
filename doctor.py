#!/usr/bin/env python3
"""What this checkout can and cannot actually do. Run me first.

Nothing here is fatal: the point is that the pipeline degrades in several places
rather than failing, so you should know which degraded mode you are in BEFORE you
read a verdict as meaningful.
"""

import importlib.util
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ok = lambda b: "yes" if b else "NO"


def main():
    print("MORE harvest — review snapshot\n")

    print("Python")
    print(f"  {sys.version.split()[0]}  ({'3.13+' if sys.version_info >= (3, 13) else 'developed on 3.13'})")

    print("\nPackages")
    for mod, why in (("duckdb", "the router/tracker index"),
                     ("lxml", "every transform in lanec/"),
                     ("fitz", "PDF text for the Lane-B fidelity gate (pymupdf)")):
        print(f"  {mod:<8} {ok(importlib.util.find_spec(mod) is not None):<4} {why}")

    print("\nGates (vendor/, see vendor/SOURCE.md)")
    for rel in ("scripts/validate_jats.py", "scripts/jats_house_lint.py",
                "scripts/data/anzsrc_2020.json"):
        print(f"  {ok(os.path.isfile(os.path.join(HERE, 'vendor', rel))):<4} {rel}")

    dtd = os.path.join(HERE, "vendor", "dtd", "JATS-archivearticle1-4-mathml3.dtd")
    has_dtd, has_xmllint = os.path.isfile(dtd), shutil.which("xmllint") is not None
    print("\nValidation tier")
    if has_dtd and has_xmllint:
        print("  TIER 2 — structural + DTD validity. Verdicts mean what they say.")
    else:
        print("  TIER 1 ONLY — structural checks; DTD validity is SKIPPED.")
        if not has_dtd:
            print("    no DTD at vendor/dtd/ (see vendor/dtd/README.md)")
        if not has_xmllint:
            print("    xmllint not on PATH")
        print("    Green verdicts in this mode prove LESS than they appear to.")

    print("\nWhat you can run without an API key")
    print("  python tests/crosswalk_pilot.py    Lane C, seven publisher fixtures, offline")
    print("  python tests/test_routing.py       the routing policy (needs a works DB)")
    print("  python -m routing --explain        the routing policy as a decision table")

    sample = [os.path.join(r, f)
              for r, _, fs in os.walk(os.path.join(HERE, "harvest"))
              for f in fs if f.endswith(".json")]
    print("\nSample data")
    if sample:
        year = os.path.basename(os.path.dirname(sample[0])).replace("works_", "")
        print(f"  {len(sample)} harvested page(s) present — build the DB with:")
        print(f"    python harvest_openalex.py build-db --year {year}")
    else:
        print("  none — harvesting needs an OpenAlex key (see README)")

    key = any(os.path.isfile(os.path.join(HERE, k))
              for k in ("openalex_key.txt",)) or os.environ.get("OPENALEX_API_KEY")
    print("\nOpenAlex key")
    print("  present — live harvesting and Lane-B fetches available" if key else
          "  absent — harvesting and all fetching are unavailable; the fixtures and the\n"
          "  sample page are what make this checkout exercisable")


if __name__ == "__main__":
    main()
