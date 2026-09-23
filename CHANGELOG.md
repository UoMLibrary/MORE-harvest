# Engine changelog — MORE-harvest

The answer to "did we regress?", "wasn't this fixed already?", and "what needs
re-doing after this change?" — in one place, newest first.

**The discipline:** every change to the TRANSFORMATION (crosswalk, converters,
cleaners), the GATES (validate / house-lint / licence), or the RENDER
(render_article) gets an entry **in the same commit as the change**. Each entry
says what changed, which package classes it affects, and which of the three
remediation types it requires:

- **re-render** — article.html regenerates from article.xml; a Platform sync
  picks it up. No package is rebuilt. (Render-only fixes.)
- **re-lint** — packages are unchanged but their gate verdicts are stale;
  re-run the gates and update sidecars/log. (Gate hardenings.)
- **re-ingest** — the packages themselves are wrong; rebuild the AFFECTED CLASS
  (never a blanket --redo) and re-sync. (Transform fixes.)

Scope tags: `[transform]` `[gates]` `[render]` `[router]` `[ops]`.

---

## 2026-09-02

- **[router]** The lane-routing policy moved out of `harvest_openalex.build_db`
  into a `routing/` package. It had been six hand-written `CASE` expressions
  inline in the DuckDB build — the most consequential judgement in the pipeline
  (which route each paper takes, and therefore which lane, which assets and what
  a human must do with it) expressed as SQL string interpolation, readable only
  by reading the plumbing around it.

  `routing/rules.py` now holds the policy as ordered, first-match-wins `Rule`
  tables with the publisher sets as named constants and a `why` on every arm;
  `routing/__init__.py` compiles those tables to the same SQL and applies them;
  `python -m routing --explain` prints the whole thing as a decision table. The
  comments that recorded real findings (the SCOAP3 'other' three-way split, the
  NoDerivatives test behind `source_aam`, why asset `none` is an escalation flag)
  travelled with the rules rather than being left behind with the SQL.

  **Behaviour-preserving, and pinned rather than trusted:** `tests/test_routing.py`
  keeps the original SQL verbatim as a golden reference and requires row-for-row
  agreement on all six derived columns (`scoap3`, `route`, `route_access`,
  `asset_route`, `lane`, `disposition`) across every `works_*.duckdb` on disk —
  **16 databases, 81,585 works, zero differences**. `build-db --year 1968` was
  then rebuilt end to end and diffed against its pre-change backup: identical.

  No package content affected — **no remediation**. Deliberate routing changes
  from here must update `LEGACY_SQL` in that test in the same commit, so the next
  change is measured against the new baseline.

