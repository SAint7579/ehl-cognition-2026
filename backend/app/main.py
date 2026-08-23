from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Callable

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app import executor
from backend.app.artifacts import artifact_path, list_artifacts, media_type
from backend.app.chatfilter import visible_messages
from backend.app.devin import normalize_session_ref
from backend.app.executor import (
    answer_follow_up,
    import_session,
    job_is_busy,
    resume_running_jobs,
    run_job,
    sync_job,
)
from backend.app.models import Job, JobCreate, JobStatus, MessageCreate, ProtocolInfo, Speaker
from backend.app.research import (
    CapabilityInfo,
    ResearchWorkspace,
    catalog_response,
    load_workspace,
)
from backend.app.settings import (
    env_value,
    missing_devin_settings,
    settings,
    snapshot_configured,
    supabase_configured,
)
from backend.app.store import new_message, store
from backend.app.supabase import supabase


_protocol_cache: tuple[float, list[dict[str, object]]] | None = None
PROTOCOL_CACHE_SECONDS = 30.0


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        _spawn(resume_running_jobs)
    yield


app = FastAPI(title="ehl-cognition", version="0.1.0", lifespan=lifespan)
auth_scheme = HTTPBearer(auto_error=False)
JOB_PUBLIC = {"owner_id", "seen_devin_ids"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


def authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
) -> str | None:
    if not supabase_configured():
        return None
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "authentication required")
    user_id = supabase.verify_user(credentials.credentials)
    if user_id is None:
        raise HTTPException(401, "invalid or expired access token")
    return user_id


def owned_job(job_id: str, user_id: str | None) -> Job:
    job = store.get(job_id)
    if job is None or (user_id is not None and job.owner_id != user_id):
        raise HTTPException(404, "job not found")
    return job


@app.get("/api/health")
def health() -> dict[str, object]:
    missing = missing_devin_settings()
    return {
        "status": "ok" if not missing else "not_configured",
        "runtime": "devin-sandbox",
        "configured": not missing,
        "missing": missing,
        "snapshot_configured": snapshot_configured(),
        "supabase_configured": supabase_configured(),
    }


@app.get("/api/jobs", response_model=list[Job], response_model_exclude=JOB_PUBLIC)
def list_jobs(user_id: str | None = Depends(authenticated_user)) -> list[Job]:
    return sorted(
        (_public_job(job) for job in store.list(user_id)),
        key=lambda job: job.created_at,
        reverse=True,
    )


@app.get("/api/capabilities", response_model=list[CapabilityInfo])
def list_capabilities() -> list[CapabilityInfo]:
    return catalog_response()


@app.get("/api/protocols", response_model=list[ProtocolInfo])
def list_protocols(user_id: str | None = Depends(authenticated_user)) -> list[ProtocolInfo]:
    del user_id
    return [_protocol_info(item) for item in _discover_playbooks()]


@app.post("/api/jobs", response_model=Job, response_model_exclude=JOB_PUBLIC)
def create_job(
    body: JobCreate,
    user_id: str | None = Depends(authenticated_user),
) -> Job:
    selected_id = body.playbook_id or env_value("DEVIN_PLAYBOOK_ID") or None
    selected_title: str | None = None
    if body.playbook_id:
        matching = next(
            (item for item in _discover_playbooks() if item.get("playbook_id") == body.playbook_id),
            None,
        )
        if matching is None:
            raise HTTPException(400, "unknown Devin playbook id")
        selected_title = str(matching.get("title") or "") or None
    elif selected_id:
        matching = next(
            (item for item in _discover_playbooks() if item.get("playbook_id") == selected_id),
            None,
        )
        selected_title = str(matching.get("title") or "") or None if matching else None
    job = store.create(
        body.objective,
        body.title,
        body.include_structure,
        body.capabilities,
        user_id,
        selected_id,
        selected_title,
    )
    if body.devin_session_id:
        session_id, session_url = normalize_session_ref(body.devin_session_id)
        store.update(job.id, devin_session_id=session_id, session_url=session_url)
    _spawn(run_job, job.id)
    return _public_job(store.get(job.id) or job)


@app.get("/api/jobs/{job_id}", response_model=Job, response_model_exclude=JOB_PUBLIC)
def get_job(
    job_id: str,
    user_id: str | None = Depends(authenticated_user),
) -> Job:
    job = owned_job(job_id, user_id)
    if job.devin_session_id and not os.environ.get("PYTEST_CURRENT_TEST"):
        sync_job(job_id)
        job = store.get(job_id) or job
    return _public_job(job)


