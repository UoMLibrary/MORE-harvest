---
type: concept
tags: [harvest, concept, rights]
updated: 2026-07-04
---

# Why CC-BY Is the Key

> [!warning] The rule
> The whole harvest idea is legal **only** for CC-BY papers — and the licence must be verified on
> *every single paper*, never assumed from the journal or the fact that it's "open access".

## Why CC-BY specifically

A CC-BY (Creative Commons Attribution) licence grants *anyone* the right to copy, redistribute, and
**adapt** the work, as long as they credit the authors. Converting a publisher's XML into our house
JATS, adding our identifiers, and storing it in our repository is exactly "adapt and redistribute".
CC-BY says yes. So a CC-BY published version of record is fair game — arguably *more* clearly than an
author's accepted manuscript, which we only handle under Manchester's Rights Retention Policy.

Note the payment is irrelevant. We don't need to have paid the article's open-access charge, and
we're not limited to papers we paid for — CC-BY gives the rights to everyone. The real eligible pool
is "every CC-BY paper with a Manchester author", which is *bigger* than the list we paid for.

## The trap, discovered on paper one

The very first paper we pulled to test the idea — one of our own already-catalogued manuscripts —
turned out to carry a **CC-BY-NC-ND** licence, not CC-BY. The `NC` means non-commercial; the `ND`
means *no derivatives*. Restructuring it into JATS is arguably making a derivative, which ND forbids.
A second test paper was "other open access" — no clear reuse grant at all.

The lesson landed hard and early: **open access ≠ CC-BY**, and hybrid journals mix licences
article-by-article. Roughly 1,200 of our 2025 papers are the NC / ND / SA variants sitting right
next to the CC-BY ones — invisible unless you check each paper.

## How we honour the rule

- The lane router only ever routes `license = 'cc-by'` papers into a harvest lane. Everything else is
  marked `out_of_scope` for the VoR route (it may still qualify for [Lane A — Rights-Driven Conversion](../The%20Four%20Lanes/Lane%20A%20—%20Rights-Driven%20Conversion.md)
  via the author's manuscript).
- The download tools carry a licence guard that shouts if a target isn't CC-BY.
- One small extra caution: a CC-BY article can still contain a third-party figure marked "© someone
  else, reproduced with permission" — the article's licence doesn't cover that image. Flag it, don't
  redistribute it blindly.

---
Prev: [Intra vs Inter-Article Metadata](Intra%20vs%20Inter-Article%20Metadata.md) · Related: [The Four Lanes](../The%20Four%20Lanes/The%20Four%20Lanes.md)