- **[ops]** The health ledger: `audit_ledger.py` + `audits.jsonl` (append-only
  JSONL, operational data, gitignored). regate and corpus_fsck each append one
  summary line per run — timestamp, scope, duration, engines, drift/damage
  counts — so the corpus has a LONGITUDINAL health record, not just the latest
  snapshot: "the gates hardened N times and the corpus absorbed every one" is
  now a queryable sentence. Scoped (--route/--limit) runs carry their scope so
  they never masquerade as a full bill of health. The Platform's Operations
  tab reads the last full-scope line of each kind into a "Corpus health"
  strip (one-way producer-state read, sanctioned use #2). No package content
  affected — no remediation.
- **[ops]** `corpus_fsck.py` — the physical-integrity auditor, regate's
  counterpart for the SUBSTANCE: re-hashes every asset against its sidecar
  manifest, verifies article.xml parses and matches a recorded baseline hash
  (`artifacts.article_sha256_16` — stamped at ingest from now on, `--baseline`
  stamps older packages), reports strays the manifest doesn't know, missing
  anzsrc.xml, and — Lane B — LOST RE-CHECK CAPABILITY (fetched PDF/TEI gone,
  the W4407753528 class: found in the wild today, noticed only because a
  fidelity re-run happened to look). Read-only except `--baseline`; damage vs
  advisory classes; `--strict` for a CI-style exit code. Sidecar gains the
  article hash (additive). No package content affected — no remediation; run
  the audit routinely (it is the remediation-finder).
- **[gates]** The fidelity gate joins the verdict-versioning framework.
  `gate_fingerprints()` gains `fidelity` — one content-hash over
  `lanec/pdf_fidelity.py` + `lanec/publisher_rules.py` (the checker AND the
  floors it reads, so a threshold change re-judges like a code change) —
  stamped into `gates.engine` ONLY for packages that carry a fidelity verdict
  (`stale_gates` likewise skips fidelity for Lane-C packages: a package can
  never be stale on a gate that does not apply to it). `regate.py` now RE-RUNS
  fidelity LIVE when the source PDF + TEI survive in `fetched/<route>/` and the
  works DB yields the publisher floor — a fidelity hardening becomes a cheap
  re-check, not a re-ingest; when inputs are gone the recorded verdict is
  re-applied keeping its ORIGINAL engine attribution (a re-applied verdict
  never wears today's stamp). Verified on the full corpus: 31 of the 32
  fidelity-carrying packages re-ran live, every verdict identical to
  ingest-time; the one whose fetched inputs are gone (W4407753528) re-applied
  unattributed, as designed. Affects sidecar stamps only. Remediation: the
  same `regate.py --apply` sweep, run with this change.
- **[gates]** Verdict versioning + the standing re-lint sweep. Every sidecar's
  `gates` block now records WHICH gate engines issued its verdicts
  (`gates.engine` — content-hashes of validate_jats.py / jats_house_lint.py /
  licence_verdict, computed at run time) plus `gates.checked_at`. Content
  hashes rather than hand-bumped numbers because the validate/lint gates live
  in the workstation's repo, out of reach of pipeline_versions.py's
  same-commit discipline. New `gates_run.py` is the ONE implementation of the
  three package-level gates (run + parse + fingerprint) — `ingest_one` [3/3]
  and the new `regate.py` both call it, so ingest-time and sweep-time verdicts
  cannot drift. `licence_verdict` moved ingest_one → gates_run (re-exported).
  `regate.py` is the machine for this changelog's "re-lint" remediation type:
  re-judges finished packages with today's gates (structural gates re-run,
  raw-LaTeX guard recomputed from the document, recorded fidelity verdict
  re-applied), reports GREEN->RED / RED->GREEN / newly-judged drift, and with
  `--apply` rewrites sidecars (flipped verdicts keep `gates.previous`) and
  reindexes the log/DB so the board reflects today's standard. Affects every
  ingested package's SIDECAR on the first applied sweep (verdicts + stamps;
  package content untouched). Remediation: `python regate.py --apply` now, and
  after every future gate hardening.
- **[gates]** `ingest_one.licence_verdict` scopes the canonical-CC-URI search to
  `<permissions>` first, whole-document only as fallback — a CC URL merely CITED
  in a data statement or reference can no longer decide the article's flavour.
  (Investigating the three 2026-07-17 "gates-green-but-failed" PMC papers proved
  they were GENUINE CC-BY-NC/-ND in their own permissions — OpenAlex's cc-by
  label was wrong and the gate was right; this entry is hardening the latent
  first-URL-wins case, not fixing those.) No package content affected; verdicts
  can only get MORE precise — no remediation.
- **[router]** `build_db` pins the router's comparison columns (license/journal/
  publisher → VARCHAR, in_pmc/has_pdf → BOOLEAN) after `read_json_auto`: a small
  single-year intake batch (a year holding ONE work with a null licence) made
  inference type `license` as JSON, which broke every string comparison in the
  route/disposition CASEs ("Malformed JSON ... Input: cc-by" — the works_1968
  crash that stalled the 2026-07-17 intake backlog at 2,812 unresolved DOIs).
  `build_db` also now retries-then-defers when a works DB is held open (the
  Platform's live reload ATTACHes them at exactly the moments a resolve run
  rebuilds them) instead of crashing the whole resolve on PermissionError.
  Affects the router only; no package content — no remediation. Rebuilt DBs
  healed on the first fixed resolve run.

## 2026-07-17

