from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.settings import settings
from backend.app.store import store as live_store
from backend.app.supabase import supabase


class FakeDevin:
    def __init__(self) -> None:
        self.session_id = "devin-test"
        self.url = "https://app.devin.ai/sessions/devin-test"
        self.status = "exit"
        self.status_detail = "finished"
        self.sent: list[str] = []
        self.prompts: list[str] = []
        self.messages: list[dict[str, Any]] = []
        self.playbooks: list[dict[str, Any]] = []
        self.fetched_playbooks: dict[str, dict[str, Any]] = {}
        self.fetch_failures: set[str] = set()
        self.structured_output: dict[str, Any] | None = None
        self.selected_playbook_id: str | None = None
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

    def create_session(
        self,
        prompt: str,
        title: str,
        playbook_id: str | None = None,
    ) -> dict[str, Any]:
        self.selected_playbook_id = playbook_id
        self.prompts.append(prompt)
        self.messages = [
            {"id": "m1", "type": "devin_message", "message": "[planner] Starting CPU investigation in the sandbox."},
            {"id": "m2", "type": "devin_message", "message": "[search] MMseqs2 returned 1 homolog. Evidence is CALCULATED."},
            {"id": "m3", "type": "devin_message", "message": "[structure] Retrieved 6EQE. Coordinates are KNOWN."},
        ]
        return {"session_id": self.session_id, "url": self.url}

    def get_session(self, session_id: str) -> dict[str, Any]:
        response = {
            "session_id": session_id,
            "status": self.status,
            "status_detail": self.status_detail,
            "url": self.url,
        }
        if self.structured_output is not None:
            response["structured_output"] = self.structured_output
        return response

    def list_playbooks(self) -> list[dict[str, Any]]:
        return list(self.playbooks)

    def get_playbook(self, playbook_id: str) -> dict[str, Any]:
        if playbook_id in self.fetch_failures:
            raise RuntimeError("playbook fetch failed")
        return dict(self.fetched_playbooks.get(playbook_id, {}))

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
    monkeypatch.delenv("DEVIN_PLAYBOOK_ID", raising=False)
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
    assert job["playbook_id"] is None
    assert fake.selected_playbook_id is None
    assert job["devin_session_id"] == "devin-test"
    assert job["session_url"] == fake.url
    speakers = [message["speaker"] for message in job["messages"]]
    assert "planner" in speakers
    assert "search" in speakers
    assert "structure" in speakers
    assert "system" not in speakers
    assert "sandbox" in fake.prompts[0].lower()
    assert "bioctl investigate" in fake.prompts[0]
    assert "protein_engineering_v1.md" in fake.prompts[0]
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


