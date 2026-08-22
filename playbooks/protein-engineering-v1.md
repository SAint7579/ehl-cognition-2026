# Protein engineering playbook V1 (CPU-only)

The scientific engine is `bioctl` on this repo, not a second agent loop.

## Commands

```sh
bioctl run --target fixtures/target_ispetase.fasta \
  --database fixtures/homolog_db.fasta --out artifacts/v1

bioctl structure --structure fixtures/structures/6EQE.pdb.gz --chain A \
  --target fixtures/target_ispetase.fasta \
  --conservation artifacts/v1/conservation.json \
  --references fixtures/structures --out artifacts/v1
```

The HTTP API (`backend.app.main`) runs the same functions for a job and
exposes conversation + artifacts. Devin, when wired later, should call these
commands and not invent homologs or structures.

## Rules

- CPU only. Retrieve PDB / AFDB; do not predict folds.
- Never label CALCULATED output as experimental.
- Follow-ups stay on the same job.
- One writer of the scientific files (`bioctl` or a single Devin session).
