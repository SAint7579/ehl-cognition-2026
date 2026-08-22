from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.artifacts import list_artifacts
from backend.app.capabilities import capability_prompt, resolve_capabilities
from backend.app.main import app
from backend.app.models import ResearchCapability
from backend.app.settings import settings
from backend.app.store import store


def _reset(tmp_path: Path) -> None:
    settings.runs_dir = tmp_path
    store._jobs.clear()


def test_capability_catalog_and_routing(tmp_path: Path) -> None:
    _reset(tmp_path)
    catalog = TestClient(app).get("/api/capabilities")
    assert catalog.status_code == 200
    ids = {item["id"] for item in catalog.json()}
    assert ids == {item.value for item in ResearchCapability}

    routed = resolve_capabilities(
        "Dock a ligand and rank protein variants using structure and sequence evidence.",
        [],
        True,
    )
    assert ResearchCapability.sequence_analysis in routed
    assert ResearchCapability.structure_analysis in routed
    assert ResearchCapability.molecular_simulation in routed
    assert ResearchCapability.candidate_ranking in routed
    assert routed[-1] == ResearchCapability.research_synthesis

    explicit = resolve_capabilities(
        "Analyze this question.",
        [ResearchCapability.literature_search, ResearchCapability.literature_search],
        False,
    )
    assert explicit == [
        ResearchCapability.literature_search,
        ResearchCapability.research_synthesis,
    ]


def test_job_persists_capabilities_and_prompt_describes_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from tests.test_api import _install

    fake = _install(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/jobs",
        json={
            "objective": "Simulate ligand docking and compare the quantitative results.",
            "capabilities": ["molecular-simulation", "data-analysis"],
        },
    )
    assert created.status_code == 200
    job = created.json()
    assert job["capabilities"] == [
        "molecular-simulation",
        "data-analysis",
        "research-synthesis",
    ]
    prompt = fake.prompts[0]
    assert "Molecular simulation (`molecular-simulation`)" in prompt
    assert "simulation_results.json" in prompt
    assert "Never report a" in prompt
    assert "simulation as completed unless an engine command ran successfully" in prompt
    assert "research_plan.json" in prompt
    assert "synthesis.json" in prompt

    store._jobs.clear()
    store.load()
    restored = store.get(job["id"])
    assert restored is not None
    assert restored.capabilities == [
        ResearchCapability.molecular_simulation,
        ResearchCapability.data_analysis,
        ResearchCapability.research_synthesis,
    ]


