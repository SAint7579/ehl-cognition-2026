"""Transparent candidate-site generation from structure and sequence artifacts."""

from __future__ import annotations

import gzip
import math
import shutil
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
from Bio import AlignIO
from Bio.Align import MultipleSeqAlignment
from Bio.PDB import PDBParser
from Bio.PDB.Residue import Residue
from numpy.typing import NDArray

from . import __version__
from .models import (
    CandidateShortlist,
    CandidateSite,
    CandidateSitesArtifact,
    CandidateSubScores,
    CandidateSubstitutionOption,
    ProvenanceRecord,
    ResidueAnnotationsArtifact,
    StructureWarning,
)
from .provenance import file_digest

LIMITATIONS = [
    "Scores are transparent heuristic rankings over CALCULATED sequence and structure features.",
    "The rankings are not predictions of activity or stability.",
    "The rankings carry no effect estimate and are not experimental validation.",
    "Substitution options are observed homolog alignment residues, not predictions, recommendations, or beneficial effects.",
]

ACTIVITY_WEIGHTS = {
    "proximity": 0.50,
    "plasticity": 0.30,
    "burial": 0.20,
}
STABILITY_WEIGHTS = {
    "exposure": 0.35,
    "variability": 0.30,
    "remoteness": 0.20,
    "loop": 0.15,
}

FEATURE_DEFINITIONS = {
    "lin": "lin(x, lo, hi) = clamp((x - lo) / (hi - lo), 0, 1)",
    "proximity": "1 - lin(distance_to_active_site_angstrom, 4.0, 12.0)",
    "remoteness": "lin(distance_to_active_site_angstrom, 12.0, 25.0)",
    "burial": "1 - lin(rsa, 0.0, 0.5)",
    "exposure": "lin(rsa, 0.0, 0.5)",
    "plasticity": "1 - lin(conservation, 0.60, 0.98)",
    "variability": "1 - lin(conservation, 0.50, 0.90)",
    "loop": '1.0 if secondary_structure == "C" else 0.0',
}

SCORE_DEFINITIONS = {
    "activity": "0.50 * proximity + 0.30 * plasticity + 0.20 * burial",
    "stability": "0.35 * exposure + 0.30 * variability + 0.20 * remoteness + 0.15 * loop",
}


@dataclass(frozen=True)
class CandidateFeature:
    author_residue: int
    insertion_code: str | None
    structure_index: int
    target_position: int
    msa_column: int | None
    one_letter: str
    conservation: float
    rsa: float
    secondary_structure: str | None
    distance_to_active_site_angstrom: float
    sub_scores: CandidateSubScores