- **[ops]** OpenAlex org key now travels as the Bearer header in `ingest_one.
  openalex_authors` and `ingest_batch.openalex_topic` (both now route through
  `harvest_openalex.get`). As an `api_key` query param the key was IGNORED and
  every call fell into the budget-capped keyless pool — the same failure
  `dbde355` fixed in `harvest_openalex.get` itself. `ingest_batch` no longer
  hard-requires `openalex_key.txt` on disk (env var works too). No package
  content affected; no remediation.
- **[ops]** Multi-year ingest: `ingest_log.year_for(work_id)` finds which
  `works_YYYY.duckdb` knows a work; `ingest_one`'s metadata reads, `ingest_batch`
  mid minting (`MORE-{year}-…`, seq suffix still global so mids never collide)
  and the log's DB mirror all use it instead of a hardcoded 2025. Previously a
  non-2025 work got a `MORE-2025-*` mid, `None` sidecar metadata and a no-op
  mirror UPDATE against the wrong DB. Affects future non-2025 ingests only; no
  remediation for existing 2025 packages.
- **[ops]** The `ingest_log` DuckDB mirror (record / index_sidecar) now degrades
  gracefully when the Platform's live refresh holds a works DB open — the JSON
  log/sidecar write is the truth, the mirror prints a skip note and `build-db`
  catches the DB up. Previously a locked DB crashed `ingest_batch` mid-run after
  the log write.
- **[ops]** `fetch_vor_pdfs --with-tei` now gunzips content-service TEI on magic
  bytes (the endpoint serves gzip with no Content-Encoding header, as
  `fetch_tei` documents) instead of landing raw gzip bytes named
  `.grobid.xml`. Existing pilot TEIs fetched via `--with-tei` are worth a
  magic-bytes audit. `fetch_figures._discover_pmcid` now sends the mailto
  address (not the User-Agent string) as NCBI's `email` param.

## 2026-07-15

- **[transform]** Lane B author fallback (`lanec/tei_to_jats.py` v3 +
  `ingest_one.openalex_authors`). The 32-paper production run surfaced a class of
  failures where GROBID's header parse recovered NO authors, hard-failing validate
  ("no <contrib>") even though the body was complete (the fidelity gate passed
  them — e.g. W4406195136 at completeness 0.87). ingest_one now fetches the
  authoritative OpenAlex authorships (metadata-only) and passes them via
  `--authors`; tei_to_jats uses TEI authors first and falls back to that list
  ONLY on total recovery failure (a partial GROBID list is kept as-is) — same
  discipline as the journal/title/licence fallbacks, never fabricated. Verified:
  W4406195136 validate FAIL → PASS. Affects: Lane-B works with an empty GROBID
  author parse. Remediation: re-ingest that class on the next Lane-B run (the
  4 empty-body cases stay failed — correctly — because the fidelity gate rejects
  them regardless of authors). Golden suites unchanged (both green).

- **[router]** Lane B wired into production (`fetch_router.py`): the three
  convert_vor routes (`gated_commercial` / `repository` / `convert`) get a fetch
  adapter — GROBID TEI + the VoR PDF, both from the OpenAlex content service
  (Enterprise key), landing as `fetched/{route}/{wid}.xml + .pdf`. Fetching both
  from the archive means the fidelity gate's TEI/PDF pairing is version-consistent
  by construction. TEI-gated selection (`AND has_grobid` — 782 of 2,080 pending
  works qualify; the rest wait for the true PDF converter); Lane B's skip unit is
  the PAIR (an xml missing its pdf completes the pair, never refetches the xml).
  `ingest_batch --route convert|repository|gated_commercial` now just works.
  Remediation: none (new capability).

