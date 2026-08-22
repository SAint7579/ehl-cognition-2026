from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.capabilities import resolve_capabilities
from backend.app.models import Event, Job, JobStatus, Message, ResearchCapability, Speaker
from backend.app.settings import settings


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.load()

    def load(self) -> None:
        if not settings.runs_dir.is_dir():
            return
        loaded: dict[str, Job] = {}
        for path in settings.runs_dir.glob("*/job.json"):
            try:
                job = Job.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not job.capabilities:
                job = job.model_copy(
                    update={
                        "capabilities": resolve_capabilities(
                            job.objective,
                            [],
                            job.include_structure,
                        )
                    }
                )
            loaded[job.id] = job
        with self._lock:
            self._jobs.update(loaded)
        self._restore_last_session()

    def create(
        self,
        objective: str,
        title: str | None,
        include_structure: bool,
        capabilities: list[ResearchCapability] | None = None,
    ) -> Job:
        now = datetime.now(timezone.utc)
        job = Job(
            id=uuid4().hex[:12],
            title=title or _title_from(objective),
            objective=objective,
            status=JobStatus.queued,
            include_structure=include_structure,
            capabilities=resolve_capabilities(
                objective,
                capabilities or [],
                include_structure,
            ),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job.id] = job
        self._persist(job)
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
        self._persist(updated)
        return updated.model_copy(deep=True)

    def replace_message(self, job_id: str, message_id: str, body: str, source_id: str | None = None) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            messages = []
            for message in job.messages:
                if message.id == message_id:
                    fields: dict[str, object] = {"body": body}
                    if source_id:
                        fields["source_id"] = source_id
                    message = message.model_copy(update=fields)
                messages.append(message)
            updated = job.model_copy(
                update={"messages": messages, "updated_at": datetime.now(timezone.utc)}
            )
            self._jobs[job_id] = updated
        self._persist(updated)
        return updated.model_copy(deep=True)

    def add_message(self, job_id: str, message: Message) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            messages = [*job.messages, message]
            updated = job.model_copy(
                update={"messages": messages, "updated_at": datetime.now(timezone.utc)}
            )
            self._jobs[job_id] = updated
        self._persist(updated)
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
        self._persist(updated)
        return updated.model_copy(deep=True)

    def _persist(self, job: Job) -> None:
        directory = settings.runs_dir / job.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "job.json").write_text(job.model_dump_json(), encoding="utf-8")
        if job.devin_session_id:
            (settings.runs_dir / "last_session.json").write_text(
                json.dumps(
                    {
                        "devin_session_id": job.devin_session_id,
                        "session_url": job.session_url,
                        "objective": job.objective,
                        "title": job.title,
                    }
                ),
                encoding="utf-8",
            )

    def _restore_last_session(self) -> None:
        if self._jobs:
            return
        pointer = settings.runs_dir / "last_session.json"
        if not pointer.is_file():
            return
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        session_id = str(data.get("devin_session_id") or "").strip()
        if not session_id:
            return
        now = datetime.now(timezone.utc)
        job = Job(
            id=uuid4().hex[:12],
            title=str(data.get("title") or _title_from(str(data.get("objective") or "Investigation"))),
            objective=str(data.get("objective") or "Continue the sandbox investigation."),
            status=JobStatus.failed,
            include_structure=True,
            capabilities=resolve_capabilities(
                str(data.get("objective") or "Continue the sandbox investigation."),
                [],
                True,
            ),
            devin_session_id=session_id,
            session_url=data.get("session_url"),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job.id] = job
        self._persist(job)


def _title_from(objective: str) -> str:
    text = " ".join(objective.strip().split())
    return text[:72] + ("…" if len(text) > 72 else "")


def new_message(
    speaker: Speaker,
    body: str,
    stage: str | None = None,
    artifact_ids: list[str] | None = None,
    source_id: str | None = None,
) -> Message:
    return Message(
        id=uuid4().hex[:10],
        speaker=speaker,
        body=body,
        stage=stage,
        source_id=source_id,
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