def analyze_candidates(
    annotations_path: Path | str,
    structure_path: Path | str,
    chain_id: str,
    out_dir: Path | str,
    alignment_path: Path | str | None = None,
    catalytic_residue: int = 160,
    catalytic_atom: str = "OG",
    exclude: Iterable[int] = (160, 206, 237),
    top_n: int = 15,
) -> CandidateSitesArtifact:
    annotations_path = Path(annotations_path).resolve()
    structure_path = Path(structure_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    exclude_set = {int(value) for value in exclude}
    if top_n < 1:
        raise ValueError("--top must be at least 1")

    started_at = datetime.now(timezone.utc)
    clock = time.perf_counter()
    annotations = ResidueAnnotationsArtifact.model_validate_json(
        annotations_path.read_text(encoding="utf-8")
    )
    pdb_path = _stage_structure(structure_path, out_dir)
    structure = PDBParser(QUIET=True).get_structure(pdb_path.stem, str(pdb_path))
    model = next(structure.get_models())
    if chain_id not in model:
        raise ValueError(f"chain {chain_id!r} not found in structure")
    chain = model[chain_id]
    residue_by_author = {
        (int(residue.id[1]), residue.id[2].strip() or None): residue
        for residue in chain
        if residue.id[0] == " "
    }
    catalytic = residue_by_author.get((catalytic_residue, None))
    if catalytic is None:
        catalytic = next(
            (
                residue
                for (author_residue, _), residue in residue_by_author.items()
                if author_residue == catalytic_residue
            ),
            None,
        )
    if catalytic is None:
        raise ValueError(f"catalytic residue {catalytic_residue} not found in chain {chain_id!r}")
    if catalytic_atom not in catalytic:
        raise ValueError(
            f"catalytic atom {catalytic_atom!r} not found in residue {catalytic_residue}"
        )
    catalytic_coord = catalytic[catalytic_atom].get_coord()

    alignment: MultipleSeqAlignment | None = None
    warnings: list[StructureWarning] = []
    if alignment_path is not None:
        alignment_path = Path(alignment_path).resolve()
        alignment = AlignIO.read(str(alignment_path), "fasta")
    else:
        warnings.append(
            StructureWarning(
                code="ALIGNMENT_UNAVAILABLE",
                message="Alignment was not provided; substitution options are unavailable.",
                severity="WARNING",
            )
        )

    incomplete: list[str] = []
    features: list[CandidateFeature] = []
    for annotation in annotations.annotations:
        if annotation.target_position is None:
            continue
        if annotation.conservation is None or annotation.rsa is None:
            incomplete.append(str(annotation.author_residue))
            continue
        residue = residue_by_author.get(
            (annotation.author_residue, annotation.insertion_code)
        )
        if residue is None:
            raise ValueError(
                f"author residue {annotation.author_residue}{annotation.insertion_code or ''} "
                f"from annotations not found in chain {chain_id!r}"
            )
        distance = _minimum_heavy_atom_distance(residue, catalytic_coord)
        scores = _sub_scores(distance, annotation.conservation, annotation.rsa, annotation.secondary_structure)
        features.append(
            CandidateFeature(
                author_residue=annotation.author_residue,
                insertion_code=annotation.insertion_code,
                structure_index=annotation.structure_index,
                target_position=annotation.target_position,
                msa_column=annotation.msa_column,
                one_letter=annotation.one_letter,
                conservation=annotation.conservation,
                rsa=annotation.rsa,
                secondary_structure=annotation.secondary_structure,
                distance_to_active_site_angstrom=distance,
                sub_scores=scores,
            )
        )
    if incomplete:
        warnings.append(
            StructureWarning(
                code="INCOMPLETE_FEATURES",
                message=f"Conservation or RSA is missing for author residues: {', '.join(incomplete)}.",
                severity="WARNING",
            )
        )

    activity_sites = _rank_sites(
        [
            _make_site(
                feature,
                score=(
                    0.50 * feature.sub_scores.proximity
                    + 0.30 * feature.sub_scores.plasticity
                    + 0.20 * feature.sub_scores.burial
                ),
                substitution_options=_substitution_options_for_feature(feature, alignment),
            )
            for feature in features
            if (
                feature.distance_to_active_site_angstrom <= 12.0
                and feature.conservation < 0.98
                and feature.rsa < 0.50
                and feature.author_residue not in exclude_set
            )
        ]
    )
    stability_sites = _rank_sites(
        [
            _make_site(
                feature,
                score=(
                    0.35 * feature.sub_scores.exposure
                    + 0.30 * feature.sub_scores.variability
                    + 0.20 * feature.sub_scores.remoteness
                    + 0.15 * feature.sub_scores.loop
                ),
                substitution_options=_substitution_options_for_feature(feature, alignment),
            )
            for feature in features
            if (
                feature.distance_to_active_site_angstrom >= 12.0
                and feature.conservation < 0.90
                and feature.rsa >= 0.25
                and feature.author_residue not in exclude_set
            )
        ]
    )

    input_files = [annotations_path, structure_path]
    if alignment_path is not None:
        input_files.append(alignment_path)
    ended_at = datetime.now(timezone.utc)
    parameters = {
        "catalytic_residue": catalytic_residue,
        "catalytic_atom": catalytic_atom,
        "exclude": sorted(exclude_set),
        "top_n": top_n,
        "activity_filters": {
            "distance_to_active_site_angstrom_max": 12.0,
            "conservation_max_exclusive": 0.98,
            "rsa_max_exclusive": 0.50,
        },
        "stability_filters": {
            "distance_to_active_site_angstrom_min": 12.0,
            "conservation_max_exclusive": 0.90,
            "rsa_min_inclusive": 0.25,
        },
        "feature_cutoffs": {
            "proximity_distance_low": 4.0,
            "proximity_distance_high": 12.0,
            "remoteness_distance_low": 12.0,
            "remoteness_distance_high": 25.0,
            "burial_rsa_low": 0.0,
            "burial_rsa_high": 0.5,
            "exposure_rsa_low": 0.0,
            "exposure_rsa_high": 0.5,
            "plasticity_conservation_low": 0.60,
            "plasticity_conservation_high": 0.98,
            "variability_conservation_low": 0.50,
            "variability_conservation_high": 0.90,
        },
        "activity_weights": ACTIVITY_WEIGHTS,
        "stability_weights": STABILITY_WEIGHTS,
        "substitution_option_rules": {
            "minimum_count": 2,
            "minimum_frequency": 0.15,
            "frequency_denominator": "non-gap characters in the MSA column",
            "sort": "frequency descending, residue ascending",
        },
    }
    provenance = ProvenanceRecord(
        stage="candidate-site-generation",
        tool_name="bio_tools.candidates",
        tool_version=__version__,
        argv=None,
        parameters=parameters,
        input_files=[file_digest(path) for path in input_files],
        output_files=[],
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=time.perf_counter() - clock,
        exit_code=None,
        evidence_type="CALCULATED",
    )
    return CandidateSitesArtifact(
        target_id=annotations.target_id,
        provenance=provenance,
        parameters=parameters,
        feature_definitions=FEATURE_DEFINITIONS,
        score_definitions=SCORE_DEFINITIONS,
        shortlists={
            "activity": CandidateShortlist(
                objective="Substrate-cleft engineering",
                filters={
                    "distance_to_active_site_angstrom": "<= 12.0",
                    "conservation": "< 0.98",
                    "rsa": "< 0.50",
                    "author_residue": "not in exclude",
                },
                weights=ACTIVITY_WEIGHTS,
                n_sites=len(activity_sites),
                sites=activity_sites,
            ),
            "stability": CandidateShortlist(
                objective="Surface engineering away from the active site",
                filters={
                    "distance_to_active_site_angstrom": ">= 12.0",
                    "conservation": "< 0.90",
                    "rsa": ">= 0.25",
                    "author_residue": "not in exclude",
                },
                weights=STABILITY_WEIGHTS,
                n_sites=len(stability_sites),
                sites=stability_sites,
            ),
        },
        warnings=warnings,
        limitations=LIMITATIONS,
    )


def _stage_structure(path: Path, out_dir: Path) -> Path:
    if path.suffix != ".gz":
        return path
    output = out_dir / "structure_input.pdb"
    with gzip.open(path, "rb") as source, output.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    return output


def _make_site(
    feature: CandidateFeature,
    score: float,
    substitution_options: list[CandidateSubstitutionOption],
) -> CandidateSite:
    return CandidateSite(
        author_residue=feature.author_residue,
        insertion_code=feature.insertion_code,
        structure_index=feature.structure_index,
        target_position=feature.target_position,
        msa_column=feature.msa_column,
        one_letter=feature.one_letter,
        conservation=feature.conservation,
        rsa=feature.rsa,
        secondary_structure=feature.secondary_structure,
        distance_to_active_site_angstrom=feature.distance_to_active_site_angstrom,
        sub_scores=feature.sub_scores,
        score=score,
        rank=0,
        substitution_options=substitution_options,
        evidence_type="CALCULATED",
    )


def _substitution_options_for_feature(
    feature: CandidateFeature,
    alignment: MultipleSeqAlignment | None,
) -> list[CandidateSubstitutionOption]:
    return _substitution_options(alignment, feature.msa_column, feature.one_letter)


def _minimum_heavy_atom_distance(
    residue: Residue, catalytic_coord: NDArray[np.float64]
) -> float:
    atoms = (
        atom
        for atom in residue.get_atoms()
        if str(atom.element).upper() != "H"
    )
    return min(
        math.dist(tuple(atom.get_coord()), tuple(catalytic_coord))
        for atom in atoms
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _lin(value: float, low: float, high: float) -> float:
    return _clamp((value - low) / (high - low))


def _sub_scores(
    distance: float,
    conservation: float,
    rsa: float,
    secondary_structure: str | None,
) -> CandidateSubScores:
    return CandidateSubScores(
        proximity=1.0 - _lin(distance, 4.0, 12.0),
        remoteness=_lin(distance, 12.0, 25.0),
        burial=1.0 - _lin(rsa, 0.0, 0.5),
        exposure=_lin(rsa, 0.0, 0.5),
        plasticity=1.0 - _lin(conservation, 0.60, 0.98),
        variability=1.0 - _lin(conservation, 0.50, 0.90),
        loop=1.0 if secondary_structure == "C" else 0.0,
    )


def _rank_sites(sites: list[CandidateSite]) -> list[CandidateSite]:
    ordered = sorted(sites, key=lambda site: (-site.score, site.target_position))
    return [site.model_copy(update={"rank": rank}) for rank, site in enumerate(ordered, start=1)]


def _substitution_options(
    alignment: MultipleSeqAlignment | None,
    msa_column: int | None,
    wild_type: str,
) -> list[CandidateSubstitutionOption]:
    if alignment is None or msa_column is None:
        return []
    residues = [
        str(row.seq)[msa_column - 1]
        for row in alignment
        if str(row.seq)[msa_column - 1] != "-"
    ]
    non_wild_type = [residue for residue in residues if residue != wild_type]
    counts = Counter(non_wild_type)
    denominator = len(residues)
    return [
        CandidateSubstitutionOption(
            residue=residue,
            count=count,
            frequency=count / denominator,
            source="observed_in_homologs",
        )
        for residue, count in sorted(
            counts.items(), key=lambda item: (-item[1] / denominator, item[0])
        )
        if count >= 2 and count / denominator >= 0.15
    ]
