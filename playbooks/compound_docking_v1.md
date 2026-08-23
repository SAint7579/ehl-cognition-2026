---
id: compound-docking-v1
name: CPU compound docking and molecular simulation
version: 1.0.0
updated: 2026-08-23
scope: ligand preparation, docking into a deposited site, and short CPU molecular dynamics
---

# CPU compound docking and molecular simulation

Use this protocol when the question concerns a compound, ligand, or binding
site: docking a molecule, comparing a compound set, or probing the stability of
a complex. The engines here are CPU-native and already installed: AutoDock
Vina, Open Babel, Meeko, RDKit, OpenMM, MDAnalysis. There is no structure
prediction and no learned scoring model; do not install one.

## 1. Plan and identify inputs

Write `research_plan.json` first. State the receptor (deposited PDB entry and
chain), the ligand set (SMILES, SDF, or a named compound), and the site to be
targeted. If the scientist has not named a receptor structure, retrieve a
deposited one and say which entry you chose and why. Never dock into a
predicted structure without saying so explicitly.

## 2. Prepare the receptor and ligands

Strip waters and irrelevant heteroatoms, keep the biologically relevant chain,
and record what was removed. Prepare ligands with RDKit and Open Babel or
Meeko: correct protonation at the stated pH, generate 3D coordinates, and
record the SMILES actually used. Write `ligand_summary.json` with ligand
identity, preparation method, and the files produced. A silent protonation or
tautomer choice invalidates the comparison, so state it.

## 3. Define the site deliberately

Derive the search box from known catalytic or binding residues where they are
documented, not from the whole protein. Record the box centre and size as
parameters. A blind whole-protein box is acceptable only when no site is known,
and must be reported as such.

## 4. Dock

Run AutoDock Vina with an explicit exhaustiveness and seed, and keep the seed
in the parameters so the run can be repeated. Retain the top poses as files.
Inspect the best pose's contacts against the residues expected to matter, and
say whether the pose is chemically sensible rather than only citing the score.

## 5. Optional short dynamics

When pose stability is the question and inputs allow, run a short OpenMM
minimisation and equilibration on the complex, and analyse it with MDAnalysis
(RMSD, contact persistence). A short CPU trajectory probes whether a pose is
immediately unstable; it does not establish binding.

## 6. Report simulations honestly

Write `simulation_results.json` and `simulation_metrics.csv`. A run is
`COMPLETED` only if a real engine command succeeded and quantitative output was
parsed into the artifact; otherwise use `FAILED`, `BLOCKED`, or `SKIPPED` and
say why. A Vina score is a calculated ranking, not a binding affinity, and an
MD metric is not measured stability. Rigid-receptor docking, missing solvent
and cofactors, single protonation states, and short trajectories all belong in
the limitations.

## 7. Synthesize

Integrate docking, structural context, and any retrieved literature into the
structured synthesis output. Rank compounds or poses only against criteria you
state. Where a pose contradicts published mutagenesis or a known binding mode,
report the conflict as counter-evidence. Recommend the wet-lab assay that would
actually discriminate between the remaining possibilities.