@app.get("/api/jobs/{job_id}/research", response_model=ResearchWorkspace)
def get_research_workspace(
    job_id: str,
    user_id: str | None = Depends(authenticated_user),
) -> ResearchWorkspace:
    job = owned_job(job_id, user_id)
    return load_workspace(job_id, job.capabilities, job.objective)


@app.post("/api/jobs/{job_id}/messages", response_model=Job, response_model_exclude=JOB_PUBLIC)
def post_message(
    job_id: str,
    body: MessageCreate,
    user_id: str | None = Depends(authenticated_user),
) -> Job:
    job = owned_job(job_id, user_id)
    if not job.devin_session_id:
        raise HTTPException(409, "no Devin sandbox session for this job")
    if job_is_busy(job):
        raise HTTPException(409, "sandbox session is still working")
    store.add_message(job_id, new_message(Speaker.user, body.body.strip()))
    store.update(job_id, status=JobStatus.running, active_agent=Speaker.reviewer, active_stage="follow-up")
    _spawn(answer_follow_up, job_id, body.body)
    return _public_job(store.get(job_id) or job)


@app.post("/api/jobs/{job_id}/harvest", response_model=Job, response_model_exclude=JOB_PUBLIC)
def harvest_job(
    job_id: str,
    user_id: str | None = Depends(authenticated_user),
) -> Job:
    job = owned_job(job_id, user_id)
    if not job.devin_session_id:
        raise HTTPException(409, "no Devin sandbox session for this job")
    if job.status == JobStatus.running:
        raise HTTPException(409, "sandbox session is still running")
    store.update(job_id, status=JobStatus.running, active_agent=Speaker.reviewer, active_stage="import", error=None)
    _spawn(import_session, job_id)
    return _public_job(store.get(job_id) or job)


@app.get("/api/jobs/{job_id}/artifacts/{filename}")
def get_artifact(
    job_id: str,
    filename: str,
    user_id: str | None = Depends(authenticated_user),
) -> FileResponse:
    owned_job(job_id, user_id)
    if filename == "structure.pdb":
        from backend.app.artifacts import ensure_structure_pdb

        ensure_structure_pdb(job_id)
    path = artifact_path(job_id, filename)
    if path is None:
        destination = settings.runs_dir / job_id / filename
        if supabase.download_artifact(job_id, filename, destination):
            path = artifact_path(job_id, filename)
    if path is None:
        raise HTTPException(404, "artifact not found")
    return FileResponse(path, filename=filename, media_type=media_type(filename))


@app.get("/api/jobs/{job_id}/events")
async def stream_events(
    job_id: str,
    user_id: str | None = Depends(authenticated_user),
) -> StreamingResponse:
    owned_job(job_id, user_id)

    async def generate() -> AsyncIterator[str]:
        last = ""
        while True:
            job = store.get(job_id)
            if job is None:
                break
            public = _public_job(job)
            payload = public.model_dump(mode="json")
            bodies = ":".join(str(len(item.body)) for item in public.messages)
            files = ":".join(f"{item.filename}:{item.bytes}" for item in public.artifacts)
            events = ":".join(
                f"{item.id}:{item.type}:{len(item.message)}" for item in public.events
            )
            signature = f"{public.status.value}:{public.active_stage}:{bodies}:{events}:{files}"
            if signature != last:
                yield f"data: {json.dumps({'type': 'job', 'job': payload})}\n\n"
                last = signature
            if public.status.value in {"complete", "failed"}:
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

def _spawn(fn: Callable[..., None], *args: object) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        fn(*args)
        return
    threading.Thread(target=fn, args=args, daemon=True).start()


def _public_job(job: Job) -> Job:
    local_artifacts = list_artifacts(job.id)
    artifacts = {item.filename: item for item in job.artifacts}
    artifacts.update({item.filename: item for item in local_artifacts})
    return job.model_copy(
        update={
            "messages": visible_messages(job.messages),
            "artifacts": list(artifacts.values()),
        }
    )


def _discover_playbooks() -> list[dict[str, object]]:
    global _protocol_cache
    now = time.monotonic()
    if _protocol_cache and now - _protocol_cache[0] < PROTOCOL_CACHE_SECONDS:
        return _protocol_cache[1]
    try:
        raw = executor.get_client().list_playbooks()
    except Exception:
        raw = []
    _protocol_cache = (
        now,
        [
            item
            for item in raw
            if isinstance(item, dict)
            and isinstance(item.get("playbook_id"), str)
            and isinstance(item.get("title"), str)
        ],
    )
    return _protocol_cache[1]


def _protocol_info(item: dict[str, object]) -> ProtocolInfo:
    return ProtocolInfo(
        id=str(item["playbook_id"]),
        title=str(item["title"]),
        has_structured_output_schema=isinstance(item.get("structured_output_schema"), dict),
    )
