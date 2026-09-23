---
type: concept
tags: [harvest, concept]
updated: 2026-07-04
---

# Intra vs Inter-Article Metadata

> [!abstract] The organising idea
> Every fact we hold about a paper is either **intra-article** (about the paper itself) or
> **inter-article** (about how the paper connects to the outside world). This one distinction
> quietly draws our rights line *and* organises the whole lab.

This is the piece of language the whole project hangs on, and it earns its keep three ways.

## The two kinds of fact

- **Intra-article** — facts whose scope is *this one paper*: its title and authors, its subject
  classification, the cataloguer's checklist, which gates it passed, how long it took.
- **Inter-article** — facts that *relate the paper to things outside itself*: the DOIs of the works
  it cites, the matches we find in Crossref and OpenAlex, its own published DOI, the authors it
  shares with other papers in the collection.

## Why it's more than a tidy label

**It draws the rights line by itself.** Intra-article *content* — the actual text of an
author's manuscript — is rights-restricted and stays within our processing environments.
Inter-article *bibliographic strings* — reference
lists, the article's own title for a DOI lookup — are exactly what we're allowed to send out to
scholarly registries. The names of the two categories happen to match the rule we already follow.
That is a good sign a distinction is real and not just decoration.

**It has a second axis: provenance.** Orthogonal to scope, every fact came from somewhere —
`manuscript` (read from the paper), `workstation` (created by our own pipeline and gates), or
`registry` (handed to us by Crossref, OpenAlex, PubMed Central). Scope × provenance classifies
*everything* cleanly, and it maps beautifully onto the knowledge-graph work in the *MORE-crate*
sibling later.

**It tells us which lane a paper can take.** Working out whether a structured version exists (in
[PubMed Central — The Biomedical Half](../Sources/PubMed%20Central%20—%20The%20Biomedical%20Half.md) or [SCOAP3 — The Physics Half](../Sources/SCOAP3%20—%20The%20Physics%20Half.md)) is a purely inter-article
question — it's about the paper's relationships, not its contents. So the lane router
([The DuckDB Lane Router](../The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md)) is built entirely from inter-article metadata, and never has to touch a
word of anyone's manuscript.

## Where it lives

In the lab, this axis is the schema behind the federated read-view (`metadata_lab.py`): the views
are literally named `intra_articles`, `inter_references`, `inter_self_doi`. See [The Tools](../The%20Production%20Pipeline/The%20Tools.md).

---
Prev: [Harvest, Don't Convert](Harvest,%20Don't%20Convert.md) · Next: [The Four Lanes](../The%20Four%20Lanes/The%20Four%20Lanes.md)
