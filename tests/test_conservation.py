from pathlib import Path

import pytest

from bio_tools.conservation import analyze_alignment


def write_alignment(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    path = tmp_path / "alignment.fasta"
    path.write_text("".join(f">{name}\n{sequence}\n" for name, sequence in rows))
    return path


def test_conservation_math_cases(tmp_path: Path) -> None:
    identical = analyze_alignment(
        write_alignment(tmp_path, [("target", "A"), ("a", "A"), ("b", "A")]), "target"
    ).columns[0]
    assert identical.conservation == pytest.approx(1.0)
    assert identical.entropy == pytest.approx(0.0)

    half = analyze_alignment(
        write_alignment(tmp_path, [("target", "A"), ("a", "A"), ("b", "B"), ("c", "B")]), "target"
    ).columns[0]
    assert half.entropy == pytest.approx(1.0)
    assert half.conservation == pytest.approx(1 - 1 / __import__("math").log2(20))

    uniform = analyze_alignment(
        write_alignment(
            tmp_path,
            [("target", "A")] + [(f"x{i}", residue) for i, residue in enumerate("CDEFGHIKLMNPQRSTVWY")],
        ),
        "target",
    ).columns[0]
    assert uniform.conservation == pytest.approx(0.0)


def test_uninformative_and_target_position_mapping(tmp_path: Path) -> None:
    artifact = analyze_alignment(
        write_alignment(
            tmp_path,
            [("target", "A-C"), ("a", "A-C"), ("b", "---"), ("c", "A-C")],
        ),
        "target",
    )
    assert artifact.columns[1].target_position is None
    assert artifact.columns[1].entropy is None
    assert artifact.columns[1].conservation is None
    assert artifact.columns[2].target_position == 2

    single = analyze_alignment(
        write_alignment(tmp_path, [("target", "A"), ("a", "-")]), "target"
    ).columns[0]
    assert single.entropy is None
    assert single.informative is False

    all_gap = analyze_alignment(
        write_alignment(tmp_path, [("target", "-"), ("a", "-")]), "target"
    ).columns[0]
    assert all_gap.entropy is None
    assert all_gap.target_position is None
