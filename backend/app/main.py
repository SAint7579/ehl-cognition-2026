from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from backend.app.artifacts import artifact_path, list_artifacts
from backend.app.executor import answer_follow_up, run_job
from backend.app.models import Job, JobCreate, MessageCreate
from backend.app.settings import settings
from backend.app.store import store
from backend.app.tools import missing_tools, prepend_tool_path

prepend_tool_path()

app = FastAPI(title="ehl-cognition", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    missing = missing_tools()
    return {"status": "ok" if not missing else "missing_tools", "missing_tools": missing}


@app.get("/api/jobs", response_model=list[Job])
def list_jobs() -> list[Job]:
    return sorted(store.list(), key=lambda job: job.created_at, reverse=True)


@app.post("/api/jobs", response_model=Job)
def create_job(body: JobCreate, background: BackgroundTasks) -> Job:
    job = store.create(body.objective, body.title, body.include_structure)
    background.add_task(run_job, job.id)
    return store.get(job.id) or job


@app.get("/api/jobs/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job.model_copy(update={"artifacts": list_artifacts(job_id)})


@app.post("/api/jobs/{job_id}/messages", response_model=Job)
def post_message(job_id: str, body: MessageCreate) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    answer_follow_up(job_id, body.body)
    return store.get(job_id) or job


@app.get("/api/jobs/{job_id}/artifacts/{filename}")
def get_artifact(job_id: str, filename: str) -> FileResponse:
    if store.get(job_id) is None:
        raise HTTPException(404, "job not found")
    path = artifact_path(job_id, filename)
    if path is None:
        raise HTTPException(404, "artifact not found")
    return FileResponse(path, filename=filename)


@app.get("/api/jobs/{job_id}/events")
async def stream_events(job_id: str) -> StreamingResponse:
    if store.get(job_id) is None:
        raise HTTPException(404, "job not found")

    async def generate() -> AsyncIterator[str]:
        last = 0
        while True:
            job = store.get(job_id)
            if job is None:
                break
            for event in job.events[last:]:
                yield f"data: {event.model_dump_json()}\n\n"
                last += 1
            snapshot = {
                "type": "job.snapshot",
                "status": job.status.value,
                "active_agent": job.active_agent.value if job.active_agent else None,
                "active_stage": job.active_stage,
            }
            yield f"data: {json.dumps(snapshot)}\n\n"
            if job.status.value in {"complete", "failed"} and last >= len(job.events):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream")
