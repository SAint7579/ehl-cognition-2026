from pathlib import Path

import pytest

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
