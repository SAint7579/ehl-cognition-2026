# Testing and verification

Use the smallest relevant layer while developing, then run the full gate before
merging a milestone. The deterministic scientific tests do not require network
access, but they do require the CPU tools installed in the Devin snapshot.

## Prerequisites

- Python 3.12 virtual environment at `.venv/`.
- Project installed with `.venv/bin/python -m pip install -e .`.
- MMseqs2, MAFFT, Foldseek, and `mkdssp` available on `PATH` for scientific
  integration tests.
- Node dependencies installed from the lockfile with `npm ci` in `frontend/`.

Verify the scientific environment:

```sh
python --version
mmseqs version
mafft --version
foldseek version
mkdssp --version
python -c "import Bio,numpy,pandas,scipy,sklearn,logomaker,biotite"
```

## Fast pull-request gate

From the repository root:

```sh
.venv/bin/python -m pytest -q
```

From `frontend/`:

```sh
npm ci
npm run build
```

The Python suite covers schema stability, scientific calculations, real CLI
integration over committed fixtures, API behavior, authentication boundaries,
persistence adapters, timeout handling, and capability routing. The frontend
production build is the current type-check and bundling gate.

## Scientific smoke tests

Run the smoke tests in increasing order:

```sh
./scripts/smoke_test.sh
./scripts/structure_smoke_test.sh
./scripts/candidate_smoke_test.sh
./scripts/investigate_smoke_test.sh
```

They write ignored output beneath `runs/` and exercise:

1. MMseqs2 homolog search, MAFFT alignment, and conservation.
2. Foldseek/DSSP structure analysis and residue-coordinate mapping.
3. Separate activity and stability candidate rankings.
4. The complete orchestration contract and `final_result.json`.

The structure smoke test must retain the PETase catalytic-triad mapping:

| Author residue | Target position | MSA column |
| --- | --- | --- |
| Ser160 | 160 | 177 |
| Asp206 | 206 | 223 |
| His237 | 237 | 255 |

The committed fixture currently produces 265 modelled residues, target range
`1-28` as unmodelled, and 5XJH as the top Foldseek reference hit. A changed
result is not automatically wrong, but it requires an explicit fixture,
parameter, or algorithm explanation in the pull request.

## Artifact inspection

After `investigate_smoke_test.sh`, inspect `runs/investigate_smoke/`:

- `sequence/` contains homolog, alignment, and conservation evidence.
- `structure/` contains structure summary and residue annotations.
- `candidates/` contains the two transparent heuristic rankings.
- `final_result.json` records objective, constraints, stages, artifacts,
  evidence labels, playbook identity, and limitations.

Confirm that:

- every stage has provenance and a terminal status;
- artifact paths resolve beneath the run directory;
- catalytic residues are excluded from candidate rankings;
- activity and stability remain separate rankings;
- no calculated or inferred result is labelled experimental;
- schemas validate without network access.

## Local application check

Copy `.env.example` to `.env`, add backend-only Devin values, and start FastAPI:

```sh
set -a
source .env
set +a
python -m uvicorn backend.app.main:app --reload --port 8000
```

Start the UI in another terminal:

```sh
cd frontend
npm run dev
```

Check `http://127.0.0.1:8000/api/health` before creating a job. Open
`http://127.0.0.1:5173`, create an investigation, observe SSE progress, inspect
the artifacts, manipulate the 3D structure, and send a follow-up after the
initial run reaches a terminal state.

## Live Devin gate

Live testing consumes external service capacity and must be deliberate. Do not
place credentials in commands, screenshots, commits, browser variables, or
artifacts.

For a release candidate:

1. Confirm the configured snapshot contains the repository and CPU toolchain.
2. Confirm the selected organization playbook matches the intended protocol.
3. Create one investigation through the UI.
4. Record the Devin session URL and the application job ID.
5. Verify live progress, structured synthesis, and artifact harvesting.
6. Send one constraint as a follow-up to the same session.
7. Reload the browser and confirm the job and artifacts remain available.

If live behavior fails, preserve the job ID, session URL, backend error, last
event, and artifact list before retrying. Those five items distinguish API,
sandbox, polling, harvesting, and rendering failures.
