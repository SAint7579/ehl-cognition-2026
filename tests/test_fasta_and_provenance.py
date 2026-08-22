import json
from pathlib import Path

import pytest

from bio_tools.cli import main
from bio_tools.fasta_io import validate_target
from bio_tools.provenance import run_tool


def test_target_validation_errors(tmp_path: Path) -> None:
    empty = tmp_path / "empty.fasta"
    empty.write_text("")
    with pytest.raises(ValueError, match="exactly one"):
        validate_target(empty)
    invalid = tmp_path / "invalid.fasta"
    invalid.write_text(">target\nAB*Z\n")
    with pytest.raises(ValueError, match="invalid protein"):
        validate_target(invalid)
    multi = tmp_path / "multi.fasta"
    multi.write_text(">a\nACD\n>b\nACD\n")
    with pytest.raises(ValueError, match="exactly one"):
        validate_target(multi)


def test_provenance_record_shape(tmp_path: Path) -> None:
    input_file = tmp_path / "input.txt"
    output_file = tmp_path / "output.txt"
    input_file.write_text("input")
    output_file.write_text("output")
    record = run_tool(
        "test",
        "python",
        ["python", "-c", "print('ok')"],
        {"example": True},
        [input_file],
        [output_file],
    )
    assert record.stage == "test"
    assert record.tool_name == "python"
    assert record.argv[-1] == "print('ok')"
    assert record.input_files[0].bytes == 5
    assert record.output_files[0].bytes == 6
    assert record.exit_code == 0
    assert record.evidence_type == "CALCULATED"


def test_cli_invalid_target_returns_readable_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "invalid.fasta"
    target.write_text(">target\nAB*\n")
    exit_code = main(
        [
            "homolog-search",
            "--target",
            str(target),
            "--database",
            str(tmp_path / "missing.fasta"),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "invalid protein residue" in captured.err


def test_cli_conservation_writes_provenance(tmp_path: Path) -> None:
    alignment = tmp_path / "alignment.fasta"
    alignment.write_text(">target\nAC\n>other\nAC\n")
    out = tmp_path / "out"
    assert main(
        [
            "conservation",
            "--alignment",
            str(alignment),
            "--target-id",
            "target",
            "--out",
            str(out),
        ]
    ) == 0
    artifact = json.loads((out / "conservation.json").read_text())
    provenance = artifact["provenance"]
    assert provenance["tool_name"] == "bio_tools.conservation"
    assert provenance["tool_version"]
    assert provenance["argv"] is None
    assert provenance["exit_code"] is None
    assert provenance["input_files"]
    assert provenance["output_files"] == []
