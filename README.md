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

## Workspace API and UI

The FastAPI layer is a **control room**, not a local scientific runtime. One
objective becomes one Devin Cloud sandbox session (`protein-engineering-v1`).
Devin runs `bioctl investigate` on a Linux VM; this laptop only creates the
session, polls it, and copies attached artifacts into the right-hand pane.

Copy `.env.example` and set a `cog_` service-user key plus org id. A snapshot
that already has this repo and the CPU toolchain (`mmseqs`, `mafft`,
`foldseek`, `mkdssp`) is strongly recommended:

```sh
cp .env.example .env
# DEVIN_API_KEY, DEVIN_ORG_ID, DEVIN_SNAPSHOT_ID
set -a && source .env && set +a
python -m pip install -e .
python -m uvicorn backend.app.main:app --reload --port 8000
```

```sh
cd frontend && npm install && npm run dev
```

Open http://127.0.0.1:5173. `GET /api/health` reports whether Devin credentials
are present. There is no local `bioctl` fallback for jobs; missing
`DEVIN_API_KEY` / `DEVIN_ORG_ID` fails the job instead of running on the Mac.

`POST /api/jobs` opens a session. Follow-ups stay on that same session.
`GET /api/jobs/{id}` and `/artifacts/{filename}` feed the UI once Devin
attaches `conservation.json`, structure files, and `final_result.json`.

For hosting, deploy the frontend on Vercel and keep FastAPI on persistent
compute. [DEPLOYMENT.md](DEPLOYMENT.md) covers the beta and production
architecture, environment variables, constraints, and smoke tests.

Local `bioctl` smoke tests still use `./scripts/bootstrap_tools.sh` for CLI
development only. That path is not the product.

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

## V1 orchestration contract

The versioned [protein-engineering V1 playbook](playbooks/protein_engineering_v1.md)
defines the operator-facing procedure over the sequence, structure, and
candidate slices. Run the complete investigation with:

```sh
bioctl investigate \
  --objective "Identify substrate-cleft and surface engineering sites" \
  --target fixtures/target_ispetase.fasta \
  --database fixtures/homolog_db.fasta \
  --structure fixtures/structures/6EQE.pdb.gz \
  --chain A \
  --references fixtures/structures \
  --out runs/investigate
```

The command writes stage outputs under `sequence/`, `structure/`, and
`candidates/`, plus the schema-validated `final_result.json`. The report
records stage statuses and continues to write the report when a stage fails:
later stages become `SKIPPED` and the command exits 1. Constraints are labeled
`ENFORCED_BY_PIPELINE` only when passed through to candidate ranking; other
constraints are `RECORDED_ONLY`.

The playbook is versioned as `protein-engineering-v1` version `1.0.0`, and its
path and digest are pinned in the final report. The fourth smoke test is:

```sh
./scripts/investigate_smoke_test.sh
```
