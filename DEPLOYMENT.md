# Deployment plan

The browser application is a good fit for Vercel. The current FastAPI control
room should run on a persistent service because investigations outlive a single
HTTP request and the backend currently keeps job state in memory and under
`runs/jobs`.

## Recommended hosted beta

```text
Browser
  │
  ├── React/Vite UI ───────────── Vercel
  │
  └── HTTPS + reconnecting SSE ─ FastAPI on Fly.io, Railway, or Render
                                  │
                                  ├── Devin Cloud API
                                  └── persistent volume for runs/jobs
```

This is the smallest deployment that preserves the application's current job
model:

1. Deploy `frontend` as a Vite project on Vercel.
2. Deploy the repository's FastAPI app on a persistent Python host.
3. Attach a persistent volume and set `RUNS_DIR` to a path on that volume.
4. Set `VITE_API_BASE_URL` in Vercel to the public backend origin.
5. Set `CORS_ORIGINS` on the backend to the Vercel URL and any custom frontend
   domain.

The frontend now supports a separate API origin. Relative `/api` requests remain
the local-development default.

## Why the FastAPI control room should not start on Vercel

FastAPI itself can run as a Vercel Function, and Vercel supports streaming
responses. The problem is the current workload rather than framework support:

- A Devin investigation can run longer than a serverless function's configured
  duration.
- The SSE endpoint stays open and polls job state. Streaming time is still part
  of the function's duration.
- Function instances are ephemeral. In-memory jobs and background threads do
  not survive scale-to-zero, restarts, or routing to another instance.
- The function filesystem is read-only except for temporary storage. `/tmp` is
  not durable storage for research plans, result JSON, structures, or figures.
- A request-triggered background thread is not a durable job worker.

Vercel is therefore suitable for the UI and short request handlers, but the
current control-room process needs persistent compute and storage.

## Environment variables

### Vercel frontend

| Variable | Example | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `https://api.research.example.com` | Public FastAPI origin, without a trailing slash |
| `VITE_SUPABASE_URL` | `https://project.supabase.co` | Public Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | `eyJ...` | Public Supabase anon/publishable key |

### FastAPI backend

| Variable | Required | Purpose |
| --- | --- | --- |
| `DEVIN_API_KEY` | yes | Server-side Devin credential; never expose it to Vite |
| `DEVIN_ORG_ID` | yes | Devin organization |
| `DEVIN_SNAPSHOT_ID` | recommended | Scientific Linux snapshot |
| `RUNS_DIR` | yes for hosted beta | Mounted persistent job directory |
| `CORS_ORIGINS` | yes | Comma-separated allowed frontend origins |
| `DEVIN_BASE_URL` | no | Override only when using a different Devin API endpoint |
| `SUPABASE_URL` | yes when persistence/auth is enabled | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | yes when persistence/auth is enabled | Backend-only Supabase service role credential |
| `SUPABASE_ARTIFACT_BUCKET` | no | Private Storage bucket name; defaults to `research-artifacts` |
| `DEVIN_POLL_TIMEOUT_SECONDS` | no | Absolute Devin wait cap; defaults to 86400 seconds (24 hours) |
| `DEVIN_IDLE_TIMEOUT_SECONDS` | no | Idle wait cap; defaults to 5400 seconds (90 minutes) |

Store these values in the hosting providers' encrypted environment-variable
settings. `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are intentionally
public and are safe to embed in the browser. The Supabase service role key is
backend-only: never put it in frontend variables, source control, or generated
artifacts.

## Supabase setup

1. Create a Supabase project and enable email/password authentication.
   If the project keeps **Confirm email** enabled, new users must confirm their
   address before sign-in will succeed; configure SMTP and the confirmation flow
   or disable that setting for a trusted internal deployment. Signup requests
   are also subject to Supabase's email-send rate limits.
2. Apply `supabase/migrations/20260823010000_research_workspace.sql` with the
   Supabase SQL editor or the Supabase CLI:

   ```sh
   supabase db push
   ```

3. Create a **private** Storage bucket named `research-artifacts` (or set
   `SUPABASE_ARTIFACT_BUCKET` to another private bucket).
4. Set `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and
   `SUPABASE_ARTIFACT_BUCKET` on the backend only.
5. Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` on the frontend.

The backend validates bearer tokens through Supabase Auth and scopes every
investigation to its owner. Artifact bytes are downloaded server-side from the
private bucket. Do not use the service role key in the browser.

## Vercel frontend setup

Do **not** use the FastAPI preset or add `[tool.vercel] entrypoint` in
`pyproject.toml`. That would put the control room on a Vercel Function.

1. Import the GitHub repository in Vercel.
2. Set the Root Directory to `frontend` and the framework to Vite. The
   committed `vercel.json` assumes that directory (do not also prefix
   `frontend` in the install command).
3. Add `VITE_API_BASE_URL` (the public Railway/API origin, no trailing slash).
4. Deploy and add the generated Vercel URL to backend `CORS_ORIGINS`.
5. Add a custom domain after the API and SSE flow pass the smoke tests.

No Vercel rewrite is required when `VITE_API_BASE_URL` points directly to the
backend. A same-origin `/api` proxy can be added later if desired.

## Backend setup

The host must support:

- A long-running ASGI process.
- Outbound HTTPS access to Devin Cloud.
- A persistent mounted directory.
- SSE responses without proxy buffering.
- A health check on `GET /api/health`.
- A request and connection timeout long enough for the configured Devin poller.

The default poll limits allow a turn to run for up to 24 hours, while requiring
some observed progress within each 90-minute idle window. Use a persistent host
without short request or idle timeouts. Vercel serverless functions cannot host
the poller; Vercel remains suitable for the frontend only.

Run:

```sh
uvicorn backend.app.main:app --host 0.0.0.0 --port "$PORT"
```

Set `RUNS_DIR` to the mounted volume, for example `/data/ehl-cognition/jobs`.
Use one backend process for the hosted beta because the current in-memory store
coordinates background polling inside that process.

## Production architecture for laboratory use

Before horizontal scaling or relying on the service for durable lab records,
replace the local job store:

```text
Vercel UI
   │
FastAPI API ───── PostgreSQL: jobs, events, messages, Devin session IDs
   │
Durable worker ─ queue: job creation, polling, harvesting, retries
   │
Object storage ─ JSON, CSV, structures, figures, simulation outputs
   │
Devin Cloud
```

Required changes:

1. Move jobs, messages, event cursors, capabilities, and session IDs from memory
   and `job.json` into PostgreSQL.
2. Move artifact bytes to S3-compatible object storage and retain metadata in
   PostgreSQL.
3. Move Devin polling and harvest work from request-started threads to a durable
   queue worker.
4. Publish events through Redis, a database event table, or a managed realtime
   service.
5. Make SSE reconnectable with `Last-Event-ID`; polling is an acceptable
   fallback for serverless clients.
6. Add authentication and lab-level authorization before storing private
   research data.
7. Add retention, deletion, backup, and restore policies.

After those changes, the FastAPI request layer could run on Vercel Functions if
each request stays short and long work runs in the external worker. Keeping the
API and worker together on a persistent host is operationally simpler at first.

## Staged rollout

### 1. Local verification

- Run all backend tests and the production frontend build.
- Start FastAPI and Vite.
- Verify a complete mocked investigation, page reload, and SSE reconnection.

### 2. Hosted demo

- Vercel frontend.
- One persistent FastAPI instance and volume.
- Real Devin Cloud session creation and artifact harvesting.
- Restricted beta users and non-sensitive research inputs.

### 3. Durable beta

- PostgreSQL, object storage, queue worker, authentication, backups.
- Multiple API instances after background work no longer depends on process
  memory.

### 4. Production

- Custom frontend and API domains.
- Monitoring for API latency, Devin polling failures, SSE reconnects, artifact
  ingestion failures, queue depth, and storage growth.
- Restore drills and explicit data-retention controls.

## Production smoke tests

1. `GET /api/health` reports Devin and snapshot configuration.
2. Create a real investigation and receive a Devin session URL.
3. Observe live worklog updates after an SSE reconnect.
4. Open a research plan, synthesis, table, structure, and simulation result
   inline.
5. Reload the page and recover the investigation and artifacts.
6. Send a follow-up after the original investigation completes.
7. Confirm the backend still has the job after a process restart.
8. Confirm no API key or raw secret appears in browser assets, logs, messages,
   or artifacts.

## Relevant Vercel constraints

- [Using FastAPI with Vercel](https://vercel.com/docs/frameworks/backend/fastapi)
- [Vercel Functions limits](https://vercel.com/docs/functions/limitations)
- [Streaming from Vercel Functions](https://vercel.com/docs/functions/streaming-functions)
- [Vercel Functions runtimes](https://vercel.com/docs/functions/runtimes)
