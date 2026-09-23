# vendor/dtd — the JATS 1.4 DTD (not committed)

`vendor/scripts/validate_jats.py` checks in two tiers:

- **Tier 1, structural** — always runs. No DTD, no network.
- **Tier 2, DTD validity** — runs *only* if the DTD is present here, and needs
  `xmllint` on PATH.

**Tier 2 skips silently when the DTD is absent, and that is the dangerous failure
mode**: verdicts still come back green, they just prove less. Run `python doctor.py`
to see which tier you are actually getting before you trust any verdict.

To enable Tier 2, obtain the NLM *JATS Archiving and Interchange DTD with MathML3
v1.4* pack from the NLM JATS site and unpack it here, so that this path exists:

    vendor/dtd/JATS-archivearticle1-4-mathml3.dtd

The pack is about 9.8 MB and is deliberately not committed.
