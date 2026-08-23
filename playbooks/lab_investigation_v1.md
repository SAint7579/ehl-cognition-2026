---
id: lab-investigation-v1
name: General laboratory investigation
version: 1.0.0
updated: 2026-08-23
scope: any scientific question the sandbox can answer with retrieval, calculation, and synthesis
---

# General laboratory investigation

The default protocol. Use it when the question is not specifically a protein
investigation or a compound docking study.

## 1. Turn the question into a plan

Restate the scientist's objective in their terms. Decide the smallest set of
concrete tasks that can actually answer it with the data and tools available
here. Write `research_plan.json` and attach it before starting the main work,
then reattach it as task statuses change. Do not pad the plan with tasks you
do not intend to run.

## 2. Establish what is already known

Retrieve the specific public records that bear on the question: named
sequences, deposited structures, database entries, primary literature. Prefer
one named record or a small targeted search over bulk downloads. Record every
source in `literature_sources.csv` with enough identity (accession, PDB id,
DOI, URL) that the scientist can go back to it.

## 3. Calculate

Run the real calculation in this sandbox with real data. Python, pandas,
SciPy, RDKit, Biopython, and the installed bioinformatics tools are all
available. Never substitute prose for a calculation the scientist asked for.
Write structured results to `analysis_results.json` and tabular results to
`analysis_table.csv`, and export figures headlessly as descriptively named
PNGs.

## 4. State the evidence class for everything

`KNOWN` is only deposited or published records. `CALCULATED` is anything this
sandbox computed: searches, alignments, statistics, scores, simulations.
`PREDICTED` requires that a prediction model actually ran. `EXPERIMENTAL` is
reserved for wet-lab validation and is never produced here. Calculated
evidence is not experimental evidence, and a score is not a measurement.

## 5. Synthesize

Integrate the artifacts into the structured synthesis output. Read the files
you produced; do not synthesize from memory of what you did. State
convergence and conflicts, keep counter-evidence visible, name what remains
unresolved, and recommend next experiments that follow from the specific
uncertainty you found.

## 6. Escalate rather than guess

Escalate to the scientist when a required input is missing, a tool or dataset
is unavailable, the data cannot support the question as asked, or the honest
answer is that the calculation was inconclusive. Say what is missing and offer
options. Never fabricate a result, a source, or a structured artifact.
