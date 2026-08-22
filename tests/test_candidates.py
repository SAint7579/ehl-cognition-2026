import json
import gzip
from pathlib import Path

from Bio.PDB import PDBParser
from jsonschema import Draft202012Validator

from bio_tools.candidates import _minimum_heavy_atom_distance, _sub_scores
from bio_tools.cli import main
from bio_tools.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]


def _prepare_structure(tmp_path: Path) -> tuple[Path, Path, Path]:
    sequence_out = tmp_path / "sequence"
    run_pipeline(
        ROOT / "fixtures/target_ispetase.fasta",
        ROOT / "fixtures/homolog_db.fasta",
        sequence_out,
        threads=1,
    )
    structure_out = tmp_path / "structure"
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
            str(structure_out),
            "--threads",
            "1",
        ]
    ) == 0
    return (
        structure_out / "residue_annotations.json",
        ROOT / "fixtures/structures/6EQE.pdb.gz",
        sequence_out / "alignment.fasta",
    )


def _run_candidates(
    annotations: Path,
    structure: Path,
    alignment: Path | None,
    out: Path,
    extra: list[str] | None = None,
) -> int:
    args = [
        "candidates",
        "--annotations",
        str(annotations),
        "--structure",
        str(structure),
        "--chain",
        "A",
        "--out",
        str(out),
    ]
    if alignment is not None:
        args.extend(["--alignment", str(alignment)])
    if extra:
        args.extend(extra)
    return main(args)


def test_candidate_cli_artifact_filters_ranking_and_determinism(tmp_path: Path) -> None:
    annotations, structure, alignment = _prepare_structure(tmp_path)
    first = tmp_path / "candidates-1"
    second = tmp_path / "candidates-2"
    assert _run_candidates(annotations, structure, alignment, first) == 0
    assert _run_candidates(annotations, structure, alignment, second) == 0
    first_path = first / "candidate_sites.json"
    second_path = second / "candidate_sites.json"
    artifact = json.loads(first_path.read_text())
    second_artifact = json.loads(second_path.read_text())
    assert artifact["shortlists"] == second_artifact["shortlists"]
    schema = json.loads((ROOT / "schemas/candidate_sites.schema.json").read_text())
    Draft202012Validator(schema).validate(artifact)
    assert artifact["evidence_type"] == "CALCULATED"
    assert artifact["provenance"]["argv"] is None
    assert artifact["provenance"]["exit_code"] is None
    assert artifact["provenance"]["input_files"]
    activity = artifact["shortlists"]["activity"]
    stability = artifact["shortlists"]["stability"]
    assert {site["author_residue"] for site in activity["sites"]}.isdisjoint(
        site["author_residue"] for site in stability["sites"]
    )
    for name, sites in (("activity", activity["sites"]), ("stability", stability["sites"])):
        assert [site["rank"] for site in sites] == list(range(1, len(sites) + 1))
        assert [(site["score"], site["target_position"]) for site in sites] == sorted(
            ((site["score"], site["target_position"]) for site in sites),
            key=lambda item: (-item[0], item[1]),
        )
        for site in sites:
            assert site["author_residue"] not in {160, 206, 237}
            if name == "activity":
                assert site["distance_to_active_site_angstrom"] <= 12.0
                assert site["conservation"] < 0.98
                assert site["rsa"] < 0.50
            else:
                assert site["distance_to_active_site_angstrom"] >= 12.0
                assert site["conservation"] < 0.90
                assert site["rsa"] >= 0.25
            assert all(
                option["residue"] != site["one_letter"]
                and option["residue"] != "-"
                for option in site["substitution_options"]
            )
    assert artifact["shortlists"]["activity"]["n_sites"] == len(activity["sites"])
    assert artifact["shortlists"]["stability"]["n_sites"] == len(stability["sites"])


def test_candidate_subscores_clamp_at_both_ends() -> None:
    low = _sub_scores(0.0, 0.0, 0.0, "C")
    high = _sub_scores(30.0, 1.0, 1.5, "H")
    assert low.proximity == 1.0
    assert low.burial == 1.0
    assert high.proximity == 0.0
    assert high.remoteness == 1.0
    assert high.exposure == 1.0
    assert all(0.0 <= value <= 1.0 for value in low.model_dump().values() if isinstance(value, float))
    assert all(0.0 <= value <= 1.0 for value in high.model_dump().values() if isinstance(value, float))


def test_candidate_distance_alignment_warning_and_errors(
    tmp_path: Path, capsys
) -> None:
    annotations, structure, alignment = _prepare_structure(tmp_path)
    no_alignment = tmp_path / "without-alignment"
    assert _run_candidates(annotations, structure, None, no_alignment) == 0
    no_alignment_artifact = json.loads(
        (no_alignment / "candidate_sites.json").read_text()
    )
    assert any(
        warning["code"] == "ALIGNMENT_UNAVAILABLE"
        for warning in no_alignment_artifact["warnings"]
    )
    for shortlist in no_alignment_artifact["shortlists"].values():
        assert all(not site["substitution_options"] for site in shortlist["sites"])

    bad_atom = tmp_path / "bad-atom"
    assert _run_candidates(
        annotations,
        structure,
        alignment,
        bad_atom,
        ["--catalytic-atom", "ZZ"],
    ) == 1
    assert "catalytic atom" in capsys.readouterr().err
    bad_chain = tmp_path / "bad-chain"
    assert main(
        [
            "candidates",
            "--annotations",
            str(annotations),
            "--structure",
            str(structure),
            "--chain",
            "Z",
            "--out",
            str(bad_chain),
        ]
    ) == 1
    assert "chain 'Z' not found" in capsys.readouterr().err
    missing = tmp_path / "missing"
    assert main(
        [
            "candidates",
            "--annotations",
            str(annotations),
            "--structure",
            str(tmp_path / "missing.pdb"),
            "--chain",
            "A",
            "--out",
            str(missing),
        ]
    ) == 1
    assert "missing.pdb" in capsys.readouterr().err

    staged = tmp_path / "distance.pdb"
    with gzip.open(structure, "rb") as source, staged.open("wb") as destination:
        destination.write(source.read())
    model = next(PDBParser(QUIET=True).get_structure("6EQE", str(staged)).get_models())
    chain = model["A"]
    catalytic_coord = chain[(" ", 160, " ")][
        "OG"
    ].get_coord()
    assert _minimum_heavy_atom_distance(chain[(" ", 206, " ")], catalytic_coord) < 7.0
    assert _minimum_heavy_atom_distance(chain[(" ", 237, " ")], catalytic_coord) < 7.0
