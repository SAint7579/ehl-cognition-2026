from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.settings import settings
from backend.app.store import store as live_store


def _install_fakes(monkeypatch, tmp_path: Path) -> None:
    settings.runs_dir = tmp_path
    live_store._jobs.clear()

    def fake_pipeline(_target, _database, out, _threads):
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "homolog_search.json").write_text(
            json.dumps({"hits": [{"accession": "A0A0K8P6T7", "percent_identity": 100.0, "evalue": 0.0}]})
        )
        (out / "conservation.json").write_text(
            json.dumps(
                {
                    "columns": [
                        {"target_position": 160, "target_residue": "S", "conservation": 1.0}
                    ]
                }
            )
        )
        return SimpleNamespace(limitations=["All results are CALCULATED."])

    def fake_structure(_s, _c, _t, out, _r, _cons, _threads):
        out = Path(out)
        (out / "structure_summary.json").write_text(
            json.dumps({"structure_id": "6EQE", "chain": "A", "modelled_residue_count": 262})
        )
        (out / "residue_annotations.json").write_text(
            json.dumps({"annotations": [{"author_residue": 160, "target_position": 160, "one_letter": "S"}]})
        )
        return (
            SimpleNamespace(
                modelled_residue_count=262,
                deposition=SimpleNamespace(pdb_id="6EQE"),
                limitations=["Coordinates are KNOWN."],
            ),
            SimpleNamespace(),
        )

    monkeypatch.setattr("backend.app.executor.run_pipeline", fake_pipeline)
    monkeypatch.setattr("backend.app.executor.analyze_structure", fake_structure)


def test_job_lifecycle_and_follow_up(monkeypatch, tmp_path: Path) -> None:
    _install_fakes(monkeypatch, tmp_path)
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
    speakers = [message["speaker"] for message in job["messages"]]
    assert speakers[0] == "planner"
    assert "search" in speakers
    assert "structure" in speakers
    names = {item["filename"] for item in job["artifacts"]}
    assert "conservation.json" in names
    assert "structure_summary.json" in names
    conservation = client.get(f"/api/jobs/{job_id}/artifacts/conservation.json")
    assert conservation.status_code == 200
    asked = client.post(f"/api/jobs/{job_id}/messages", json={"body": "Why is S160 conserved?"})
    assert asked.status_code == 200
    assert asked.json()["messages"][-1]["speaker"] == "reviewer"


def test_health_lists_tool_status() -> None:
    payload = TestClient(app).get("/api/health").json()
    assert payload["status"] in {"ok", "missing_tools"}
    assert "missing_tools" in payload
