import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from bio_tools.cli import main
from bio_tools.provenance import file_digest, write_json_model
from bio_tools.structure import analyze_structure
from bio_tools.candidates import analyze_candidates
from bio_tools.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "fixtures/target_ispetase.fasta"
DATABASE = ROOT / "fixtures/homolog_db.fasta"
STRUCTURE = ROOT / "fixtures/structures/6EQE.pdb.gz"
REFERENCES = ROOT / "fixtures/structures"
PLAYBOOK = ROOT / "playbooks/protein_engineering_v1.md"
VOLATILE_PROVENANCE_KEYS = {
    "argv",
    "started_at",
    "ended_at",
    "duration_seconds",
    "input_files",
    "output_files",
    "stdout",
    "stderr",
}


def _args(out: Path, top: int = 10, extra: list[str] | None = None) -> list[str]:
    args = [
        "investigate",
        "--objective",
        "Identify substrate-cleft and surface engineering sites for IsPETase",
        "--target",
        str(TARGET),
        "--database",
        str(DATABASE),
        "--structure",
        str(STRUCTURE),
        "--chain",
        "A",
        "--references",
        str(REFERENCES),
        "--out",
        str(out),
        "--threads",
        "1",
        "--top",
        str(top),
    ]
    if extra:
        args.extend(extra)
    return args


def _load_result(out: Path) -> dict:
    return json.loads((out / "final_result.json").read_text(encoding="utf-8"))


def _without_volatile_provenance(document: dict) -> dict:
    stable = deepcopy(document)
    provenance = stable.get("provenance")
    records = provenance if isinstance(provenance, list) else [provenance]
    for record in records:
        if isinstance(record, dict):
            for key in VOLATILE_PROVENANCE_KEYS:
                record.pop(key, None)
    return stable


def test_investigate_success_schema_digests_and_standalone_equivalence(
    tmp_path: Path,
) -> None:
    out = tmp_path / "investigate"
    assert main(_args(out)) == 0
    result = _load_result(out)
    schema = json.loads((ROOT / "schemas/final_result.schema.json").read_text())
    Draft202012Validator(schema).validate(result)
    assert [stage["status"] for stage in result["stages"]] == [
        "COMPLETED",
        "COMPLETED",
        "COMPLETED",
    ]
    for stage in result["stages"]:
        for digest in stage["artifact_digests"]:
            path = Path(digest["path"])
            assert path.exists()
            assert path.is_relative_to(out)
            actual = file_digest(path)
            assert digest["sha256"] == actual.sha256
            assert digest["bytes"] == actual.bytes
        for path in stage["artifact_paths"]:
            assert (out / path).exists()
    for paths in result["artifact_index"].values():
        assert all((out / path).exists() for path in paths)
    assert result["playbook"]["version"] == "1.0.0"
    assert result["playbook"]["digest"]["sha256"] == file_digest(PLAYBOOK).sha256
    assert result["playbook"]["digest"]["bytes"] == file_digest(PLAYBOOK).bytes

    standalone = tmp_path / "standalone"
    sequence = standalone / "sequence"
    run_pipeline(TARGET, DATABASE, sequence, threads=1)
    structure_out = standalone / "structure"
    summary, annotations = analyze_structure(
        STRUCTURE,
        "A",
        TARGET,
        structure_out,
        REFERENCES,
        sequence / "conservation.json",
        1,
    )
    write_json_model(structure_out / "structure_summary.json", summary)
    write_json_model(structure_out / "residue_annotations.json", annotations)
    candidates_out = standalone / "candidates"
    candidate = analyze_candidates(
        structure_out / "residue_annotations.json",
        STRUCTURE,
        "A",
        candidates_out,
        sequence / "alignment.fasta",
        160,
        "OG",
        (160, 206, 237),
    )
    write_json_model(candidates_out / "candidate_sites.json", candidate)
    orchestrated_candidate = json.loads(
        (out / "candidates/candidate_sites.json").read_text()
    )
    standalone_candidate = json.loads(
        (candidates_out / "candidate_sites.json").read_text()
    )
    assert _without_volatile_provenance(orchestrated_candidate) == (
        _without_volatile_provenance(standalone_candidate)
    )
    orchestrated_structure = json.loads(
        (out / "structure/structure_summary.json").read_text()
    )
    standalone_structure = json.loads(
        (structure_out / "structure_summary.json").read_text()
    )
    assert _without_volatile_provenance(orchestrated_structure) == (
        _without_volatile_provenance(standalone_structure)
    )


def test_investigate_determinism_constraints_and_top_limit(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    extra = [
        "--constraint",
        "exclude_residues=160,206,237,183",
        "--constraint",
        "max_mutations=3",
    ]
    assert main(_args(first, top=3, extra=extra)) == 0
    assert main(_args(second, top=3, extra=extra)) == 0
    first_result = _load_result(first)
    second_result = _load_result(second)
    for field in (
        "objective",
        "constraints",
        "stages",
        "shortlists",
        "evidence_labels",
        "limitations",
    ):
        if field == "stages":
            assert [
                (stage["stage"], stage["status"]) for stage in first_result[field]
            ] == [
                (stage["stage"], stage["status"]) for stage in second_result[field]
            ]
        else:
            assert first_result[field] == second_result[field]
    assert {item["enforcement"] for item in first_result["constraints"]} == {
        "ENFORCED_BY_PIPELINE",
        "RECORDED_ONLY",
    }
    assert len(first_result["shortlists"]["activity"]["sites"]) == 3
    assert len(first_result["shortlists"]["stability"]["sites"]) == 3
    assert first_result["shortlists"]["activity"]["n_total"] == 25
    assert first_result["shortlists"]["stability"]["n_total"] == 69
    assert 183 not in {
        site["author_residue"]
        for site in first_result["shortlists"]["activity"]["sites"]
    }


def test_investigate_failure_and_constraint_errors(tmp_path: Path, capsys) -> None:
    out = tmp_path / "failed"
    assert main(_args(out, extra=["--chain", "Z"])) == 1
    result = _load_result(out)
    schema = json.loads((ROOT / "schemas/final_result.schema.json").read_text())
    Draft202012Validator(schema).validate(result)
    assert [stage["status"] for stage in result["stages"]] == [
        "COMPLETED",
        "FAILED",
        "SKIPPED",
    ]
    assert result["stages"][1]["error"]
    assert result["stages"][2]["artifact_paths"] == []
    assert "chain 'Z' not found" in capsys.readouterr().err

    assert main(_args(tmp_path / "malformed", extra=["--constraint", "foo"])) == 1
    assert "malformed --constraint" in capsys.readouterr().err


def test_investigate_evidence_honesty(tmp_path: Path) -> None:
    out = tmp_path / "honesty"
    assert main(_args(out)) == 0
    result = _load_result(out)

    def labels(value: object) -> list[object]:
        if isinstance(value, dict):
            return [
                item
                for key, child in value.items()
                for item in ([child] if key == "evidence_type" else labels(child))
            ]
        if isinstance(value, list):
            return [item for child in value for item in labels(child)]
        return []

    assert "EXPERIMENTAL" not in labels(result)
    assert "PREDICTED" not in labels(result)
    assert any("experimental validation" in text for text in result["limitations"])
