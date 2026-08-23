from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import executor
from backend.app.main import app
from backend.app.models import JobStatus, ResearchCapability
from backend.app.settings import settings
from backend.app.store import store
from backend.app.supabase import SupabaseRepository, supabase


@pytest.fixture
def isolated_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(settings, "runs_dir", tmp_path)
    store._jobs.clear()
    monkeypatch.setattr(store, "_persist", lambda job: None)
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
    yield
    store._jobs.clear()


def test_auth_token_validation_and_owner_scoping(
    monkeypatch: pytest.MonkeyPatch, isolated_store: None
) -> None:
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
    monkeypatch.setattr(supabase, "verify_user", lambda token: {"valid": "user-a"}.get(token))
    first = store.create("first objective", None, True, owner_id="user-a")
    second = store.create("second objective", None, True, owner_id="user-b")
    client = TestClient(app)

    assert client.get("/api/jobs").status_code == 401
    listed = client.get("/api/jobs", headers={"Authorization": "Bearer valid"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [first.id]
    assert client.get(
        f"/api/jobs/{second.id}", headers={"Authorization": "Bearer valid"}
    ).status_code == 404
    assert client.get(
        f"/api/jobs/{first.id}", headers={"Authorization": "Bearer invalid"}
    ).status_code == 401


def test_supabase_disabled_fallback_stays_unauthenticated(
    isolated_store: None,
) -> None:
    job = store.create("local objective", None, True)
    response = TestClient(app).get(f"/api/jobs/{job.id}")
    assert response.status_code == 200
    assert response.json()["id"] == job.id


class FakeResponse:
    def __init__(self, payload: object = None, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class FailedResponse:
    status_code = 400
    text = '{"code":"PGRST204","message":"column investigations.playbook_id does not exist"}'

    def raise_for_status(self) -> None:
        request = httpx.Request("POST", "https://example.supabase.co/rest/v1/investigations")
        raise httpx.HTTPStatusError("Client error", request=request, response=self)


def test_supabase_persist_records_postgrest_error_detail(
    monkeypatch: pytest.MonkeyPatch, isolated_store: None
) -> None:
    job = store.create("persist objective", None, True, owner_id="user-a")
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: FailedResponse())
    repository = SupabaseRepository()

    repository.persist_job(job)

    failure = repository.last_failure
    assert failure is not None
    assert failure["operation"] == "investigations upsert"
    assert "PGRST204" in failure["message"]
    assert "playbook_id" in failure["message"]
    assert failure["timestamp"]


def test_mocked_supabase_rest_storage_hydration_and_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "runs_dir", tmp_path)
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
    monkeypatch.setattr(settings, "supabase_artifact_bucket", "research-artifacts")
    calls: list[tuple[str, str]] = []
    rows: dict[str, list[dict[str, Any]]] = {
        "investigations": [],
        "investigation_messages": [],
        "investigation_events": [],
        "investigation_artifacts": [],
        "research_results": [],
    }

    def request(
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json: object = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ) -> FakeResponse:
        del headers, timeout
        calls.append((method, url))
        if "/storage/v1/object/" in url and method == "GET":
            return FakeResponse(content=b'{"answer": 42}')
        if "/storage/v1/object/" in url and method == "POST":
            return FakeResponse([])
        table = url.rsplit("/", 1)[-1]
        if method == "POST" and table in rows:
            payload = json if isinstance(json, list) else [json]
            rows[table].extend(item for item in payload if isinstance(item, dict))
            return FakeResponse([])
        if method == "PATCH":
            return FakeResponse([])
        if method == "GET" and table in rows:
            return FakeResponse(rows[table])
        raise AssertionError((method, url, params, content))

    monkeypatch.setattr(httpx, "request", request)
    repository = SupabaseRepository()
    job = store.create("persist objective", None, True, owner_id="user-a")
    repository.persist_job(job)
    artifact = job.model_copy(
        update={
            "status": JobStatus.complete,
            "artifacts": [],
        }
    )
    artifact_info = executor.ArtifactInfo(
        id="art_result",
        filename="final_result.json",
        media_type="application/json",
        bytes=14,
        stage="synthesis",
        title="Final result",
        purpose="Result",
    )
    path = tmp_path / "final_result.json"
    path.write_text(json.dumps({"answer": 42}), encoding="utf-8")
    repository.persist_artifact(artifact, artifact_info, path)
    loaded = repository.load_jobs()
    assert loaded and loaded[0].owner_id == "user-a"
    destination = tmp_path / "downloaded.json"
    assert repository.download_artifact(job.id, "final_result.json", destination)
    assert json.loads(destination.read_text()) == {"answer": 42}
    assert any("/storage/v1/object/" in url for _, url in calls)


class TimelineClient:
    def __init__(
        self,
        sessions: list[dict[str, str]],
        messages: list[dict[str, Any]],
        messages_after: int = 0,
    ) -> None:
        self.sessions = sessions
        self.messages = messages
        self.messages_after = messages_after
        self.index = 0
        self.message_calls = 0

    def get_session(self, session_id: str) -> dict[str, str]:
        del session_id
        item = self.sessions[min(self.index, len(self.sessions) - 1)]
        self.index += 1
        return item

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        del session_id
        self.message_calls += 1
        return self.messages if self.message_calls > self.messages_after else []

    def list_attachments(self, session_id: str) -> list[dict[str, Any]]:
        del session_id
        return []

    def download(self, url: str) -> bytes:
        raise AssertionError(url)


def _timeout_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(settings, "runs_dir", tmp_path)
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
    store._jobs.clear()
    job = store.create("timeout objective", None, True)
    store.update(job.id, status=JobStatus.running)
    return job


def test_progress_resets_idle_deadline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    job = _timeout_job(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "poll_interval_seconds", 1)
    monkeypatch.setattr(settings, "poll_timeout_seconds", 8)
    monkeypatch.setattr(settings, "poll_idle_timeout_seconds", 2)
    clock = [0.0]
    monkeypatch.setattr(executor, "_harvest", lambda *args, **kwargs: args[4])
    client = TimelineClient(
        [
            {"status": "running", "status_detail": "plan"},
            {"status": "running", "status_detail": "analysis"},
            {"status": "running", "status_detail": "structure"},
            {"status": "exit", "status_detail": "finished"},
        ],
        [],
    )
    executor._await_session(
        job.id,
        client,
        "session",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        lambda: clock[0],
        wait_for_new_work=False,
    )


def test_timeout_recovery_completes_with_limitation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _timeout_job(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "poll_interval_seconds", 1)
    monkeypatch.setattr(settings, "poll_timeout_seconds", 1)
    monkeypatch.setattr(settings, "poll_idle_timeout_seconds", 1)
    clock = [0.0]
    messages = [{"id": "reply", "type": "devin_message", "message": "[reviewer] recovered answer"}]
    client = TimelineClient(
        [{"status": "running", "status_detail": "analysis"}],
        messages,
        messages_after=1,
    )
    monkeypatch.setattr(executor, "_harvest", lambda *args, **kwargs: args[4])
    assert executor._await_session(
        job.id,
        client,
        "session",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        lambda: clock[0],
        wait_for_new_work=False,
    ) == "done"
    assert any("wait limit" in item.lower() for item in store.get(job.id).limitations)


def test_timeout_without_recovery_raises_and_preserves_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _timeout_job(monkeypatch, tmp_path)
    store.update(job.id, devin_session_id="live-session")
    monkeypatch.setattr(settings, "poll_interval_seconds", 1)
    monkeypatch.setattr(settings, "poll_timeout_seconds", 1)
    monkeypatch.setattr(settings, "poll_idle_timeout_seconds", 1)
    clock = [0.0]
    client = TimelineClient(
        [{"status": "running", "status_detail": "analysis"}],
        [],
    )
    monkeypatch.setattr(executor, "_harvest", lambda *args, **kwargs: args[4])
    with pytest.raises(executor.DevinError, match="session is still live"):
        executor._await_session(
            job.id,
            client,
            "session",
            lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            lambda: clock[0],
            wait_for_new_work=False,
        )
    assert store.get(job.id).devin_session_id == "live-session"


def test_active_work_refreshes_idle_deadline_until_absolute_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _timeout_job(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "poll_interval_seconds", 1)
    monkeypatch.setattr(settings, "poll_timeout_seconds", 5)
    monkeypatch.setattr(settings, "poll_idle_timeout_seconds", 2)
    clock = [0.0]
    client = TimelineClient(
        [{"status": "running", "status_detail": "working"}],
        [],
    )
    monkeypatch.setattr(executor, "_harvest", lambda *args, **kwargs: args[4])
    with pytest.raises(executor.DevinError, match="wait limit"):
        executor._await_session(
            job.id,
            client,
            "session",
            lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            lambda: clock[0],
            wait_for_new_work=False,
        )
    assert clock[0] == 5