- **[gates]** Lane-B fidelity gate (`lanec/pdf_fidelity.py`, ingest_one step [2e],
  pipeline step `fidelity` v1). Lane B converts ONE extractor's silent output
  (GROBID); the structural gates validate what exists, never what's missing. The
  new gate compares the finished package against an independent reading of its own
  PDF — five checks with thresholds CALIBRATED on the 76-pair pilot corpus (see
  the module docstring; letter-bearing shingles kill the two known noise classes):
  ref parity (hard, TEI biblStruct == JATS ref), grounding ≥0.60 (hard — catches
  wrong TEI/PDF pairing), completeness (<0.40 fail / 0.40–0.65 flag / ≥0.65 pass;
  `PublisherRule.fidelity_floor` overrides), body mass (hard — catches empty body
  + bad fetch), numbers (advisory). FAIL → lint_pass=False, never ships clean
  (ingest_batch reads the `[2e] fidelity:` line); FLAG ships with the reason in
  the tracker and the largest missing runs in the sidecar. Corpus behaviour:
  73 PASS / 1 FLAG (line-numbered RSC proof) / 2 FAIL (empty body; 1-page bad
  fetch). Standing evidence tool: `fidelity_calibrate.py` (report →
  harvest/tei_pilot/fidelity_calibration.json); thresholds move only on its
  evidence, here. Golden test: `tests/fidelity_pilot.py` (intact passes;
  dropped-body and dropped-ref mutants must not). Remediation: none (new gate;
  packages gain the sidecar block as they rebuild). Production pair
  W4407753528 re-ingested same day (tei_to_jats v2 remediation): fidelity PASS
  .89/.90, refs 43/43; figures remain the honest attended boundary (partial).

