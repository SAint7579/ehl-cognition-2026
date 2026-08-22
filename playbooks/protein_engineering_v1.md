---
id: protein-engineering-v1
name: CPU-native protein engineering investigation
version: 1.0.0
updated: 2026-08-22
scope: sequence, structure, and candidate-site scientific slices
---

# Protein-engineering V1 playbook

## Objective and inputs

Record the operator's objective verbatim. Inputs are a target protein FASTA,
an offline homolog FASTA database, a deposited structure file and chain, and
the committed Foldseek reference structure directory. The procedure is CPU
only and uses no database downloads or network access.

## Procedure

Run these commands in order, using the output of each stage as the next
stage's input:

```sh
bioctl run --target <target.fasta> --database <database.fasta> --out <out>/sequence
bioctl structure --structure <structure.pdb.gz> --chain A --target <target.fasta> --conservation <out>/sequence/conservation.json --references <references> --out <out>/structure
bioctl candidates --annotations <out>/structure/residue_annotations.json --structure <structure.pdb.gz> --chain A --alignment <out>/sequence/alignment.fasta --out <out>/candidates
```

## Coordinate systems and checks

The sequence-to-structure mapping keeps four coordinate systems distinct:
`structure_index` is the modelled chain sequence index used by Foldseek,
`author_residue` is the PDB author number and insertion code,
`target_position` is the target FASTA position, and `msa_column` is the
alignment column. Verify mapping identity against the target, recovery of the
catalytic triad, and the target-position/MSA-column round trip. Candidate
activity and stability shortlists must be disjoint.

## Evidence taxonomy

`KNOWN` is reserved for deposited sequences, coordinates, and deposition
metadata. `CALCULATED` labels MMseqs2, MAFFT, conservation, DSSP, Foldseek,
mapping, and heuristic candidate scores. `PREDICTED` and `EXPERIMENTAL` are
reserved and unused by this playbook. Retrieved or calculated evidence is not
experimental validation.

## Prohibitions

Do not describe retrieved or calculated evidence as experimental validation.
Do not download databases, use network access in tests, add learned models, or
run outside the CPU-native toolchain.

## Escalation

Escalate a failed stage, low mapping identity, missing catalytic residues,
unexpected coordinate-system mismatch, absent required fixture, or any request
for experimental claims to a human. Also escalate constraints that the
pipeline records but does not enforce.
