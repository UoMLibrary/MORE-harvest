---
title: The Route-Operator Agents
tags: [harvest, agents]
---

# 🤖 The Route-Operator Agents

> [!abstract] The idea
> The routes are deterministic scripts — that's the whole achievement. So agents don't belong
> *per route*; they belong where **judgement** recurs. Two thin agents, organised by kind of work,
> not by config.

## Why not one agent per route

There are ~11 routes, but they differ by *fetch and asset config*, not by judgement — they share
the machinery ([crosswalk_generic](The%20Four%20Lanes/Lane%20C%20—%20Ingest.md) handles PMC/APS/JHEP/Frontiers/NLM from one
codebase). An agent earns its place at recurring judgement under uncertainty; the harvest lab
deliberately factored judgement *out* into scripts. Eleven near-identical prompts would be a
maintenance smell — and it clashes with the standing principle: *scripts over cheap agents.*

## The two agents (by kind of judgement)

Both live in `MORE-harvest/.claude/agents/` (Opus, per the workspace discipline):

- **`ingest-operator`** — drives the deterministic ingest routes. Its world-model is the [work-tracker](The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md): it reads the do-next queue, kicks a batch, and **triages the
  tail** — classifying each non-clean outcome as *partial* (physics figures short, the known
  boundary), *escalate* (math-as-image, no source), *failed* (a real defect), or *novel*
  (investigate). Kicking the batch is trivial; adjudicating the tail is the job.

- **`transform-author`** — authors or extends a [Lane-C′ transform](The%20Four%20Lanes/Lane%20C′%20—%20Transform.md) when a
  new publisher flavour appears that the generic crosswalk can't ingest. Invoked rarely and
  deliberately, following the `elsevier_to_jats.py` pattern, and proving the result through the
  workstation gates.

## Design rules baked in

- **Thin.** The agents *point at* the canonical context (this vault, the CLAUDE.md, the scripts)
  and *wield the scripts* — they don't restate route knowledge that would drift.
- **The tracker is the operator's memory.** The [worklist DB](The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md) is exactly
  the state an ops agent needs to decide what to run and what needs a human.
- **One-way boundary, absolute.** They *call* the workstation's gate scripts (as the ingest
  scripts already do) but never write into or import from it — and never learn the *consumers* exist.

> [!note] The right frame
> The routes don't want an agent — that they *don't* need one per paper is the win. Agents sit
> where novel judgement recurs: operating the tail, and authoring new transforms.

Related: [The Tools](The%20Production%20Pipeline/The%20Tools.md) · [The DuckDB Lane Router](The%20Production%20Pipeline/The%20DuckDB%20Lane%20Router.md) · *Every Agent Runs Opus*
