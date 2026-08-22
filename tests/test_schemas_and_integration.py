import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from bio_tools.models import (
    AlignmentArtifact,
    ConservationArtifact,
    HomologSearchArtifact,
    RunArtifact,
    SCHEMA_VERSION,
)
from bio_tools.pipeline import run_pipeline
from bio_tools.provenance import file_digest
from bio_tools.versions import tool_version

ROOT = Path(__file__).resolve().parents[1]


def test_committed_schemas_match_export(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from export_schemas import export_schemas

    fresh = tmp_path / "schemas"
    export_schemas(fresh)
    for name in (
        "homolog_search",
        "alignment",
        "conservation",
        "run",
        "structure_summary",
        "residue_annotations",
    ):
        schema_path = ROOT / "schemas" / f"{name}.schema.json"
        fresh_path = fresh / f"{name}.schema.json"
        assert schema_path.read_bytes() == fresh_path.read_bytes()
        Draft202012Validator.check_schema(json.loads(fresh_path.read_text()))


def test_real_pipeline_on_committed_fixtures(tmp_path: Path) -> None:
    out = tmp_path / "run"
    run_pipeline(
        ROOT / "fixtures/target_ispetase.fasta",
        ROOT / "fixtures/homolog_db.fasta",
        out,
        threads=2,
    )
    for name in ("homolog_search", "alignment", "conservation", "run"):
        artifact_path = out / f"{name}.json"
        assert artifact_path.exists()
        artifact = json.loads(artifact_path.read_text())
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        Draft202012Validator(schema).validate(artifact)
    homologs = json.loads((out / "homolog_search.json").read_text())
    assert (out / "homologs.m8").exists()
    assert not (out / "mmseqs_tmp").exists()
    hits = {hit["accession"]: hit for hit in homologs["hits"]}
    assert hits["A0A0K8P6T7"]["percent_identity"] == pytest.approx(100.0, abs=0.1)
    for accession in ("Q6A0I4", "G9BY57", "D1A9G5", "D1A2H1", "E9LVH8"):
        assert 40 <= hits[accession]["percent_identity"] <= 60
    # This documents specificity of -s 7.5 -e 1e-3, not that these proteins are unrelated.
    for accession in ("P41365", "P37967", "A0A0K8P8E7", "P00590"):
        assert accession not in hits
    alignment = json.loads((out / "alignment.json").read_text())
    assert alignment["target_row_id"]
    assert alignment["n_sequences"] >= 2
    run = json.loads((out / "run.json").read_text())
    assert run["limitations"]
    assert run["environment"]["mmseqs_version"]
    assert run["environment"]["mafft_version"]
    assert all(stage["provenance"] for stage in run["stages"])
    assert all(
        record["tool_version"]
        for stage in run["stages"]
        for record in stage["provenance"]
    )
    for stage in run["stages"]:
        assert stage["artifact_digests"]
        for digest in stage["artifact_digests"]:
            actual = file_digest(digest["path"])
            assert digest["sha256"] == actual.sha256
            assert digest["bytes"] == actual.bytes
    versions = {
        record["provenance"][0]["tool_name"]: record["provenance"][0]["tool_version"]
        for record in run["stages"]
    }
    assert versions["mmseqs"] == tool_version("mmseqs")
    assert versions["mafft"] == tool_version("mafft")
    conservation = json.loads((out / "conservation.json").read_text())
    catalytic = {
        item["target_position"]: item
        for item in conservation["columns"]
        if item["target_position"] in {160, 206, 237}
    }
    assert catalytic[160]["target_residue"] == "S"
    assert catalytic[206]["target_residue"] == "D"
    assert catalytic[237]["target_residue"] == "H"
    for position in (160, 206, 237):
        assert catalytic[position]["conservation"] >= 0.95
        assert catalytic[position]["gap_fraction"] == 0
