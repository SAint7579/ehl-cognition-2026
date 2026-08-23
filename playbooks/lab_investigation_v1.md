---
id: lab-investigation-v1
name: End-to-end laboratory investigation
version: 2.0.0
updated: 2026-08-23
scope: the default protocol — any scientific question, from retrieval through calculation, simulation, and synthesis
---

# End-to-end laboratory investigation

The default protocol. It carries an investigation the whole way: understand the
question, retrieve what is known, calculate, simulate where the question needs
it, and synthesize a scientific answer. Run only the stages the question
actually requires, in this order, each consuming the previous stage's output.
The specialised protocols exist for deep single-domain work; this one should
handle a staged, multi-part request on its own.

## Stage 0 — Plan

Restate the scientist's objective in their terms. Decide the smallest set of
concrete tasks that can actually answer it here. Write and attach
`research_plan.json` before the main work, and reattach it as task statuses
change. Do not pad the plan with tasks you will not run.

## Stage 1 — Establish what is known

Retrieve the specific records that bear on the question: named sequences,
deposited structures, database entries, primary literature. Prefer one named
record or a small targeted search over bulk downloads. Never fall back to the
`fixtures/` example files for a different target. Record every source in
`literature_sources.csv` with enough identity (accession, PDB id, DOI, URL) for
the scientist to return to it, and separate what a paper claims from what the
deposited record actually contains.

## Stage 2 — Sequence and conservation

When the question concerns a protein: pin down a target FASTA, collect a small
homolog set (MMseqs2 or a named set), align with MAFFT, and calculate
per-position conservation. Write `conservation.json`. Conservation is
evolutionary constraint, not measured function. Keep the coordinate systems
distinct and never report a residue number without knowing which system it is
in: chain `structure_index`, PDB `author_residue` (with insertion code), target
FASTA `target_position`, alignment `msa_column`. Verify mapping identity and the
recovery of expected functional residues before building on the mapping; a poor
mapping means stop and escalate.

## Stage 3 — Structure

Use a deposited structure — there is no structure prediction here; if none
exists, say so. Attach `structure.pdb` and `structure_summary.json`, run DSSP
and Foldseek comparisons where they inform the question, and write
`residue_annotations.json` mapping the residues of interest with their evidence
class and conservation. When the scientist wants to see the structure, name the
entry and the residues to highlight in chat and optionally attach a headless
cartoon or surface PNG; the Evidence panel renders it.

## Stage 4 — Docking and simulation

CPU engines only, all installed: AutoDock Vina, Open Babel, Meeko, RDKit,
OpenMM, MDAnalysis. Prepare the receptor (strip waters and irrelevant
heteroatoms, keep the relevant chain, record what was removed) and the ligands
(protonation at a stated pH, 3D coordinates, the SMILES actually used) and write
`ligand_summary.json`. Derive the search box from the residues Stage 2 and 3
identified rather than blind-boxing the protein, and record the box, the
exhaustiveness, and the seed as parameters so the run repeats. Keep the top
poses as files and judge the best pose by its contacts against the residues
expected to matter, not by score alone. Where pose stability is the question, a
short OpenMM minimisation and equilibration analysed with MDAnalysis probes
whether a pose is immediately unstable — it does not establish binding.

Write `simulation_results.json` and `simulation_metrics.csv`. A run is
`COMPLETED` only if a real engine command succeeded and quantitative output was
parsed into the artifact; otherwise `FAILED`, `BLOCKED`, or `SKIPPED` with the
reason. A Vina score is a calculated ranking, not a binding affinity, and an MD
metric is not measured stability. Rigid receptor, absent solvent and cofactors,
single protonation states, and short trajectories belong in the limitations.

## Stage 5 — Evidence classes

`KNOWN` is deposited or published records. `CALCULATED` is anything this sandbox
computed: searches, alignments, conservation, DSSP, Foldseek, docking scores,
statistics, simulations. `PREDICTED` requires that a prediction model actually
ran. `EXPERIMENTAL` is wet-lab validation and is never produced here. Calculated
evidence is not experimental evidence, and a score is not a measurement.

## Stage 6 — Synthesize

Integrate the artifacts into the structured synthesis output, reading the files
you produced rather than recalling the run. Say where literature, conservation,
structure, and simulation converge and where they conflict — counter-evidence
stays visible, including a docked pose that contradicts published mutagenesis.
Name what remains unresolved. Recommend next experiments that follow from the
specific uncertainty you found, each with its supporting evidence and the assay
that would discriminate between the remaining possibilities. Never present a
computed candidate as a validated variant.

## Escalation

Escalate when a required input is missing, a tool or dataset is unavailable, a
stage failed, the coordinate systems disagree, the data cannot support the
question as asked, or the honest answer is that the calculation was
inconclusive. Say what is missing and offer options. Never fabricate a result,
a source, or a structured artifact.