def test_protocol_discovery_selection_snapshot_and_structured_synthesis(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from backend.app import main

    fake = _install(monkeypatch, tmp_path)
    fake.playbooks = [
        {
            "playbook_id": "pb-lab",
            "title": "Lab investigation",
            "body": "# Lab protocol\nUse only reviewable evidence.",
            "structured_output_schema": {"type": "object"},
        }
    ]
    fake.structured_output = {
        "objective": "Investigate enzyme stability.",
        "summary": "The evidence supports a stable variant.",
        "findings": [],
    }
    main._protocol_cache = None
    client = TestClient(app)
    protocols = client.get("/api/protocols")
    assert protocols.status_code == 200
    assert protocols.json() == [
        {
            "id": "pb-lab",
            "title": "Lab investigation",
            "has_structured_output_schema": True,
            "is_default": False,
        }
    ]
    created = client.post(
        "/api/jobs",
        json={"objective": "Investigate enzyme stability.", "playbook_id": "pb-lab"},
    )
    assert created.status_code == 200
    job = created.json()
    assert job["playbook_id"] == "pb-lab"
    assert job["playbook_title"] == "Lab investigation"
    assert fake.selected_playbook_id == "pb-lab"
    assert (tmp_path / job["id"] / "protocol.md").read_text() == fake.playbooks[0]["body"]
    assert any(item["filename"] == "protocol.md" for item in job["artifacts"])
    synthesis = json.loads((tmp_path / job["id"] / "synthesis.json").read_text())
    assert synthesis["summary"] == "The evidence supports a stable variant."
    assert "protein_engineering_v1.md" not in fake.prompts[-1]


def test_protocol_discovery_degrades_to_empty_list(monkeypatch) -> None:
    from backend.app import main

    main._protocol_cache = None
    monkeypatch.setattr(
        "backend.app.executor.get_client",
        lambda: (_ for _ in ()).throw(RuntimeError("Devin is not configured")),
    )
    response = TestClient(app).get("/api/protocols")
    assert response.status_code == 200
    assert response.json() == []


def test_empty_protocol_body_skips_snapshot_and_records_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from backend.app import main

    fake = _install(monkeypatch, tmp_path)
    fake.playbooks = [
        {
            "playbook_id": "pb-fetched",
            "title": "Fetched protocol",
            "body": "  \n",
        },
        {
            "playbook_id": "pb-missing",
            "title": "Missing protocol",
            "body": "  \n",
        },
    ]
    fake.fetched_playbooks["pb-fetched"] = {"body": "Fetched protocol body"}
    fake.fetch_failures.add("pb-missing")
    main._protocol_cache = None
    client = TestClient(app)
    fetched = client.post(
        "/api/jobs",
        json={"objective": "Investigate enzyme stability.", "playbook_id": "pb-fetched"},
    )
    assert fetched.status_code == 200
    fetched_job = fetched.json()
    assert (tmp_path / fetched_job["id"] / "protocol.md").read_text() == "Fetched protocol body"

    missing = client.post(
        "/api/jobs",
        json={"objective": "Investigate enzyme stability.", "playbook_id": "pb-missing"},
    )
    assert missing.status_code == 200
    missing_job = missing.json()
    assert not (tmp_path / missing_job["id"] / "protocol.md").exists()
    workspace = client.get(f"/api/jobs/{missing_job['id']}/research")
    assert "protocol.md" in workspace.json()["validation_errors"]


def test_configured_default_protocol_is_selected_and_recorded(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from backend.app import main

    fake = _install(monkeypatch, tmp_path)
    fake.playbooks = [
        {
            "playbook_id": "pb-default",
            "title": "End-to-end laboratory investigation",
            "body": "# Default laboratory protocol",
            "structured_output_schema": {"type": "object"},
        },
        {
            "playbook_id": "pb-specialized",
            "title": "Specialized protocol",
            "body": "# Specialized protocol",
        },
    ]
    monkeypatch.setenv("DEVIN_PLAYBOOK_ID", "pb-default")
    main._protocol_cache = None
    client = TestClient(app)
    protocols = client.get("/api/protocols")
    assert protocols.status_code == 200
    assert protocols.json()[0]["is_default"] is True
    assert protocols.json()[1]["is_default"] is False

    created = client.post(
        "/api/jobs",
        json={"objective": "Investigate enzyme stability."},
    )
    assert created.status_code == 200
    job = created.json()
    assert job["playbook_id"] == "pb-default"
    assert job["playbook_title"] == "End-to-end laboratory investigation"
    assert fake.selected_playbook_id == "pb-default"
    assert (tmp_path / job["id"] / "protocol.md").read_text() == fake.playbooks[0]["body"]


def test_unknown_protocol_is_rejected_and_invalid_output_is_reported(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from backend.app import main

    fake = _install(monkeypatch, tmp_path)
    fake.playbooks = [
        {
            "playbook_id": "pb-lab",
            "title": "Lab investigation",
            "body": "Protocol",
            "structured_output_schema": {"type": "object"},
        }
    ]
    main._protocol_cache = None
    client = TestClient(app)
    unknown = client.post(
        "/api/jobs",
        json={"objective": "Investigate enzyme stability.", "playbook_id": "unknown"},
    )
    assert unknown.status_code == 400

    job = live_store.create("Investigate enzyme stability.", None, True, playbook_id="pb-lab")
    synthesis = {
        "objective": job.objective,
        "summary": "Existing valid synthesis.",
        "findings": [],
    }
    (tmp_path / job.id / "synthesis.json").write_text(json.dumps(synthesis))
    fake.structured_output = {"summary": ""}
    from backend.app.executor import run_job

    run_job(job.id, client=fake, sleep=lambda _: None)
    assert json.loads((tmp_path / job.id / "synthesis.json").read_text()) == synthesis
    workspace = client.get(f"/api/jobs/{job.id}/research")
    assert workspace.status_code == 200
    assert "synthesis.json" in workspace.json()["validation_errors"]


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
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
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
    assert "supabase_healthy" not in ready


def test_health_reports_supabase_failure_detail(monkeypatch) -> None:
    class FailedResponse:
        status_code = 400
        text = '{"code":"PGRST204","message":"column investigations.playbook_id does not exist"}'

        def raise_for_status(self) -> None:
            request = httpx.Request(
                "GET",
                "https://example.supabase.co/rest/v1/investigations",
            )
            raise httpx.HTTPStatusError("Client error", request=request, response=self)

    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
    monkeypatch.setattr(supabase, "_health_cache", None)
    monkeypatch.setattr(supabase, "_last_failure", None)
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: FailedResponse())

    payload = TestClient(app).get("/api/health").json()

    assert payload["supabase_configured"] is True
    assert payload["supabase_healthy"] is False
    failure = payload["supabase_last_failure"]
    assert failure["operation"] == "investigations health check"
    assert "PGRST204" in failure["message"]
    assert "playbook_id" in failure["message"]


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


def test_lists_png_and_csv_artifacts(tmp_path: Path) -> None:
    settings.runs_dir = tmp_path
    live_store._jobs.clear()
    job = live_store.create("Show LCC as a figure.", None, True)
    folder = tmp_path / job.id
    (folder / "lcc_triad.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    (folder / "triad_residues.csv").write_text("residue,role\nS165,nucleophile\n", encoding="utf-8")
    from backend.app.artifacts import list_artifacts

    names = {item.filename for item in list_artifacts(job.id)}
    assert "lcc_triad.png" in names
    assert "triad_residues.csv" in names
    client = TestClient(app)
    image = client.get(f"/api/jobs/{job.id}/artifacts/lcc_triad.png")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")


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
