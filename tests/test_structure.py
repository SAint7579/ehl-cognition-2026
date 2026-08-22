import json
from pathlib import Path

from jsonschema import Draft202012Validator

from bio_tools.models import ResidueAnnotationsArtifact, StructureSummaryArtifact
from bio_tools.pipeline import run_pipeline
from bio_tools.structure import _extract_residues, _map_to_target
from bio_tools.structure import analyze_structure
from bio_tools.versions import tool_version

ROOT = Path(__file__).resolve().parents[1]


def test_structure_fixture_mapping_and_artifacts(tmp_path: Path) -> None:
    sequence_out = tmp_path / "sequence"
    run_pipeline(
        ROOT / "fixtures/target_ispetase.fasta",
        ROOT / "fixtures/homolog_db.fasta",
        sequence_out,
        threads=1,
    )
    out = tmp_path / "structure"
    summary, annotations = analyze_structure(
        ROOT / "fixtures/structures/6EQE.pdb.gz",
        "A",
        ROOT / "fixtures/target_ispetase.fasta",
        out,
        ROOT / "fixtures/structures",
        sequence_out / "conservation.json",
        threads=1,
    )
    summary_path = out / "structure_summary.json"
    annotation_path = out / "residue_annotations.json"
    summary_path.write_text(summary.model_dump_json(indent=2) + "\n")
    annotation_path.write_text(annotations.model_dump_json(indent=2) + "\n")
    for name, path in (
        ("structure_summary", summary_path),
        ("residue_annotations", annotation_path),
    ):
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        Draft202012Validator(schema).validate(json.loads(path.read_text()))
    assert summary.modelled_residue_count == 265
    assert summary.unmodelled_target_ranges == ["1-28"]
    assert summary.secondary_structure.counts_3state["H"] > 0
    assert summary.secondary_structure.counts_3state["E"] > 0
    assert summary.foldseek_hits[0].target == "5XJH"
    assert next(hit for hit in summary.foldseek_hits if hit.target == "1UBQ").significant is False
    triad = {item.author_residue: item for item in annotations.annotations}
    for residue, target_position, one_letter in ((160, 160, "S"), (206, 206, "D"), (237, 237, "H")):
        item = triad[residue]
        assert item.target_position == target_position
        assert item.one_letter == one_letter
        assert item.msa_column is not None
        column = json.loads((sequence_out / "conservation.json").read_text())["columns"][
            item.msa_column - 1
        ]
        assert column["target_position"] == target_position
    for item in annotations.annotations:
        if item.author_residue in (291, 292, 293):
            assert item.target_position is None
            assert item.msa_column is None
    assert any(w.code == "UNMODELLED_TARGET_RESIDUES" for w in summary.warnings)
    assert any(w.code == "ALTERNATE_LOCATION" for w in summary.warnings)
    assert any(w.code == "RESIDUE_OUTSIDE_TARGET" for w in summary.warnings)
    assert any(record.tool_version == tool_version("mkdssp") for record in summary.provenance)
    assert any(record.tool_version == tool_version("foldseek") for record in summary.provenance)
    assert all(item.rsa is None or item.rsa >= 0 for item in annotations.annotations)


def test_structure_mapping_does_not_assume_author_numbering() -> None:
    mapping, parameters = _map_to_target("ACDE", "XXACDE")
    assert mapping == [3, 4, 5, 6]
    assert parameters["substitution_matrix"] == "BLOSUM62"


def test_synthetic_author_offset_and_insertion_are_reported(tmp_path: Path) -> None:
    pdb = tmp_path / "tiny.pdb"
    pdb.write_text(
        "ATOM      1  CA  ALA A  10       1.000   1.000   1.000  1.00 20.00           C  \n"
        "ATOM      2  CA  CYS A  12A      2.000   1.000   1.000  1.00 20.00           C  \n"
        "ATOM      3  CA  ASP A  13       3.000   1.000   1.000  1.00 20.00           C  \n"
        "TER\nEND\n"
    )
    residues, sequence, warnings = _extract_residues(pdb, "A")
    mapping, _ = _map_to_target(sequence, "ACD")
    assert sequence == "ACD"
    assert mapping == [1, 2, 3]
    assert residues[0]["author_residue"] == 10
    assert any(w.code == "AUTHOR_NUMBERING_GAP" for w in warnings)
    assert any(w.code == "INSERTION_CODE" for w in warnings)
