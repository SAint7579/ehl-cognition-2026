import json
from pathlib import Path

from Bio import AlignIO
from jsonschema import Draft202012Validator

from bio_tools.cli import main
from bio_tools.pipeline import run_pipeline
from bio_tools.structure import _extract_residues, _map_to_target
from bio_tools.versions import tool_version

ROOT = Path(__file__).resolve().parents[1]


def test_structure_cli_fixture_mapping_and_artifacts(tmp_path: Path) -> None:
    sequence_out = tmp_path / "sequence"
    run_pipeline(
        ROOT / "fixtures/target_ispetase.fasta",
        ROOT / "fixtures/homolog_db.fasta",
        sequence_out,
        threads=1,
    )
    out = tmp_path / "structure"
    assert main(
        [
            "structure",
            "--structure",
            str(ROOT / "fixtures/structures/6EQE.pdb.gz"),
            "--chain",
            "A",
            "--target",
            str(ROOT / "fixtures/target_ispetase.fasta"),
            "--conservation",
            str(sequence_out / "conservation.json"),
            "--references",
            str(ROOT / "fixtures/structures"),
            "--out",
            str(out),
            "--threads",
            "1",
        ]
    ) == 0
    summary_path = out / "structure_summary.json"
    annotation_path = out / "residue_annotations.json"
    summary = json.loads(summary_path.read_text())
    annotations = json.loads(annotation_path.read_text())
    for name, path in (
        ("structure_summary", summary_path),
        ("residue_annotations", annotation_path),
    ):
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        Draft202012Validator(schema).validate(json.loads(path.read_text()))
    assert summary["modelled_residue_count"] == 265
    assert summary["unmodelled_target_ranges"] == ["1-28"]
    assert summary["residue_counts"]["unmodelled_target"] == 28
    assert summary["secondary_structure"]["counts_3state"]["H"] > 0
    assert summary["secondary_structure"]["counts_3state"]["E"] > 0
    assert summary["residue_counts"]["dssp_annotated"] == 265
    assert any(w["code"] == "RSA_ABOVE_ONE" for w in summary["warnings"])
    rsa_above_one = {
        item["author_residue"]
        for item in annotations["annotations"]
        if item["rsa"] is not None and item["rsa"] > 1
    }
    assert rsa_above_one == {29, 293}
    assert all(item["rsa"] is None or item["rsa"] < 2 for item in annotations["annotations"])
    hits = summary["foldseek_hits"]
    assert hits[0]["target"] == "5XJH"
    assert [hit["evalue"] for hit in hits] == sorted(hit["evalue"] for hit in hits)
    assert all(
        hit["significant"] for hit in hits if hit["target"].split("_")[0] in {"5XJH", "4CG1", "1JFR"}
    )
    assert next(hit for hit in hits if hit["target"] == "1UBQ")["significant"] is False
    triad = {item["author_residue"]: item for item in annotations["annotations"]}
    conservation = json.loads((sequence_out / "conservation.json").read_text())
    alignment = AlignIO.read(str(sequence_out / "alignment.fasta"), "fasta")
    target_row = next(
        row for row in alignment if row.id == json.loads((sequence_out / "alignment.json").read_text())["target_row_id"]
    )
    for item in annotations["annotations"]:
        if item["msa_column"] is not None:
            column = conservation["columns"][item["msa_column"] - 1]
            assert column["target_position"] == item["target_position"]
            assert str(target_row.seq)[item["msa_column"] - 1] == item["one_letter"]
    for residue, target_position, one_letter in ((160, 160, "S"), (206, 206, "D"), (237, 237, "H")):
        item = triad[residue]
        assert item["target_position"] == target_position
        assert item["one_letter"] == one_letter
        assert item["msa_column"] is not None
        column = conservation["columns"][item["msa_column"] - 1]
        assert column["target_position"] == target_position
    for item in annotations["annotations"]:
        if item["author_residue"] in (291, 292, 293):
            assert item["target_position"] is None
            assert item["msa_column"] is None
    assert any(w["code"] == "UNMODELLED_TARGET_RESIDUES" for w in summary["warnings"])
    assert any(w["code"] == "ALTERNATE_LOCATION" for w in summary["warnings"])
    assert any(w["code"] == "RESIDUE_OUTSIDE_TARGET" for w in summary["warnings"])
    assert all(record["tool_version"] for record in summary["provenance"])
    assert all(item["rsa"] is None or item["rsa"] >= 0 for item in annotations["annotations"])
    assert summary["numbering"]["mapping_quality"]["identity_fraction"] == 1.0


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
    assert residues[0].author_residue == 10
    assert any(w.code == "AUTHOR_NUMBERING_GAP" for w in warnings)
    assert any(w.code == "INSERTION_CODE" for w in warnings)


