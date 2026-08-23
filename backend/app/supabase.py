from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

import httpx

from backend.app.models import ArtifactInfo, Event, Job, Message
from backend.app.settings import settings, supabase_configured

logger = logging.getLogger(__name__)


class SupabaseRepository:
    def __init__(self) -> None:
        self.timeout = 15.0

    @property
    def enabled(self) -> bool:
        return supabase_configured()

    def persist_job(self, job: Job) -> None:
        if not self.enabled:
            return
        try:
            self._upsert("investigations", self._job_row(job), "id")
            if job.messages:
                self._upsert(
                    "investigation_messages",
                    [self._message_row(job.id, message) for message in job.messages],
                    "id",
                )
            if job.events:
                self._upsert(
                    "investigation_events",
                    [self._event_row(job.id, event) for event in job.events],
                    "investigation_id,event_id",
                )
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Supabase job persistence failed for %s: %s", job.id, error)

    def persist_artifact(self, job: Job, artifact: ArtifactInfo, path: Path) -> None:
        if not self.enabled:
            return
        owner = job.owner_id or "unassigned"
        storage_path = f"{owner}/{job.id}/{artifact.filename}"
        structured_payload: object | None = None
        if path.suffix.lower() == ".json":
            try:
                structured_payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                structured_payload = None
        try:
            self._upload(storage_path, path, artifact.media_type)
            self._upsert(
                "investigation_artifacts",
                self._artifact_row(
                    job.id,
                    job.owner_id,
                    artifact,
                    storage_path,
                    structured_payload,
                ),
                "investigation_id,filename",
            )
            if artifact.stage in {"plan", "synthesis", "simulation"} and structured_payload is not None:
                self._patch(
                    "research_results",
                    {
                        "owner_id": job.owner_id,
                        f"{artifact.stage}_filename": artifact.filename,
                        f"{artifact.stage}_result": structured_payload,
                        "updated_at": job.updated_at.isoformat(),
                    },
                    {"investigation_id": f"eq.{job.id}"},
                )
        except (httpx.HTTPError, ValueError) as error:
            logger.warning(
                "Supabase artifact persistence failed for %s/%s: %s",
                job.id,
                artifact.filename,
                error,
            )

    def persist_validation_error(self, job_id: str, filename: str, error: str) -> None:
        if not self.enabled:
            return
        try:
            self._patch(
                "research_results",
                {"validation_errors": {filename: error}},
                {"investigation_id": f"eq.{job_id}"},
            )
        except (httpx.HTTPError, ValueError) as caught:
            logger.warning(
                "Supabase validation error persistence failed for %s: %s",
                job_id,
                caught,
            )

    def load_jobs(self) -> list[Job]:
        if not self.enabled:
            return []
        try:
            investigations = self._select("investigations")
            messages = self._select("investigation_messages")
            events = self._select("investigation_events")
            artifacts = self._select("investigation_artifacts")
            research_results = self._select("research_results")
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Supabase job hydration failed: %s", error)
            return []
        messages_by_job: defaultdict[str, list[Message]] = defaultdict(list)
        for row in messages:
            investigation_id = str(row["investigation_id"])
            messages_by_job[investigation_id].append(
                Message.model_validate(
                    {
                        "id": row["id"],
                        "speaker": row["speaker"],
                        "body": row["body"],
                        "stage": row.get("stage"),
                        "source_id": row.get("source_id"),
                        "artifact_ids": row.get("artifact_ids") or [],
                        "created_at": row["created_at"],
                    }
                )
            )
        events_by_job: defaultdict[str, list[Event]] = defaultdict(list)
        for row in events:
            investigation_id = str(row["investigation_id"])
            events_by_job[investigation_id].append(
                Event.model_validate(
                    {
                        "id": row["event_id"],
                        "type": row["event_type"],
                        "stage": row.get("stage"),
                        "message": row["message"],
                        "artifact_id": row.get("artifact_id"),
                        "created_at": row["created_at"],
                    }
                )
            )
        artifacts_by_job: defaultdict[str, list[ArtifactInfo]] = defaultdict(list)
        for row in artifacts:
            investigation_id = str(row["investigation_id"])
            artifacts_by_job[investigation_id].append(
                ArtifactInfo.model_validate(
                    {
                        "id": row["artifact_id"],
                        "filename": row["filename"],
                        "media_type": row["media_type"],
                        "bytes": row["bytes"],
                        "stage": row["stage"],
                        "title": row["title"],
                        "purpose": row["purpose"],
                    }
                )
            )
            self._cache_structured_artifact(investigation_id, row)
        for row in research_results:
            errors = row.get("validation_errors")
            if isinstance(errors, dict):
                self._cache_validation_errors(
                    str(row.get("investigation_id") or ""),
                    errors,
                )
        jobs: list[Job] = []
        for row in investigations:
            job_id = str(row["id"])
            jobs.append(
                Job.model_validate(
                    {
                        "id": job_id,
                        "owner_id": row.get("owner_id"),
                        "title": row["title"],
                        "objective": row["objective"],
                        "playbook": row["playbook"],
                        "playbook_id": row.get("playbook_id"),
                        "playbook_title": row.get("playbook_title"),
                        "status": row["status"],
                        "active_agent": row.get("active_agent"),
                        "active_stage": row.get("active_stage"),
                        "error": row.get("error"),
                        "include_structure": row["include_structure"],
                        "capabilities": row.get("capabilities") or [],
                        "devin_session_id": row.get("devin_session_id"),
                        "session_url": row.get("session_url"),
                        "seen_devin_ids": row.get("seen_devin_ids") or [],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "messages": sorted(
                            messages_by_job[job_id],
                            key=lambda item: item.created_at,
                        ),
                        "events": sorted(
                            events_by_job[job_id],
                            key=lambda item: item.id,
                        ),
                        "artifacts": artifacts_by_job[job_id],
                        "limitations": row.get("limitations") or [],
                    }
                )
            )
        return jobs

    def download_artifact(self, job_id: str, filename: str, destination: Path) -> bool:
        if not self.enabled:
            return False
        try:
            rows = self._select(
                "investigation_artifacts",
                {
                    "investigation_id": f"eq.{job_id}",
                    "filename": f"eq.{filename}",
                    "select": "storage_path",
                    "limit": "1",
                },
            )
            if not rows or not rows[0].get("storage_path"):
                return False
            storage_path = str(rows[0]["storage_path"])
            response = self._request(
                "GET",
                f"/storage/v1/object/{settings.supabase_artifact_bucket}/{quote(storage_path)}",
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(response.content)
            return True
        except (httpx.HTTPError, ValueError, OSError) as error:
            logger.warning(
                "Supabase artifact download failed for %s/%s: %s",
                job_id,
                filename,
                error,
            )
            return False

    def verify_user(self, access_token: str) -> str | None:
        if not self.enabled:
            return None
        try:
            response = self._request(
                "GET",
                "/auth/v1/user",
                bearer=access_token,
            )
        except httpx.HTTPError:
            return None
        payload = response.json()
        user_id = payload.get("id") if isinstance(payload, dict) else None
        return str(user_id) if user_id else None

    def _cache_structured_artifact(self, job_id: str, row: dict[str, object]) -> None:
        payload = row.get("structured_payload")
        filename = row.get("filename")
        if payload is None or not isinstance(filename, str):
            return
        path = settings.runs_dir / job_id / filename
        if path.is_file():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _cache_validation_errors(self, job_id: str, errors: dict[str, object]) -> None:
        if not job_id or not errors:
            return
        path = settings.runs_dir / job_id / ".validation_errors.json"
        if path.is_file():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({str(key): str(value) for key, value in errors.items()}, indent=2),
            encoding="utf-8",
        )

    def _upload(self, storage_path: str, path: Path, content_type: str) -> None:
        self._request(
            "POST",
            f"/storage/v1/object/{settings.supabase_artifact_bucket}/{quote(storage_path)}",
            content=path.read_bytes(),
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )

    def _upsert(
        self,
        table: str,
        payload: dict[str, object] | list[dict[str, object]],
        conflict: str,
    ) -> None:
        self._request(
            "POST",
            f"/rest/v1/{table}",
            params={"on_conflict": conflict},
            json_payload=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    def _select(
        self,
        table: str,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        response = self._request(
            "GET",
            f"/rest/v1/{table}",
            params=params or {"select": "*"},
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Supabase returned a non-list response for {table}")
        return [row for row in payload if isinstance(row, dict)]

    def _patch(
        self,
        table: str,
        payload: dict[str, object],
        params: dict[str, str],
    ) -> None:
        self._request(
            "PATCH",
            f"/rest/v1/{table}",
            params=params,
            json_payload=payload,
            headers={"Prefer": "return=minimal"},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_payload: dict[str, object] | list[dict[str, object]] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        bearer: str | None = None,
    ) -> httpx.Response:
        request_headers = {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {bearer or settings.supabase_service_role_key}",
            **(headers or {}),
        }
        response = httpx.request(
            method,
            f"{settings.supabase_url}{path}",
            params=params,
            json=json_payload,
            content=content,
            headers=request_headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    @staticmethod
    def _job_row(job: Job) -> dict[str, object]:
        return {
            "id": job.id,
            "owner_id": job.owner_id,
            "title": job.title,
            "objective": job.objective,
            "playbook": job.playbook,
            "playbook_id": job.playbook_id,
            "playbook_title": job.playbook_title,
            "status": job.status.value,
            "active_agent": job.active_agent.value if job.active_agent else None,
            "active_stage": job.active_stage,
            "error": job.error,
            "include_structure": job.include_structure,
            "capabilities": [item.value for item in job.capabilities],
            "devin_session_id": job.devin_session_id,
            "session_url": job.session_url,
            "seen_devin_ids": job.seen_devin_ids,
            "limitations": job.limitations,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        }

    @staticmethod
    def _message_row(job_id: str, message: Message) -> dict[str, object]:
        return {
            "id": message.id,
            "investigation_id": job_id,
            "speaker": message.speaker.value,
            "body": message.body,
            "stage": message.stage,
            "source_id": message.source_id,
            "artifact_ids": message.artifact_ids,
            "created_at": message.created_at.isoformat(),
        }

    @staticmethod
    def _event_row(job_id: str, event: Event) -> dict[str, object]:
        return {
            "investigation_id": job_id,
            "event_id": event.id,
            "event_type": event.type,
            "stage": event.stage,
            "message": event.message,
            "artifact_id": event.artifact_id,
            "created_at": event.created_at.isoformat(),
        }

    @staticmethod
    def _artifact_row(
        job_id: str,
        owner_id: str | None,
        artifact: ArtifactInfo,
        storage_path: str | None,
        structured_payload: object | None,
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "investigation_id": job_id,
            "owner_id": owner_id,
            "artifact_id": artifact.id,
            "filename": artifact.filename,
            "media_type": artifact.media_type,
            "bytes": artifact.bytes,
            "stage": artifact.stage,
            "title": artifact.title,
            "purpose": artifact.purpose,
        }
        if storage_path is not None:
            row["storage_path"] = storage_path
        if structured_payload is not None:
            row["structured_payload"] = structured_payload
        return row


supabase = SupabaseRepository()