def test_research_workspace_parses_outputs_and_reports_invalid_documents(
    tmp_path: Path,
) -> None:
    _reset(tmp_path)
    job = store.create(
        "Simulate binding and synthesize the result.",
        None,
        True,
        [ResearchCapability.molecular_simulation],
    )
    directory = tmp_path / job.id
    (directory / "research_plan.json").write_text(
        json.dumps(
            {
                "objective": job.objective,
                "strategy": "Run a quantitative docking workflow.",
                "tasks": [
                    {
                        "id": "simulation",
                        "title": "Run docking",
                        "purpose": "Estimate relative binding scores.",
                        "capability": "molecular-simulation",
                        "status": "COMPLETED",
                        "methods": ["AutoDock Vina"],
                        "output_files": ["simulation_results.json"],
                    }
                ],
                "assumptions": [],
                "required_inputs": [],
            }
        ),
        encoding="utf-8",
    )
    (directory / "synthesis.json").write_text(
        json.dumps(
            {
                "objective": job.objective,
                "summary": "One calculated pose ranked above the alternatives.",
                "findings": [
                    {
                        "title": "Top pose",
                        "statement": "Pose A had the best calculated score.",
                        "confidence": "MEDIUM",
                        "evidence_files": ["simulation_results.json"],
                        "implications": ["Prioritize Pose A for experimental testing."],
                    }
                ],
                "limitations": ["Docking is not experimental validation."],
            }
        ),
        encoding="utf-8",
    )
    (directory / "simulation_results.json").write_text(
        json.dumps(
            {
                "objective": job.objective,
                "summary": "The docking command completed and produced one parsed score.",
                "recommended_next_steps": ["Compare the pose experimentally."],
                "runs": [
                    {
                        "id": "dock-1",
                        "question": "Which pose has the best calculated score?",
                        "method": "Rigid-receptor docking",
                        "engine": "AutoDock Vina",
                        "status": "COMPLETED",
                        "input_files": ["receptor.pdbqt", "ligand.pdbqt"],
                        "parameters": {"exhaustiveness": 8},
                        "metrics": [
                            {
                                "name": "binding_score",
                                "value": -7.2,
                                "unit": "kcal/mol",
                                "interpretation": "More favorable than the compared poses.",
                            }
                        ],
                        "output_files": ["pose.pdbqt"],
                        "interpretation": "Pose A ranked first in this calculation.",
                        "limitations": ["The score is not an experimental affinity."],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    client = TestClient(app)
    response = client.get(f"/api/jobs/{job.id}/research")
    assert response.status_code == 200
    workspace = response.json()
    assert workspace["plan"]["tasks"][0]["capability"] == "molecular-simulation"
    assert workspace["synthesis"]["findings"][0]["confidence"] == "MEDIUM"
    assert workspace["simulations"]["runs"][0]["metrics"][0]["value"] == -7.2
    assert workspace["validation_errors"] == {}

    (directory / "simulation_results.json").write_text('{"runs": "invalid"}', encoding="utf-8")
    malformed = client.get(f"/api/jobs/{job.id}/research").json()
    assert malformed["simulations"] is None
    assert "simulation_results.json" in malformed["validation_errors"]


def test_artifacts_include_scientist_facing_metadata(tmp_path: Path) -> None:
    _reset(tmp_path)
    job = store.create("Analyze a dataset and synthesize it.", None, False)
    directory = tmp_path / job.id
    (directory / "synthesis.json").write_text("{}", encoding="utf-8")
    (directory / "simulation_metrics.csv").write_text("name,value\nscore,-7.2\n", encoding="utf-8")
    (directory / "dose_response.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    artifacts = {item.filename: item for item in list_artifacts(job.id)}
    assert artifacts["synthesis.json"].stage == "synthesis"
    assert artifacts["synthesis.json"].title == "Scientific synthesis"
    assert artifacts["simulation_metrics.csv"].stage == "simulation"
    assert artifacts["dose_response.png"].stage == "analysis"
    assert artifacts["dose_response.png"].purpose


def test_follow_up_prompt_keeps_capability_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from tests.test_api import _install

    fake = _install(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/jobs",
        json={
            "objective": "Search literature and synthesize the findings.",
            "capabilities": ["literature-search"],
        },
    )
    job_id = created.json()["id"]
    asked = client.post(
        f"/api/jobs/{job_id}/messages",
        json={"body": "Update the synthesis with the newest source."},
    )
    assert asked.status_code == 200
    assert fake.sent
    assert "Literature and database search (`literature-search`)" in fake.sent[0]
    assert "update\nresearch_plan.json plus synthesis.json" in fake.sent[0]


def test_capability_prompt_lists_expected_tools_and_outputs() -> None:
    rendered = capability_prompt(
        [
            ResearchCapability.sequence_analysis,
            ResearchCapability.research_synthesis,
        ]
    )
    assert "MMseqs2" in rendered
    assert "conservation.json" in rendered
    assert "synthesis.json" in rendered


def test_capability_progress_messages_map_to_research_stages() -> None:
    from backend.app.executor import _stage_for_message
    from backend.app.models import Speaker

    assert (
        _stage_for_message(
            Speaker.reviewer,
            "**Simulation:** using the selected structure for docking.",
        )
        == "simulation"
    )
    assert (
        _stage_for_message(
            Speaker.reviewer,
            "**Synthesis:** integrating the structure and sequence evidence.",
        )
        == "synthesis"
    )


def test_loading_legacy_job_infers_capabilities(tmp_path: Path) -> None:
    _reset(tmp_path)
    job = store.create("Compare enzyme variants.", None, True)
    path = tmp_path / job.id / "job.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("capabilities")
    path.write_text(json.dumps(payload), encoding="utf-8")

    store._jobs.clear()
    store.load()
    restored = store.get(job.id)
    assert restored is not None
    assert ResearchCapability.sequence_analysis in restored.capabilities
    assert ResearchCapability.research_synthesis in restored.capabilities
