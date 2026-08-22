from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from backend.app.artifacts import artifact_path, list_artifacts
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
from backend.app.models import Job, JobCreate, JobStatus, MessageCreate, Speaker
from backend.app.settings import missing_devin_settings, settings, snapshot_configured
from backend.app.store import new_message, store

app = FastAPI(title="ehl-cognition", version="0.1.0")
JOB_PUBLIC = {"seen_devin_ids"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    missing = missing_devin_settings()
    return {
        "status": "ok" if not missing else "not_configured",
        "runtime": "devin-sandbox",
        "configured": not missing,
        "missing": missing,
        "snapshot_configured": snapshot_configured(),
    }


@app.get("/api/jobs", response_model=list[Job], response_model_exclude=JOB_PUBLIC)
def list_jobs() -> list[Job]:
    return sorted((_public_job(job) for job in store.list()), key=lambda job: job.created_at, reverse=True)


@app.post("/api/jobs", response_model=Job, response_model_exclude=JOB_PUBLIC)
def create_job(body: JobCreate) -> Job:
    job = store.create(body.objective, body.title, body.include_structure)
    if body.devin_session_id:
        session_id, session_url = normalize_session_ref(body.devin_session_id)
        store.update(job.id, devin_session_id=session_id, session_url=session_url)
    _spawn(run_job, job.id)
    return _public_job(store.get(job.id) or job)


@app.get("/api/jobs/{job_id}", response_model=Job, response_model_exclude=JOB_PUBLIC)
def get_job(job_id: str) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.devin_session_id and not os.environ.get("PYTEST_CURRENT_TEST"):
        sync_job(job_id)
        job = store.get(job_id) or job
    return _public_job(job)


@app.post("/api/jobs/{job_id}/messages", response_model=Job, response_model_exclude=JOB_PUBLIC)
def post_message(job_id: str, body: MessageCreate) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if not job.devin_session_id:
        raise HTTPException(409, "no Devin sandbox session for this job")
    if job_is_busy(job):
        raise HTTPException(409, "sandbox session is still working")
    store.add_message(job_id, new_message(Speaker.user, body.body.strip()))
    store.update(job_id, status=JobStatus.running, active_agent=Speaker.reviewer, active_stage="follow-up")
    _spawn(answer_follow_up, job_id, body.body)
    return _public_job(store.get(job_id) or job)


@app.post("/api/jobs/{job_id}/harvest", response_model=Job, response_model_exclude=JOB_PUBLIC)
def harvest_job(job_id: str) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if not job.devin_session_id:
        raise HTTPException(409, "no Devin sandbox session for this job")
    if job.status == JobStatus.running:
        raise HTTPException(409, "sandbox session is still running")
    store.update(job_id, status=JobStatus.running, active_agent=Speaker.reviewer, active_stage="import", error=None)
    _spawn(import_session, job_id)
    return _public_job(store.get(job_id) or job)


@app.get("/api/jobs/{job_id}/artifacts/{filename}")
def get_artifact(job_id: str, filename: str) -> FileResponse:
    if store.get(job_id) is None:
        raise HTTPException(404, "job not found")
    if filename == "structure.pdb":
        from backend.app.artifacts import ensure_structure_pdb

        ensure_structure_pdb(job_id)
    path = artifact_path(job_id, filename)
    if path is None:
        raise HTTPException(404, "artifact not found")
    media = "chemical/x-pdb" if filename.endswith(".pdb") else None
    return FileResponse(path, filename=filename, media_type=media)


@app.get("/api/jobs/{job_id}/events")
async def stream_events(job_id: str) -> StreamingResponse:
    if store.get(job_id) is None:
        raise HTTPException(404, "job not found")

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
            signature = f"{public.status.value}:{public.active_stage}:{bodies}:{files}"
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


@app.on_event("startup")
def _resume_sandbox_jobs() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _spawn(resume_running_jobs)


def _spawn(fn: Callable[..., None], *args: object) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        fn(*args)
        return
    threading.Thread(target=fn, args=args, daemon=True).start()


def _public_job(job: Job) -> Job:
    return job.model_copy(
        update={
            "messages": visible_messages(job.messages),
            "artifacts": list_artifacts(job.id),
        }
    )
