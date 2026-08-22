import json
from pathlib import Path

from jsonschema import Draft202012Validator

from bio_tools.models import (
    AlignmentArtifact,
    ConservationArtifact,
    HomologSearchArtifact,
    RunArtifact,
    SCHEMA_VERSION,
)
from bio_tools.pipeline import run_pipeline
from bio_tools.versions import tool_version

ROOT = Path(__file__).resolve().parents[1]


def test_committed_schemas_match_export(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from export_schemas import export_schemas

    fresh = tmp_path / "schemas"
    export_schemas(fresh)
    for name in ("homolog_search", "alignment", "conservation", "run"):
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
    accessions = {hit["accession"] for hit in homologs["hits"]}
    assert {"Q6A0I4", "G9BY57", "D1A9G5"} <= accessions
    alignment = json.loads((out / "alignment.json").read_text())
    assert alignment["target_row_id"]
    assert alignment["n_sequences"] >= 2
    run = json.loads((out / "run.json").read_text())
    versions = {record["provenance"][0]["tool_name"]: record["provenance"][0]["tool_version"] for record in run["stages"]}
    assert versions["mmseqs"] == tool_version("mmseqs")
    assert versions["mafft"] == tool_version("mafft")
    conservation = json.loads((out / "conservation.json").read_text())
    region = [
        item for item in conservation["columns"]
        if item["target_position"] is not None and 150 <= item["target_position"] <= 180
    ]
    assert region
    assert sum(item["conservation"] is not None and item["conservation"] > 0.5 for item in region) / len(region) > 0.5
