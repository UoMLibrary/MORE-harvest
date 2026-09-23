---
title: The Disposition Model
tags: [harvest, router]
---

# 🧭 The Disposition Model

> [!abstract] The idea
> Routing answers "where do I *get* this paper's XML". Disposition answers the bigger question:
> "what does a *human* have to do with it?" — and the answer is driven entirely by the **licence
> of the published version**.

## Three dispositions

Every UoM paper is one of three, computed in the [router](The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md) from its
licence and lane:

| Disposition | Meaning | Route to house JATS |
|---|---|---|
| **automated** | CC-BY *and* open XML exists | [Lane C — Ingest](The%20Four%20Lanes/Lane%20C%20—%20Ingest.md) / [Lane C′ — Transform](The%20Four%20Lanes/Lane%20C′%20—%20Transform.md) — harvest handles it |
| **convert_vor** | Reusable licence (CC-BY / SA / public-domain / CC0), but no open XML | [Lane B — True Conversion](The%20Four%20Lanes/Lane%20B%20—%20True%20Conversion.md) — convert the gold VoR PDF |
| **source_aam** | Not reusable (ND / NC / closed) | [Lane A — Rights-Driven Conversion](The%20Four%20Lanes/Lane%20A%20—%20Rights-Driven%20Conversion.md) — get the author's manuscript |

## The rights logic (this is the crux)

The deciding test is **NoDerivatives**. Converting a Version of Record into JATS *is* creating a
derivative — so any `-nd` licence forbids it. And `-nc` (non-commercial) and closed licences
can't be reused either. For all of those, the published version is off-limits, and the only path
to Green OA is the author's **Accepted Manuscript** — which is exactly why the *workstation* exists.

So the rule, in plain terms: *if the published paper is genuinely open (CC-BY family), use it; if
it isn't, we need the author's manuscript instead.* This is a **rights decision** — the kind a
Green-OA specialist owns — not a technical one.

## Why it completes the model

The [four lanes](The%20Four%20Lanes/The%20Four%20Lanes.md) always implied this decision; disposition names it. It also
reconnects the whole harvest experiment to the original mission: the biggest bucket,
**source_aam**, is the reason the AAM workstation was built in the first place.

## It also decides author approval

Because disposition tracks the content's rights status, it doubles as the rule for author
consent: `source_aam` records need **author approval** — which, under the
*handover model*, happens downstream: they export into
the live infrastructure marked *awaiting author approval* (the in-Platform release flow this
note once pointed at was retired in the 2026-07-16 pare-down); `automated` / `convert_vor`
don't (already-published CC-BY). The *Platform dashboard* surfaces
all of this.

> [!note] 2025 corpus (9,189 works)
> automated **3,240** · convert_vor **~2,130** · source_aam **3,815**. The source-AAM split by
> licence: 2,626 closed/none, 635 CC-BY-NC-ND, 368 CC-BY-NC, 137 other-OA, plus NC-SA and ND.
