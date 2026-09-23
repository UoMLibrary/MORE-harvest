# `lanec/` — the transforms

Everything that turns *somebody else's* XML into *our* XML. These are the modules
`ingest_one.py` calls; nothing here fetches, and nothing here writes a package.

The design rule throughout: **a transform is written once and run over every paper of its
class.** No hand-authoring, no per-paper judgement. Where a paper needs judgement, it goes
to `escalate` in the worklist rather than getting special-cased here.

---

## The chain

Every route converges on `crosswalk_generic.py`. What differs is how much work happens
before it:

```
Lane C   publisher JATS ─────────────────────────────────► crosswalk_generic ─► house JATS
Lane C′  Elsevier XML ──► elsevier_to_jats ──► generic JATS ─► crosswalk_generic ─► house JATS
Lane B   GROBID TEI ────► tei_to_jats ───────► generic JATS ─► crosswalk_generic ─► house JATS
                          (+ publisher_rules)                       (+ pdf_fidelity gate)
```

`elsevier_to_jats.py` and `tei_to_jats.py` play the same role for their inputs: rewrite a
foreign vocabulary element-by-element into **plain JATS**, then let the shared crosswalk add
the house layer (manuscript-id, ANZSRC, licence, figure hrefs) and run the gates.

## The modules

| Module | Role |
|---|---|
| `crosswalk_generic.py` | **The core.** Any publisher JATS dialect → house JATS 1.4 Archiving. Handles APS (JATS Publishing + OASIS tables) and the older NLM-2.x flavour PMC/Frontiers and many native-OA publishers still emit — normalising the NLM-2.x ↔ JATS-1.x differences that break DTD validation. |
| `elsevier_to_jats.py` | Lane C′. Elsevier `ce:`/`ja:`/`sb:` DTD 5.x → generic JATS (Physics Letters B, Nuclear Physics B via SCOAP3). MathML is already proper and is kept. Figures reference external NDATA entities, so graphics are left as `fig{N}` placeholders for the caller's figure step. |
| `tei_to_jats.py` | Lane B. GROBID TEI → generic JATS, for the ~half of convert_vor works OpenAlex has already parsed. GROBID does not reliably recover the journal title or the licence, so those come from the works record, not the TEI. |
| `publisher_rules.py` | Lane B's per-publisher rule objects. GROBID emits the same TEI schema for everyone, but how well it parsed a given PDF varies by typesetting — so the pipeline is one shared core plus a small rule object per publisher (reference style, whether headings carry numeric prefixes, and so on). |
| `latex_body_clean.py` | For `scoap3_jhep` and other repo-PDF routes whose A++ full-text embeds the author's raw LaTeX in text nodes: `\cite{…}` → linked `<xref>`, `$…$` → `<tex-math>` formulas, plus cleanup. Operates only inside prose containers and never touches existing formula markup. |
| `pdf_fidelity.py` | **Lane B's gate** (`ingest_one` step 2e). See below. |

## The Lane-B fidelity gate

Worth understanding before trusting any Lane-B package.

Lane B converts **one extractor's silent output**. The structural gates validate what
*exists* in a package; nothing checks what *should* exist. The proof is in the history: the
back-matter hole dropped all 93 of 93 divisions — funding, acknowledgements, availability
statements, annexes — while every package linted green. Nothing caught it until this gate's
calibration did.

`pdf_fidelity.py` closes that hole by reading the package's **own PDF** independently and
doing set arithmetic on two token streams. It is the workstation's council-of-extractors
principle at Lane-B economics: no adjudication queue, no agent, ~2–4 seconds per paper.

Its five thresholds were **measured** on the 76-pair pilot corpus (2026-07-15). They move
only on `../fidelity_calibrate.py` evidence, recorded in `../CHANGELOG.md` — not on
judgement, and not to make a batch pass.

## Testing a change

```bash
python ../tests/crosswalk_pilot.py    # Lane C fixtures — run before committing
python ../tei_pilot.py                # Lane B's twin
```

`RESULTS.md` in this folder is the original Lane-C proof of concept (2026-07-04, a
*Phys. Rev. D* paper), kept for its measured timings — the evidence behind the "minutes,
not sessions" claim.

Any change to a transform needs a `../CHANGELOG.md` entry in the same commit, tagged with
the remediation it forces: **re-render**, **re-lint**, or **re-ingest of the affected
class**. `../rebuild_scan.py` turns that into the actual package list.
