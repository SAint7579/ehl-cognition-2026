# ehl-cognition-2026

## CPU-native bioinformatics pipeline

This repository contains CPU-native scientific vertical slices. A target
protein FASTA is searched against a FASTA database with MMseqs2, aligned with
MAFFT, and analyzed for per-column conservation in pure Python/NumPy. The
structure slice maps a deposited PDB chain to the target and MSA, computes
DSSP annotations, and searches a committed reference set with Foldseek.

Install the project into the supplied environment with
`./.venv/bin/python -m pip install -e .`. The pipeline writes validated JSON
artifacts (`homolog_search.json`, `alignment.json`, `conservation.json`, and
`run.json`) next to the intermediate FASTA files. Each artifact has a
committed JSON Schema under `schemas/` and includes tool/file provenance.
MMseqs2 percent identity is reported on a 0-100 scale. The MMseqs2 and MAFFT
parameters used for each run are recorded in its provenance.
Each stage records digests of its inputs, while the run manifest records
digests of every artifact file produced, since an artifact cannot contain its
own hash.

Evidence is labeled `KNOWN` for the pinned UniProt fixture/database
sequences, `CALCULATED` for direct MMseqs2/MAFFT/conservation output, and
`PREDICTED` or `EXPERIMENTAL` are reserved for future work. The run manifest
states the computational limitations explicitly; no result in this slice is
experimentally validated.

The single smoke-test command is:

```sh
./scripts/smoke_test.sh
```

It runs the committed fixtures into the ignored `runs/` directory and prints
the hit count, alignment length, and top conserved target positions.

The structure smoke test is:

```sh
./scripts/structure_smoke_test.sh
```

It first runs the sequence pipeline, then writes structure artifacts into
`runs/structure_smoke` and prints modelled residues, unmodelled target ranges,
secondary-structure composition, the top Foldseek hit, and the catalytic-triad
mapping. Structure coordinates use three distinct systems: `structure_index`
is the extracted chain sequence index used by Foldseek, `author_residue` is
PDB author numbering plus insertion code, and `target_position` is the
1-based target FASTA position. MSA columns are mapped through target
positions rather than assumed author numbering.

Deposited coordinates and metadata are `KNOWN`; DSSP, Foldseek, and all
sequence-to-structure mappings are `CALCULATED`. None of these results are
experimental validation. Structure annotations also record warnings for
unmodelled residues, numbering irregularities, alternate locations, and
residues excluded or absent from DSSP.
RSA is the raw Sander quotient and can exceed 1 for highly exposed residues,
so such values are flagged rather than clipped.

## Candidate-site ranking

The candidate stage consumes the structure annotations and sequence alignment
artifacts and writes `candidate_sites.json`. It produces two separate,
transparent heuristic shortlists:

- `activity` ranks substrate-cleft sites with
  `d <= 12.0`, `conservation < 0.98`, and `rsa < 0.50`.
  Its score is
  `0.50 * proximity + 0.30 * plasticity + 0.20 * burial`.
- `stability` ranks surface sites away from the active site with
  `d >= 12.0`, `conservation < 0.90`, and `rsa >= 0.25`.
  Its score is
  `0.35 * exposure + 0.30 * variability + 0.20 * remoteness + 0.15 * loop`.

The shared feature definitions are `lin(x, lo, hi) = clamp((x - lo) /
(hi - lo), 0, 1)`, `proximity = 1 - lin(d, 4.0, 12.0)`,
`remoteness = lin(d, 12.0, 25.0)`, `burial = 1 - lin(rsa, 0.0, 0.5)`,
`exposure = lin(rsa, 0.0, 0.5)`,
`plasticity = 1 - lin(conservation, 0.60, 0.98)`,
`variability = 1 - lin(conservation, 0.50, 0.90)`, and `loop = 1.0` for
coil (`C`) and `0.0` otherwise. Fully conserved sites are excluded because
the activity and stability filters require sequence variability, and the
catalytic triad is excluded by default to protect the catalytic residues.

Substitution options are observed residues in the homolog alignment only:
non-gap alternatives occurring at least twice and at frequency at least
`0.15`. They are not predictions, recommendations, or beneficial-effect
claims. The candidate rankings are not predictions of activity or stability,
carry no effect estimate, and are not experimental validation.

The candidate smoke test is:

```sh
./scripts/candidate_smoke_test.sh
```
