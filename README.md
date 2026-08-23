# Aletheia Reference-Table Audits

**Deterministic internal-consistency audits of the world's laboratory-physics reference tables, run end to end by a one-person AI-augmented verification lab.**

Project Aletheia is an independent research lab (one human, several adversarial AI systems) built around a single idea: take published scientific claims and data products, test them against the most boring explanation that could produce them, and publish what survives together with what does not. The lab's first confirmed institutional correction was in NASA/JPL's close-approach database: eight internally inconsistent records, reported privately, confirmed by JPL as a software issue, and corrected.

This repository holds the complete audit machinery from the lab's August 2026 campaign against nuclear physics' two flagship reference tables.

## What the machine did

The lab's discovery pipeline generated and ranked the targets itself: a two-arm question-expansion step (a sealed reasoning arm plus a wide automated crack-finding sweep) proposed ten auditable "cracks" across laboratory-physics reference data, ranked by checkability. The top routes then ran end to end:

**AME2020, the atomic mass evaluation.** Every derived column (binding energies, beta-decay energies, twelve separation and reaction energy columns, chained closure identities) was recomputed from the primary mass values with exact rational arithmetic: 51,937 eligible checks per rounding envelope. Result: **zero inconsistent rows**. The world's mass table is arithmetically airtight, a clean bill independently reproduced by a second AI system with its own parser. A residual class of 16 last-digit disagreements between the table's two published editions was chased through the journal-printed edition, a sibling file, and NUBASE2020 under a preregistered wager, and resolved as rounding-boundary ties: no error.

**ENSDF, the evaluated nuclear structure file.** All 299,105 placed gamma records in the adopted-levels datasets were checked against their own level schemes (level minus level must equal gamma plus recoil), with uncertainties treated as one-sigma statistics and flags raised only beyond ten times the summed uncertainties plus an absolute floor. Sixty-one records survived. Every one was then read: evidence packets with the record's comments, its dataset's footnote definitions, an exhaustive explanation search with negative receipts, and a cross-dataset placement search. Forty-eight dissolved into the archive's own documentation (documented poor fits, source-scheme mixing). Thirteen did not. Those thirteen were reported **privately to the maintainers first** — this repository deliberately omits their identities pending the maintainers' adjudication, per the lab's private-first policy.

## How the lab keeps itself honest

Every number above survived a process designed to kill it:

- **Preregistration before outcomes.** Frozen inputs (SHA-256-pinned), frozen relations, frozen envelopes, frozen eligibility rules. Rule changes forced by evidence are numbered amendments on the record, never silent edits.
- **Controls with teeth.** Planted errors of both signs and sizes that must be caught, clean fixtures that must pass, and deletion mutations: removing any load-bearing component must flip a planted verdict, or the gate is decorative.
- **Adversarial review.** A second AI system (OpenAI Codex) reviewed each route line by line, reimplementing parsers and arithmetic from scratch. It refuted early versions of three routes; every refutation and repair is preserved in the campaign record. Five review rounds total.
- **A blind arm.** The final ENSDF classifications were replicated by the second system from the evidence packets alone, answers hidden: agreement on 60 of 61 records and on all 13 candidates.
- **Honest nulls.** The AME clean bill and the resolved edition-tie class are published results here, not discarded attempts.

Nine reusable methodology lessons (on rounding-step semantics, control binding, verifier versioning, grammar-from-token-census, and more) were compiled into the lab's permanent memory during this campaign, several of them caught by the adversarial reviewer.

## Reproduction

The audits are deterministic and network-free at scoring time.

1. Download the public source files: AME2020 (`mass_1.mas20.txt`, `rct1.mas20.txt`, `rct2_1.mas20.txt`, `massround.mas20.txt` from the IAEA Atomic Mass Data Center) and the ENSDF monthly distribution (`ensdf_260805.zip` from NNDC). SHA-256 pins are in each script.
2. Run `src/lab_bench_r1_ame_closure_verifier_v1_1.py --mode controls` then `--mode census` for the mass table.
3. Run `src/lab_bench_r2_ensdf_closure_verifier_v3.py --mode controls` then `--mode census` for the structure file.
4. The R4 chain (`lab_bench_r4_evidence_extractor_v2.py`, `lab_bench_r4_flag_resolution_v1.py`, `lab_bench_r4_classification_v3.py`, gated by `lab_bench_r4_controls_v3.py`) builds the per-record evidence packets and the classification census.

Paths at the top of each script point at the lab's directory layout; adjust the `ROUTE`/`RAW` constants to your checkout.

## The program

This campaign is two routes of a ranked queue. The same playbook is aimed next at the particle-physics listings, the international metrology comparison network, the stopping-power tables, and the standard atomic weights. The thesis under test: the cheapest audit in science — a reference table's own arithmetic, run exhaustively with the footnotes actually read — has never been fully cleared, and one person with the right machine can clear it.

**Contact:** Bo Brothers · bo@projectaletheia.org · [projectaletheia.org](https://projectaletheia.org)
