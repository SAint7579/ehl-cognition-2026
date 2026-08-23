# System architecture

This repository implements a thin research control room around Devin Cloud.
The browser never calls Devin directly and never receives Devin credentials.

## Runtime flow

```text
React/Vite browser
    |
    | HTTP + reconnecting SSE
    v
FastAPI control room
    |
    | Devin v3 API (server-side credentials)
    v
Devin Cloud session
    |
    | versioned playbook + bioctl
    v
CPU scientific tools and structured artifacts
```

1. The browser submits an objective, optional capabilities, and a laboratory
   protocol to `POST /api/jobs`.
2. FastAPI creates the local job record and starts a Devin Cloud session.
3. Devin follows the selected playbook and operates the scientific tools in
   its Linux sandbox.
4. The backend polls the session, records messages and events, and harvests
   attached artifacts.
5. The browser follows `/api/jobs/{job_id}/events` and renders the resulting
   sequence, structure, candidate, and synthesis evidence.
6. Follow-up messages are sent to the existing Devin session rather than
   starting an unrelated investigation.

## Scientific data flow

```text
target FASTA
  -> MMseqs2 homolog search
  -> MAFFT multiple sequence alignment
  -> conservation and entropy
  -> Foldseek + DSSP structure analysis
  -> sequence/MSA/structure residue mapping
  -> activity and stability candidate rankings
  -> schema-validated final_result.json
```

The scientific pipeline lives under `bio_tools/`. Its public command is
`bioctl`; `bioctl investigate` composes the individual stages. Committed JSON
Schemas under `schemas/` are the contracts between scientific execution,
artifact harvesting, and the UI.

The candidate scores are transparent heuristics, not learned mutation-effect
models. Deposited facts are labelled `KNOWN`, direct software output is
`CALCULATED`, model estimates are `PREDICTED`, agent interpretation is
`INFERRED`, and only uploaded measurements may be labelled `EXPERIMENTAL`.

## Component ownership

| Component | Responsibility |
| --- | --- |
| `frontend/` | Objective entry, live progress, evidence navigation, 3D structure interaction, and follow-up chat |
| `backend/app/main.py` | HTTP API, authentication boundary, job ownership, SSE, and artifact delivery |
| `backend/app/executor.py` | Devin session lifecycle, polling, follow-ups, recovery, and artifact harvesting |
| `backend/app/devin.py` | Devin API transport and session-reference normalization |
| `backend/app/store.py` | In-process job coordination and local job persistence |
| `backend/app/supabase.py` | Optional durable metadata, private artifact storage, and token validation |
| `bio_tools/` | Deterministic CPU-native scientific calculations |
| `playbooks/` | Versioned scientific operating procedures used by Devin |
| `schemas/` | Structured artifact and synthesis contracts |
| `fixtures/` | Small, pinned, network-free demonstration inputs |

## State and persistence

For local development, job state is coordinated in process and artifacts are
written beneath `RUNS_DIR` (default `runs/jobs`). The optional Supabase adapter
adds authenticated ownership, durable metadata, and private object storage.

The hosted beta should use one persistent FastAPI process and a mounted
`RUNS_DIR`. Horizontal scaling requires moving background polling to a durable
worker and treating PostgreSQL/object storage as the source of truth. See
`DEPLOYMENT.md` for the rollout design.

## Security boundaries

- `DEVIN_API_KEY`, `DEVIN_ORG_ID`, `DEVIN_SNAPSHOT_ID`, and the Supabase
  service-role key are backend-only.
- Only `VITE_*` variables may be embedded in the browser build.
- CORS must list explicit frontend origins in hosted environments.
- Artifact access is checked against job ownership when Supabase auth is
  enabled.
- Computational output must not be presented as experimental validation.

## Important invariants

- A follow-up continues the original Devin session.
- Position mapping does not assume that PDB author numbering equals target
  FASTA numbering.
- Every important artifact records tools, versions, parameters, and evidence
  provenance.
- The deterministic fixture path remains available even when live services or
  public databases are unavailable.