- **[ops]** Golden-suite baseline extended (`--rebase`): the committed Lane-B
  fixture (`tests/fixtures/laneb_W7133915096.*` — T&F CC-BY 4.0 TEI + PDF-text
  snapshot + authoritative meta, for fidelity_pilot) is auto-discovered by
  crosswalk_pilot, so it now ALSO pins the TEI branch in the Lane-C golden suite
  (first committed Lane-B fixture — the 2026-07-15 codebase review's ask). All
  six prior fixtures unchanged.

- **[transform]** Lane B back matter mapped (`lanec/tei_to_jats.py` v2). GROBID
  parses funding / acknowledgements / data-availability / appendices into typed
  TEI `<back>` divs; the converter dropped ALL of them — found by the fidelity-gate
  calibration (93/93 such divs lost across the 76-pair pilot corpus, every package
  lint-green; house-lint validates what exists, not what's missing). Now mapped to
  house homes: funding → `<funding-group>/<funding-statement>` (article-meta, as
  PMC packages have it), acknowledgement → `<ack>`, availability →
  `<sec sec-type="data-availability">`, annex → `<app-group>/<app>` (GROBID's
  mis-split heading fragments fold into the preceding appendix). Inline refs in
  back prose become xrefs and ride the normal relink/unwrap passes. Feeds the
  crate layer's funding_transparency + open-data indicators, which read exactly
  these statements. Affects: Lane-B (TEI-derived) packages only — 1 in
  production (`fetched/convert/` hand-placed pair). Remediation: re-ingest that
  one on next Lane-B run; pilot corpus re-validated same day (no gate
  regressions).

- **[ops]** Incremental Platform sync (Platform-side, `scripts/collect_real.py`):
  each manifest entry fingerprints its source files; unchanged packages reuse
  their previous entry and payload (no re-parse/copy/render). 242-package sync:
  78s → 5.7s; a one-package change rebuilds one. `--full` forces the old
  wipe-and-rebuild. Remediation: none.

- **[ops]** Lane-C golden fixtures (`tests/crosswalk_pilot.py` + 6 committed
  CC-BY source XMLs). Semantic assertions per publisher flavour — articleset
  unwrapping, aff-id synthesis, zero residual LaTeX, citation/formula counts,
  DTD validity — run BEFORE committing any transform change (tei_pilot.py is
  Lane B's twin). `--rebase` moves the baseline; doing so requires a CHANGELOG
  entry saying why. Remediation: none (test-only).

- **[ops]** Pipeline version stamps + targeted rebuild query. Every new sidecar
  records the engine step versions that built it (`pipeline_versions.py`,
  stamped by `sidecar.py`); `rebuild_scan.py` lists exactly which packages a
  given step-bump affects (`--step`, `--route`, `--ids`). Pre-stamping packages
  read as version 0 (stale for any queried step) until their next natural
  rebuild. Remediation: none — stamps accrue as packages rebuild.

## 2026-07-14

- **`1273f0f` [transform]** Sidecar titles flatten `<tex-math>` to readable
  Unicode (`$W$` → W, `\sqrt{s}` → √s). Affects: any package whose JATS title
  carries formulas (JHEP; rare elsewhere). Remediation: re-ingest of the 3
  built JHEP packages — **done** same day.

- **`649ab43` [transform]** Residual-LaTeX guard counts only convertible tokens
  and skips whole formula subtrees — PMC's proper
  `<tex-math>\begin{document}$$…$$\end{document}` is legitimate math, not
  residue. Fixes the guard's false positives (10 clean PMC papers were wrongly
  flagged and needlessly re-ingested). Remediation: none (guard-only).

- **`7e544ca` [transform]** Body LaTeX → JATS (`lanec/latex_body_clean.py` +
  ingest_one step [2d] + raw-LaTeX guard). JHEP A++ BodyRef full-text embeds
  the author's LaTeX in prose; packages shipped gate-green but rendered as
  source (`\cite{…}`, raw `$…$`). Now: `\cite` → linked `<xref>`, maths →
  `<inline/disp-formula><tex-math>` for MathJax; residual LaTeX forces the
  package off "clean" (the lint doesn't police prose LaTeX — the guard does).
  Affects: scoap3_jhep (3 built packages; 92 pending build correctly), any
  LaTeX-in-prose source. Remediation: re-ingest of the 3 — **done** same day.
  NOTE: closes the body-level half of the raw-LaTeX problem; the caption half
  was `latex_caption_clean.py` (2026-07-13, scoped to captions by design).

- **`9127986` [transform]** Crosswalk: descend into `<pmc-articleset>` wrappers
  (some Europe PMC fullTextXML wraps the article); synthesize missing `<aff>`
  ids. Cut the PMC failure rate 27% → 9%. Affects: pmc route. Remediation:
  re-ingest of the failed PMC papers — **done** same day (--redo 246,
  failed 30 → 23; residuals are genuine attended-QA).

- **`bfc3594` [transform]+[gates-remediation]** Supplementary capture: the
  2026-07-13 workstation lint hardening (local hrefs must resolve) had
  invalidated 146/150 PMC packages (stale-green sidecars). Crosswalk pass C now
  fetches PMC supplementary files from the Europe PMC zip; unresolvable
  self-uri dropped with a log; `repair_local_hrefs.py` backfilled the corpus.
  Also: crosswalk keeps `mml`/`xlink` namespace declarations that
  cleanup_namespaces stripped as unused. Affects: pmc (all), any package with
  supplementary refs. Remediation: corpus backfill — **done** same day.
  LESSON: every gate hardening needs a re-lint + backfill sweep planned with it.

- **`c3b2167` [transform]** Lane B exists: GROBID TEI → generic JATS
  (`lanec/tei_to_jats.py` + `publisher_rules.py`), proven 72/76 lint-green on
  the 5-publisher TEI corpus. Also fixed a latent ingest_one bug: `route` was
  derived from the reassigned intermediate path (broke publisher-figure lookup
  for every pre-transformed source, Elsevier included). Affects: convert_vor
  (new capability); no existing packages. Remediation: none.

- **`82a7bde` / `3ad9efa` [ops]/[router]** Intake auto-resolve watcher; reviews
  scoped into the year-sweep (`type:article|review`). NOTE: the existing 2025
  board predates the review scope-in — a 2025 re-harvest is still pending
  (deliberately deferred).

## 2026-07-13 (pre-monorepo-history, recorded for completeness)

- **[gates]** Workstation lint hardening (local-href resolution, tightened name
  checks — workstation repo). Consequence for harvest: gate verdicts recorded
  before it are stale-green until re-linted (see `bfc3594`).
- **[transform]** `latex_caption_clean.py` — LaTeX → Unicode in CAPTIONS only
  (body explicitly out of scope, see its docstring; body half closed by
  `7e544ca`).

## 2026-07-10

- **`d35b8bb` [gates]+[transform]** Licence verified per work (fail-closed
  licence_verdict on the packaged document) + Elsevier transform fixes.

## 2026-07-08 (pre-monorepo, in `a987c29`)

- **[transform]** `repair_repo_pdf_figs.py` — scoap3_jhep figures landed as
  caption-only `<fig-group>` with no `<graphic>`; repair wires PDF-recovered
  images; wired into ingest_one.
