# ehl-cognition-2026

## CPU-native bioinformatics pipeline

This repository contains the first scientific vertical slice: a target
protein FASTA is searched against a FASTA database with MMseqs2, aligned with
MAFFT, and analyzed for per-column conservation in pure Python/NumPy.

Install the project into the supplied environment with
`./.venv/bin/python -m pip install -e .`. The pipeline writes validated JSON
artifacts (`homolog_search.json`, `alignment.json`, `conservation.json`, and
`run.json`) next to the intermediate FASTA files. Each artifact has a
committed JSON Schema under `schemas/` and includes tool/file provenance.
MMseqs2 percent identity is reported on a 0-100 scale. The MMseqs2 and MAFFT
parameters used for each run are recorded in its provenance.

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
