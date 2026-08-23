---
id: protein-engineering-v2
name: CPU-native protein engineering investigation
version: 2.0.0
updated: 2026-08-23
scope: sequence, structure, conservation, and candidate-site slices for a named protein
---

# CPU-native protein engineering investigation

Use this protocol when the question concerns a specific protein or enzyme:
which residues matter, how conserved they are, what the structure says, and
which sites are worth mutating. The procedure is CPU only (MMseqs2, MAFFT,
HMMER, Foldseek, DSSP, Biopython, bioctl). There is no structure prediction;
retrieve a deposited structure instead, or say that none exists.

## 1. Plan and pin down the target

Write `research_plan.json` first, naming the protein the scientist actually
asked about. Establish a target FASTA (write one from a named UniProt record if
needed), a homolog database, a deposited structure, and the chain. The
IsPETase files under `fixtures/` are a worked example, not a default target —
never fall back to them for a different protein.

## 2. Run the pipeline

Prefer the single command, pointing every input at the named protein:

```sh
bioctl investigate --objective "<objective>" \
  --target <target.fasta> \
  --database <homologs.fasta> \
  --structure <structure.pdb.gz> \
  --chain <chain> \
  --references fixtures/structures \
  --out /tmp/ehl-investigate
```

It is equivalent to these stages, each consuming the previous stage's output:

```sh
bioctl run --target <target.fasta> --database <database.fasta> --out <out>/sequence
bioctl structure --structure <structure.pdb.gz> --chain <chain> --target <target.fasta> \
  --conservation <out>/sequence/conservation.json --references <references> --out <out>/structure
bioctl candidates --annotations <out>/structure/residue_annotations.json \
  --structure <structure.pdb.gz> --chain <chain> --alignment <out>/sequence/alignment.fasta \
  --out <out>/candidates
```

If bioctl is missing, `pip install -e .`. Do not fabricate bioctl JSON: if a
stage did not run, its artifact does not exist.

## 3. Keep the coordinate systems distinct

`structure_index` is the modelled chain sequence index used by Foldseek,
`author_residue` is the PDB author number with insertion code, `target_position`
is the target FASTA position, and `msa_column` is the alignment column. Never
report a residue number without knowing which of these it is.

## 4. Verify before concluding

Check mapping identity against the target, recovery of the expected catalytic
or functional residues, and the target-position/MSA-column round trip. Activity
and stability candidate shortlists must be disjoint. A low mapping identity or
missing catalytic residues means stop and escalate, not proceed quietly.

## 5. Evidence classes

`KNOWN` is deposited sequences, coordinates, and deposition metadata.
`CALCULATED` is MMseqs2, MAFFT, conservation, DSSP, Foldseek, the mapping, and
heuristic candidate scores. Conservation is evolutionary constraint, not
measured function, and a heuristic score is not a measured effect. `PREDICTED`
and `EXPERIMENTAL` are not produced by this protocol.

## 6. Showing a structure

When asked to see a structure, retrieve the deposited entry, attach
`structure.pdb` and `structure_summary.json`, optionally export a headless
cartoon or surface PNG with a descriptive name, and name the entry and the
residues to highlight in chat. The scientist's Evidence panel renders it.

## 7. Synthesize

Integrate the sequence, structure, conservation, and candidate artifacts into
the structured synthesis output, reading the files rather than recalling the
run. Say where literature, conservation, and structure agree, and where they
do not. For each recommended mutation, give the evidence, the expected effect,
and the assay that would test it. Never present a computed candidate as a
validated variant.

## 8. Escalate

Escalate a failed stage, low mapping identity, missing catalytic residues, a
coordinate-system mismatch, or any request for an experimental claim. Do not
escalate merely because the protein is not IsPETase.
