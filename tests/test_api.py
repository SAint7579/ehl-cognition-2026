from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.settings import settings
from backend.app.store import store as live_store


class FakeDevin:
    def __init__(self) -> None:
        self.session_id = "devin-test"
        self.url = "https://app.devin.ai/sessions/devin-test"
        self.status = "exit"
        self.status_detail = "finished"
        self.sent: list[str] = []
        self.prompts: list[str] = []
        self.messages: list[dict[str, Any]] = []
        self.attachments: dict[str, bytes] = {
            "homolog_search.json": json.dumps(
                {"hits": [{"accession": "A0A0K8P6T7", "percent_identity": 100.0, "evalue": 0.0}]}
            ).encode(),
            "conservation.json": json.dumps(
                {"columns": [{"target_position": 160, "target_residue": "S", "conservation": 1.0}]}
            ).encode(),
            "structure_summary.json": json.dumps(
                {"structure_id": "6EQE", "chain": "A", "modelled_residue_count": 262}
            ).encode(),
            "final_result.json": json.dumps(
                {"limitations": ["All results are CALCULATED."], "shortlists": {"activity": {"sites": []}, "stability": {"sites": []}}}
            ).encode(),
        }

    def create_session(self, prompt: str, title: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        self.messages = [
            {"id": "m1", "type": "devin_message", "message": "[planner] Starting CPU investigation in the sandbox."},
            {"id": "m2", "type": "devin_message", "message": "[search] MMseqs2 returned 1 homolog. Evidence is CALCULATED."},
            {"id": "m3", "type": "devin_message", "message": "[structure] Retrieved 6EQE. Coordinates are KNOWN."},
        ]
        return {"session_id": self.session_id, "url": self.url}

    def get_session(self, session_id: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "status": self.status,
            "status_detail": self.status_detail,
            "url": self.url,
        }

    def send_message(self, session_id: str, message: str) -> None:
        self.sent.append(message)
        self.messages.append(
            {
                "id": f"r{len(self.messages)}",
                "type": "devin_message",
                "message": "[reviewer] Decisions come from bioctl artifacts, not chat memory.",
            }
        )

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        return list(self.messages)

    def list_attachments(self, session_id: str) -> list[dict[str, Any]]:
        return [{"name": name, "url": f"mem://{name}"} for name in self.attachments]

    def download(self, url: str) -> bytes:
        return self.attachments[url.rsplit("/", 1)[-1]]


def _install(monkeypatch, tmp_path: Path) -> FakeDevin:
    settings.runs_dir = tmp_path
    settings.poll_interval_seconds = 0
    settings.poll_timeout_seconds = 5
    live_store._jobs.clear()
    fake = FakeDevin()
    monkeypatch.setattr("backend.app.executor.get_client", lambda: fake)
    monkeypatch.setattr("backend.app.main.missing_devin_settings", lambda: [])
    return fake


def test_job_lifecycle_and_follow_up(monkeypatch, tmp_path: Path) -> None:
    fake = _install(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/jobs",
        json={"objective": "Make IsPETase more heat resistant. Keep catalysis."},
    )
    assert created.status_code == 200
    job_id = created.json()["id"]
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "complete"
    assert job["playbook"] == "protein-engineering-v1"
    assert job["devin_session_id"] == "devin-test"
    assert job["session_url"] == fake.url
    speakers = [message["speaker"] for message in job["messages"]]
    assert "planner" in speakers
    assert "search" in speakers
    assert "structure" in speakers
    assert "system" not in speakers
    assert "sandbox" in fake.prompts[0].lower()
    assert "bioctl investigate" in fake.prompts[0]
    assert "do not assume" in fake.prompts[0].lower()
    assert "--target fixtures/target_ispetase.fasta" not in fake.prompts[0].split("Scientist's request:")[0]
    names = {item["filename"] for item in job["artifacts"]}
    assert "conservation.json" in names
    assert "structure_summary.json" in names
    assert "final_result.json" in names
    assert any(event["type"] == "artifact.ready" for event in job["events"])
    conservation = client.get(f"/api/jobs/{job_id}/artifacts/conservation.json")
    assert conservation.status_code == 200
    first_devin = [message["body"] for message in job["messages"] if message["speaker"] != "user"]
    asked = client.post(f"/api/jobs/{job_id}/messages", json={"body": "Why is S160 conserved?"})
    assert asked.status_code == 200
    followed = client.get(f"/api/jobs/{job_id}").json()
    assert followed["messages"][-1]["speaker"] == "reviewer"
    assert fake.sent and "S160" in fake.sent[0]
    later = [message["body"] for message in followed["messages"] if message["speaker"] != "user"]
    for body in first_devin:
        assert later.count(body) == 1


def test_unconfigured_job_fails_without_local_fallback(monkeypatch, tmp_path: Path) -> None:
    settings.runs_dir = tmp_path
    live_store._jobs.clear()
    monkeypatch.setattr(
        "backend.app.executor.get_client",
        lambda: (_ for _ in ()).throw(
            RuntimeError(
                "This product runs science in a Devin Cloud sandbox, not on this Mac. "
                "Set DEVIN_API_KEY, DEVIN_ORG_ID and restart the API."
            )
        ),
    )
    client = TestClient(app)
    created = client.post("/api/jobs", json={"objective": "Make IsPETase more heat resistant."})
    assert created.status_code == 200
    job = client.get(f"/api/jobs/{created.json()['id']}").json()
    assert job["status"] == "failed"
    assert "sandbox" in (job["error"] or "").lower()
    assert "Mac" in (job["error"] or "")


def test_health_reports_devin_runtime(monkeypatch) -> None:
    monkeypatch.delenv("DEVIN_API_KEY", raising=False)
    monkeypatch.delenv("DEVIN_ORG_ID", raising=False)
    monkeypatch.delenv("DEVIN_SNAPSHOT_ID", raising=False)
    payload = TestClient(app).get("/api/health").json()
    assert payload["runtime"] == "devin-sandbox"
    assert payload["status"] == "not_configured"
    assert "DEVIN_API_KEY" in payload["missing"]
    assert payload["snapshot_configured"] is False

    monkeypatch.setenv("DEVIN_API_KEY", "cog_test")
    monkeypatch.setenv("DEVIN_ORG_ID", "org-test")
    monkeypatch.setenv("DEVIN_SNAPSHOT_ID", "snap-test")
    ready = TestClient(app).get("/api/health").json()
    assert ready["status"] == "ok"
    assert ready["configured"] is True
    assert ready["snapshot_configured"] is True
    assert ready["missing"] == []


def test_imports_existing_session_without_creating(monkeypatch, tmp_path: Path) -> None:
    fake = _install(monkeypatch, tmp_path)
    fake.messages = [
        {
            "id": "rev",
            "type": "devin_message",
            "message": "[reviewer] All stages COMPLETED. ATTACHMENT:{\"url\":\"https://app.devin.ai/attachments/f0dad858-0e54-45d7-8fce-68f2cc635464/conservation.json\"}",
        }
    ]
    client = TestClient(app)
    created = client.post(
        "/api/jobs",
        json={
            "objective": "Make IsPETase more heat resistant. Keep catalysis.",
            "devin_session_id": "https://app.devin.ai/sessions/47bd07f6571347ff9b06096e6514e0c0",
        },
    )
    assert created.status_code == 200
    job = client.get(f"/api/jobs/{created.json()['id']}").json()
    assert job["status"] == "complete"
    assert job["devin_session_id"] == "47bd07f6571347ff9b06096e6514e0c0"
    assert fake.prompts == []
    assert "conservation.json" in {item["filename"] for item in job["artifacts"]}
    assert "ATTACHMENT" not in job["messages"][-1]["body"]


def test_harvests_chat_attachment_urls(monkeypatch, tmp_path: Path) -> None:
    fake = _install(monkeypatch, tmp_path)
    fake.listed_attachments: list[dict[str, Any]] = []
    original_list = fake.list_attachments

    def empty_list(_session_id: str) -> list[dict[str, Any]]:
        return []

    fake.list_attachments = empty_list  # type: ignore[method-assign]
    fake.messages = [
        {
            "id": "m1",
            "type": "devin_message",
            "message": (
                "[reviewer] done "
                "https://app.devin.ai/attachments/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/conservation.json "
                "https://app.devin.ai/attachments/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/final_result.json"
            ),
        }
    ]
    client = TestClient(app)
    created = client.post(
        "/api/jobs",
        json={
            "objective": "Make IsPETase more heat resistant. Keep catalysis.",
            "devin_session_id": fake.session_id,
        },
    )
    job = client.get(f"/api/jobs/{created.json()['id']}").json()
    assert job["status"] == "complete"
    names = {item["filename"] for item in job["artifacts"]}
    assert "conservation.json" in names
    assert "final_result.json" in names
    fake.list_attachments = original_list  # type: ignore[method-assign]


def test_jobs_persist_across_reload(tmp_path: Path) -> None:
    settings.runs_dir = tmp_path
    live_store._jobs.clear()
    job = live_store.create("Make IsPETase more heat resistant. Keep catalysis.", None, True)
    live_store._jobs.clear()
    live_store.load()
    restored = live_store.get(job.id)
    assert restored is not None
    assert restored.objective.startswith("Make IsPETase")


def test_structure_pdb_is_prepared_for_the_viewer(monkeypatch, tmp_path: Path) -> None:
    fake = _install(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/jobs",
        json={"objective": "Make IsPETase more heat resistant. Keep catalysis."},
    )
    job_id = created.json()["id"]
    pdb = client.get(f"/api/jobs/{job_id}/artifacts/structure.pdb")
    assert pdb.status_code == 200
    assert pdb.text.startswith("HEADER") or "ATOM" in pdb.text


def test_hides_instruction_echoes_from_chat() -> None:
    from backend.app.chatfilter import is_internal, visible_messages
    from backend.app.models import Message, Speaker
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    messages = [
        Message(id="1", speaker=Speaker.planner, body="Stay in this same Devin Cloud sandbox session. Operator follow-up: Hello btw", created_at=now),
        Message(id="2", speaker=Speaker.user, body="Hello btw", created_at=now),
        Message(id="3", speaker=Speaker.reviewer, body="The triad is conserved. Nothing here is experimental.", created_at=now),
        Message(id="4", speaker=Speaker.system, body="Importing artifacts from https://app.devin.ai/sessions/abc", created_at=now),
    ]
    assert is_internal(messages[0].body)
    shown = visible_messages(messages)
    assert [item.body for item in shown] == ["Hello btw", "The triad is conserved. Nothing here is experimental."]


def test_attachment_ref_parses_app_urls() -> None:
    from backend.app.devin import attachment_ref, normalize_session_ref

    assert attachment_ref(
        "https://app.devin.ai/attachments/f0dad858-0e54-45d7-8fce-68f2cc635464/homolog_search.json"
    ) == ("f0dad858-0e54-45d7-8fce-68f2cc635464", "homolog_search.json")
    session_id, url = normalize_session_ref(
        "https://app.devin.ai/sessions/47bd07f6571347ff9b06096e6514e0c0"
    )
    assert session_id == "47bd07f6571347ff9b06096e6514e0c0"
    assert url.endswith(session_id)


def test_waiting_for_approval_shows_confirm_and_accepts_reply(monkeypatch, tmp_path: Path) -> None:
    fake = _install(monkeypatch, tmp_path)
    fake.status = "running"
    fake.status_detail = "waiting_for_approval"
    client = TestClient(app)
    created = client.post(
        "/api/jobs",
        json={"objective": "Tell me about strawberry flavor compounds."},
    )
    job = client.get(f"/api/jobs/{created.json()['id']}").json()
    assert job["status"] == "running"
    assert job["active_stage"] == "waiting_for_approval"
    assert any("confirm the next step" in message["body"].lower() for message in job["messages"])
    fake.status_detail = "waiting_for_user"
    replied = client.post(
        f"/api/jobs/{job['id']}/messages",
        json={"body": "Yes, proceed with the next step."},
    )
    assert replied.status_code == 200
    followed = client.get(f"/api/jobs/{job['id']}").json()
    assert followed["status"] == "complete"


def test_ingest_updates_growing_devin_output(monkeypatch, tmp_path: Path) -> None:
    fake = _install(monkeypatch, tmp_path)
    fake.status = "running"
    fake.status_detail = "waiting_for_user"
    fake.messages = [
        {"id": "grow1", "type": "devin_message", "message": "Fetching 4IDC."},
    ]
    client = TestClient(app)
    created = client.post(
        "/api/jobs",
        json={
            "objective": "Find the strawberry flavor enzyme structure.",
            "devin_session_id": fake.session_id,
        },
    )
    job_id = created.json()["id"]
    first = client.get(f"/api/jobs/{job_id}").json()
    assert any(message["body"] == "Fetching 4IDC." for message in first["messages"])
    fake.messages[0]["message"] = "Fetching 4IDC. Coordinates are from PDB 4IDC."
    from backend.app.executor import _ingest_messages

    _ingest_messages(job_id, fake, fake.session_id)
    later = client.get(f"/api/jobs/{job_id}").json()
    bodies = [message["body"] for message in later["messages"] if message["speaker"] != "user"]
    assert bodies.count("Fetching 4IDC.") == 0
    assert any("Coordinates are from PDB 4IDC." in body for body in bodies)
    assert sum(1 for body in bodies if "4IDC" in body) == 1


def test_running_waiting_for_user_closes_the_turn(monkeypatch, tmp_path: Path) -> None:
    fake = _install(monkeypatch, tmp_path)
    fake.status = "running"
    fake.status_detail = "waiting_for_user"
    client = TestClient(app)
    created = client.post(
        "/api/jobs",
        json={"objective": "Make IsPETase more heat resistant. Keep catalysis."},
    )
    job = client.get(f"/api/jobs/{created.json()['id']}").json()
    assert job["status"] == "complete"
    assert job["active_stage"] is None
    assert any("Homolog search" in event["message"] for event in job["events"])
