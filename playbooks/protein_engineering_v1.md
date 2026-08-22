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
only. Retrieving a named UniProt sequence or deposited PDB is allowed when
the scientist named that protein. Do not download large sequence databases
as a substitute for a specified target.

## Runtime

Run this playbook in the Devin Cloud Linux sandbox, not on the operator's
laptop. The control-room API only creates a session, polls it, and copies
attached artifacts. Do not ask the operator to run mmseqs, mafft, foldseek,
mkdssp, or bioctl on their Mac.

The scientist never uses this sandbox desktop. Conversation is on the left of
the control room. Structures, homologs, and other evidence render on the
**right-hand Evidence panel** (browser 3Dmol) from attached files. Do not
open Chrome, a local `view.html` server, PyMOL, nglview, screenshots, or any
other GUI on the sandbox desktop. Do not tell them that images are coming on
the desktop or that they should take control of the VM.

## Preferred operator command

Use this only when the scientist asked for a protein investigation. Point
`--target`, `--database`, `--structure`, and `--chain` at the protein they
named, not at a default enzyme. Write a FASTA and fetch a deposited PDB when
needed. The IsPETase files under `fixtures/` are a worked example, not the
product target.

```sh
bioctl investigate --objective "<objective>" \
  --target <target.fasta> \
  --database <homologs.fasta> \
  --structure <structure.pdb.gz> \
  --chain <chain> \
  --references fixtures/structures \
  --out /tmp/ehl-investigate
```

Attach those JSON artifacts (by basename) to the session when finished.

## Procedure

The investigate command is equivalent to these stages, using the output of
each as the next stage's input:

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

## Artifacts the control room can show

Attach files by short basename. The Evidence panel renders them. Chat is not
the figure viewer.

| Kind | Files | What the scientist sees |
|---|---|---|
| 3D structure | `structure.pdb`, extra `*.pdb` / `*.cif`, `structure_summary.json` | Interactive 3Dmol viewer |
| Figures | `*.png` (also jpg, webp, svg, gif) | Image cards. Use names like `lcc_triad.png` |
| Tables | `*.csv`, `*.tsv` | Preview table |
| Homologs | `homolog_search.json`, `homologs.fasta` | Hit table |
| Conservation | `conservation.json` | Heatmap |
| Candidates | `candidate_sites.json`, `final_result.json` | Ranked sites |
| Other | `alignment.*`, `residue_annotations.json`, `run.json`, `*.md` | File list / science panels |

Headless PNG export is allowed (`matplotlib`, `pymol -cq`). Opening Chrome,
`localhost:8899`, a desktop GUI, or telling them to take control of the VM
is not.

## Showing a structure

When they ask to see a structure (for example "Show me the structure for LCC"):

1. Fetch the deposited PDB (LCC is 4EB0 unless they named another entry).
2. Attach `structure.pdb` and `structure_summary.json` by basename.
3. Optionally render a headless cartoon or surface PNG (`lcc_4eb0_cartoon.png`)
   and attach it. Do not open a desktop viewer.
4. In chat, name the PDB id and any residues to highlight.

The control room shows the PDB in 3D and the PNG under Figures.

## Prohibitions

Do not describe retrieved or calculated evidence as experimental validation.
Do not add learned models. Do not download large sequence databases. Retrieving
a named UniProt record or deposited PDB is allowed.
Do not render structures or other results on the sandbox desktop.

## Escalation

Escalate a failed stage, low mapping identity, missing catalytic residues,
unexpected coordinate-system mismatch, or any request for experimental claims
to a human. Also escalate constraints that the pipeline records but does not
enforce. Do not escalate just because the protein is not IsPETase.
