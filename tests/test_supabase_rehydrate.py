from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models import Job, JobStatus
from backend.app.settings import settings
from backend.app.store import JobStore
from backend.app.supabase import supabase


def _job(job_id: str, updated_at: datetime, status: JobStatus = JobStatus.complete) -> Job:
    return Job(
        id=job_id,
        title="Hydrated investigation",
        objective="Investigate a persisted objective.",
        status=status,
        created_at=updated_at - timedelta(minutes=1),
        updated_at=updated_at,
    )


@pytest.fixture
def isolated_store(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "runs_dir", tmp_path)
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
    monkeypatch.setattr(settings, "supabase_refresh_seconds", 30.0)


def test_list_refreshes_supabase_only_investigation(
    monkeypatch: pytest.MonkeyPatch, isolated_store: None
) -> None:
    store = JobStore()
    remote = _job("remote-list", datetime.now(timezone.utc))
    calls = 0

    def load_jobs() -> list[Job]:
        nonlocal calls
        calls += 1
        return [remote]

    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
    monkeypatch.setattr(supabase, "load_jobs", load_jobs)

    assert [job.id for job in store.list()] == ["remote-list"]
    assert calls == 1


def test_get_refreshes_missing_supabase_investigation(
    monkeypatch: pytest.MonkeyPatch, isolated_store: None
) -> None:
    store = JobStore()
    remote = _job("remote-get", datetime.now(timezone.utc))
    calls = 0

    def load_jobs() -> list[Job]:
        nonlocal calls
        calls += 1
        return [remote]

    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
    monkeypatch.setattr(supabase, "load_jobs", load_jobs)

    hydrated = store.get("remote-get")

    assert hydrated is not None
    assert hydrated.id == "remote-get"
    assert calls == 1


def test_refresh_ttl_prevents_second_supabase_fetch(
    monkeypatch: pytest.MonkeyPatch, isolated_store: None
) -> None:
    store = JobStore()
    remote = _job("remote-ttl", datetime.now(timezone.utc))
    calls = 0

    def load_jobs() -> list[Job]:
        nonlocal calls
        calls += 1
        return [remote]

    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
    monkeypatch.setattr(supabase, "load_jobs", load_jobs)

    store.list()
    store.list()

    assert calls == 1


def test_refresh_does_not_overwrite_newer_running_local_job(
    monkeypatch: pytest.MonkeyPatch, isolated_store: None
) -> None:
    store = JobStore()
    local = store.create("Local objective", None, True)
    running = store.update(local.id, status=JobStatus.running)
    remote = running.model_copy(
        update={
            "status": JobStatus.complete,
            "updated_at": running.updated_at - timedelta(seconds=1),
        }
    )

    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
    monkeypatch.setattr(supabase, "load_jobs", lambda: [remote])

    refreshed = next(job for job in store.list() if job.id == local.id)

    assert refreshed is not None
    assert refreshed.status == JobStatus.running
    assert refreshed.updated_at == running.updated_at


def test_refresh_is_noop_when_supabase_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch, isolated_store: None
) -> None:
    store = JobStore()

    def unexpected_load() -> list[Job]:
        raise AssertionError("Supabase should not be queried when unconfigured")

    monkeypatch.setattr(supabase, "load_jobs", unexpected_load)

    assert store.list() == []
    assert store.get("missing") is None