def test_structure_cli_errors_and_optional_conservation(
    tmp_path: Path, capsys
) -> None:
    common = [
        "structure",
        "--target",
        str(ROOT / "fixtures/target_ispetase.fasta"),
        "--references",
        str(ROOT / "fixtures/structures"),
        "--out",
        str(tmp_path / "errors"),
        "--threads",
        "1",
    ]
    assert main(common + ["--structure", str(ROOT / "fixtures/structures/6EQE.pdb.gz"), "--chain", "Z"]) == 1
    assert "chain 'Z' not found" in capsys.readouterr().err
    assert main(common + ["--structure", str(tmp_path / "missing.pdb"), "--chain", "A"]) == 1
    assert "missing.pdb" in capsys.readouterr().err

    out = tmp_path / "without-conservation"
    assert main(
        common[:1]
        + [
            "--structure",
            str(ROOT / "fixtures/structures/6EQE.pdb.gz"),
            "--chain",
            "A",
            "--out",
            str(out),
            "--threads",
            "1",
            "--target",
            str(ROOT / "fixtures/target_ispetase.fasta"),
            "--references",
            str(ROOT / "fixtures/structures"),
        ]
    ) == 0
    annotations = json.loads((out / "residue_annotations.json").read_text())["annotations"]
    assert all(
        item[field] is None
        for item in annotations
        for field in ("msa_column", "conservation", "gap_fraction", "entropy")
    )
    summary = json.loads((out / "structure_summary.json").read_text())
    assert any(w["code"] == "CONSERVATION_NOT_PROVIDED" for w in summary["warnings"])


def test_structure_mapping_quality_rejects_unrelated_target(tmp_path: Path) -> None:
    unrelated = tmp_path / "unrelated.fasta"
    unrelated.write_text(">unrelated\n" + "A" * 290 + "\n")
    out = tmp_path / "unrelated-structure"
    assert main(
        [
            "structure",
            "--structure",
            str(ROOT / "fixtures/structures/6EQE.pdb.gz"),
            "--chain",
            "A",
            "--target",
            str(unrelated),
            "--references",
            str(ROOT / "fixtures/structures"),
            "--out",
            str(out),
            "--threads",
            "1",
        ]
    ) == 0
    summary = json.loads((out / "structure_summary.json").read_text())
    quality = summary["numbering"]["mapping_quality"]
    assert quality["identity_fraction"] < 0.9
    warning = next(w for w in summary["warnings"] if w["code"] == "LOW_MAPPING_IDENTITY")
    assert warning["severity"] == "ERROR"


def test_5xjh_mapping_reports_author_numbering_exception(tmp_path: Path) -> None:
    out = tmp_path / "5xjh"
    assert main(
        [
            "structure",
            "--structure",
            str(ROOT / "fixtures/structures/5XJH.pdb.gz"),
            "--chain",
            "A",
            "--target",
            str(ROOT / "fixtures/target_ispetase.fasta"),
            "--references",
            str(ROOT / "fixtures/structures"),
            "--out",
            str(out),
            "--threads",
            "1",
        ]
    ) == 0
    summary = json.loads((out / "structure_summary.json").read_text())
    exceptions = summary["numbering"]["exceptions"]
    assert not summary["numbering"]["author_numbering_matches_target"]
    assert any(item["author_residue"] in {30, 31, 32, 33} for item in exceptions)
