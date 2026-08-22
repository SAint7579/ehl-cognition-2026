from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.models import Event, Job, JobStatus, Message, Speaker
from backend.app.settings import settings


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, objective: str, title: str | None, include_structure: bool) -> Job:
        now = datetime.now(timezone.utc)
        job = Job(
            id=uuid4().hex[:12],
            title=title or _title_from(objective),
            objective=objective,
            status=JobStatus.queued,
            include_structure=include_structure,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job.id] = job
        (settings.runs_dir / job.id).mkdir(parents=True, exist_ok=True)
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def list(self) -> list[Job]:
        with self._lock:
            return [job.model_copy(deep=True) for job in self._jobs.values()]

    def update(self, job_id: str, **fields: object) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            updated = job.model_copy(update={**fields, "updated_at": datetime.now(timezone.utc)})
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)

    def add_message(self, job_id: str, message: Message) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            messages = [*job.messages, message]
            updated = job.model_copy(
                update={"messages": messages, "updated_at": datetime.now(timezone.utc)}
            )
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)

    def add_event(self, job_id: str, event: Event) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            next_id = (job.events[-1].id + 1) if job.events else 1
            stored = event.model_copy(update={"id": next_id})
            updated = job.model_copy(
                update={
                    "events": [*job.events, stored],
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)


def _title_from(objective: str) -> str:
    text = " ".join(objective.strip().split())
    return text[:72] + ("…" if len(text) > 72 else "")


def new_message(speaker: Speaker, body: str, stage: str | None = None, artifact_ids: list[str] | None = None) -> Message:
    return Message(
        id=uuid4().hex[:10],
        speaker=speaker,
        body=body,
        stage=stage,
        artifact_ids=artifact_ids or [],
        created_at=datetime.now(timezone.utc),
    )


def new_event(event_type: str, message: str, stage: str | None = None, artifact_id: str | None = None) -> Event:
    return Event(
        id=0,
        type=event_type,  # type: ignore[arg-type]
        stage=stage,
        message=message,
        artifact_id=artifact_id,
        created_at=datetime.now(timezone.utc),
    )


store = JobStore()
