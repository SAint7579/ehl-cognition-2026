"""Orchestrate the CPU-native protein-engineering scientific slices."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .candidates import analyze_candidates
from .models import (
    CandidateSitesArtifact,
    ConstraintRecord,
    FinalResultArtifact,
    FinalResultShortlist,
    FinalResultSite,
    InvestigationInputs,
    InvestigationStage,
    InvestigationWarning,
    PlaybookReference,
    ProvenanceRecord,
    RunArtifact,
    StructureWarning,
)
from .pipeline import run_pipeline
from .provenance import file_digest, write_json_model
from .structure import analyze_structure
from .versions import environment_block

PLAYBOOK_PATH = Path(__file__).resolve().parents[1] / "playbooks" / "protein_engineering_v1.md"
EVIDENCE_LABELS = {
    "KNOWN": "Deposited coordinates and deposition metadata are retrieved known evidence.",
    "CALCULATED": (
        "MMseqs2, MAFFT, conservation, DSSP, Foldseek, sequence mapping, "
        "and candidate scores are calculated evidence."
    ),
    "PREDICTED": "Reserved and unused in this run.",
    "EXPERIMENTAL": "Reserved and unused in this run.",
}
EXPLICIT_LIMITATIONS = [
    "All reported evidence is retrieved or calculated; none is experimental validation.",
    "The activity and stability shortlists are heuristic rankings carrying no effect estimate.",
    "Nothing in this report is experimental validation.",
]


def run_investigation(
    objective: str,
    target_path: Path | str,
    database_path: Path | str,
    structure_path: Path | str,
    chain_id: str,
    references_dir: Path | str,
    out_dir: Path | str,
    constraints: Iterable[str] | None = None,
    threads: int | None = None,
    top_n: int = 10,
    catalytic_residue: int = 160,
    catalytic_atom: str = "OG",
    exclude: Iterable[int] = (160, 206, 237),
) -> tuple[FinalResultArtifact, bool]:
    target_path = Path(target_path).resolve()
    database_path = Path(database_path).resolve()
    structure_path = Path(structure_path).resolve()
    references_dir = Path(references_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if top_n < 1:
        raise ValueError("--top must be at least 1")
    parsed_constraints, catalytic_residue, catalytic_atom, exclude = _parse_constraints(
        constraints or (), catalytic_residue, catalytic_atom, exclude
    )
    playbook = _read_playbook(PLAYBOOK_PATH)
    started_at = datetime.now(timezone.utc)
    clock = time.perf_counter()
    stages: list[InvestigationStage] = []
    sequence_run: RunArtifact | None = None
    structure_summary = None
    candidate_artifact: CandidateSitesArtifact | None = None
    failed = False

    try:
        stage_started = datetime.now(timezone.utc)
        stage_clock = time.perf_counter()
        sequence_run = run_pipeline(target_path, database_path, out_dir / "sequence", threads)
        sequence_artifact_paths = [
            f"sequence/{path}"
            for stage in sequence_run.stages
            for path in stage.artifact_paths
        ]
        sequence_provenance = [
            record
            for stage in sequence_run.stages
            for record in stage.provenance
        ]
        stages.append(
            _completed_stage(
                "sequence",
                stage_started,
                stage_clock,
                out_dir,
                sequence_artifact_paths,
                sequence_provenance,
                [],
            )
        )
    except Exception as error:
        stages.append(_failed_stage("sequence", error, stage_started, stage_clock))
        failed = True

    if not failed:
        try:
            stage_started = datetime.now(timezone.utc)
            stage_clock = time.perf_counter()
            structure_out = out_dir / "structure"
            structure_summary, residue_annotations = analyze_structure(
                structure_path,
                chain_id,
                target_path,
                structure_out,
                references_dir,
                out_dir / "sequence" / "conservation.json",
                threads,
            )
            write_json_model(structure_out / "structure_summary.json", structure_summary)
            write_json_model(structure_out / "residue_annotations.json", residue_annotations)
            stages.append(
                _completed_stage(
                    "structure",
                    stage_started,
                    stage_clock,
                    out_dir,
                    ["structure/structure_summary.json", "structure/residue_annotations.json"],
                    structure_summary.provenance,
                    structure_summary.warnings,
                )
            )
        except Exception as error:
            stages.append(
                _failed_stage("structure", error, stage_started, stage_clock)
            )
            failed = True

    if not failed:
        try:
            stage_started = datetime.now(timezone.utc)
            stage_clock = time.perf_counter()
            candidates_out = out_dir / "candidates"
            candidate_artifact = analyze_candidates(
                out_dir / "structure" / "residue_annotations.json",
                structure_path,
                chain_id,
                candidates_out,
                out_dir / "sequence" / "alignment.fasta",
                catalytic_residue,
                catalytic_atom,
                exclude,
                max(1, len(residue_annotations.annotations)),
            )
            candidate_path = candidates_out / "candidate_sites.json"
            write_json_model(candidate_path, candidate_artifact)
            candidate_artifact = CandidateSitesArtifact.model_validate_json(
                candidate_path.read_text(encoding="utf-8")
            )
            stages.append(
                _completed_stage(
                    "candidates",
                    stage_started,
                    stage_clock,
                    out_dir,
                    ["candidates/candidate_sites.json"],
                    [candidate_artifact.provenance],
                    candidate_artifact.warnings,
                )
            )
        except Exception as error:
            stages.append(
                _failed_stage("candidates", error, stage_started, stage_clock)
            )
            failed = True

    while len(stages) < 3:
        stages.append(_skipped_stage(("sequence", "structure", "candidates")[len(stages)]))

    limitations = _unique(
        (sequence_run.limitations if sequence_run else [])
        + (structure_summary.limitations if structure_summary else [])
        + (candidate_artifact.limitations if candidate_artifact else [])
        + EXPLICIT_LIMITATIONS
    )
    ended_at = datetime.now(timezone.utc)
    result = FinalResultArtifact(
        run_id=str(uuid.uuid4()),
        playbook=PlaybookReference(
            id=playbook["id"],
            name=playbook["name"],
            version=playbook["version"],
            path=str(PLAYBOOK_PATH.relative_to(Path(__file__).resolve().parents[1])),
            digest=file_digest(PLAYBOOK_PATH),
        ),
        objective=objective,
        constraints=parsed_constraints,
        inputs=InvestigationInputs(
            target=file_digest(target_path),
            database=file_digest(database_path),
            structure=file_digest(structure_path),
            references_path=str(references_dir),
            chain=chain_id,
        ),
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=time.perf_counter() - clock,
        stages=stages,
        artifact_index={stage.stage: stage.artifact_paths for stage in stages},
        shortlists=_shortlists(candidate_artifact, top_n),
        evidence_labels=EVIDENCE_LABELS,
        environment=environment_block(),
        warnings=[
            InvestigationWarning(stage=stage.stage, **warning.model_dump())
            for stage in stages
            for warning in stage.warnings
        ],
        limitations=limitations,
    )
    return result, not failed


def _parse_constraints(
    raw_constraints: Iterable[str],
    catalytic_residue: int,
    catalytic_atom: str,
    exclude: Iterable[int],
) -> tuple[list[ConstraintRecord], int, str, list[int]]:
    parsed: list[ConstraintRecord] = []
    effective_exclude = list(exclude)
    for raw in raw_constraints:
        if "=" not in raw:
            raise ValueError(f"malformed --constraint {raw!r}; expected key=value")
        key, value = raw.split("=", 1)
        if not key:
            raise ValueError(f"malformed --constraint {raw!r}; key cannot be empty")
        if key == "exclude_residues":
            try:
                effective_exclude = [
                    int(item.strip()) for item in value.split(",") if item.strip()
                ]
            except ValueError as error:
                raise ValueError(f"invalid exclude_residues constraint: {value!r}") from error
            enforcement = "ENFORCED_BY_PIPELINE"
            note = "Applied by the candidate stage exclusion filter."
        elif key == "catalytic_residue":
            try:
                catalytic_residue = int(value)
            except ValueError as error:
                raise ValueError(f"invalid catalytic_residue constraint: {value!r}") from error
            enforcement = "ENFORCED_BY_PIPELINE"
            note = "Applied by the candidate stage catalytic-residue parameter."
        elif key == "catalytic_atom":
            catalytic_atom = value
            enforcement = "ENFORCED_BY_PIPELINE"
            note = "Applied by the candidate stage catalytic-atom parameter."
        else:
            enforcement = "RECORDED_ONLY"
            note = "Recorded for the report; not enforced by any pipeline stage."
        parsed.append(
            ConstraintRecord(
                key=key,
                value=value,
                enforcement=enforcement,
                note=note,
            )
        )
    return parsed, catalytic_residue, catalytic_atom, effective_exclude


def _read_playbook(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"playbook {path} is missing front matter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"playbook {path} has unterminated front matter") from error
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"invalid playbook front matter line: {line!r}")
        key, value = line.split(":", 1)
        if not key.strip() or not value.strip():
            raise ValueError(f"invalid playbook front matter line: {line!r}")
        metadata[key.strip()] = value.strip()
    required = {"id", "name", "version", "updated", "scope"}
    missing = required - metadata.keys()
    if missing:
        raise ValueError(f"playbook front matter missing keys: {', '.join(sorted(missing))}")
    return metadata


def _completed_stage(
    stage: str,
    started_at: datetime,
    stage_clock: float,
    out_dir: Path,
    artifact_paths: list[str],
    provenance: list[ProvenanceRecord],
    warnings: list[StructureWarning],
) -> InvestigationStage:
    return InvestigationStage(
        stage=stage,
        status="COMPLETED",
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        duration_seconds=time.perf_counter() - stage_clock,
        artifact_paths=artifact_paths,
        artifact_digests=[file_digest(out_dir / path) for path in artifact_paths],
        provenance=provenance,
        warnings=warnings,
        error=None,
    )


def _failed_stage(
    stage: str, error: Exception, started_at: datetime, stage_clock: float
) -> InvestigationStage:
    ended_at = datetime.now(timezone.utc)
    return InvestigationStage(
        stage=stage,
        status="FAILED",
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=time.perf_counter() - stage_clock,
        artifact_paths=[],
        artifact_digests=[],
        provenance=[],
        warnings=[],
        error=str(error),
    )


def _skipped_stage(stage: str) -> InvestigationStage:
    return InvestigationStage(
        stage=stage,
        status="SKIPPED",
        started_at=None,
        ended_at=None,
        duration_seconds=None,
        artifact_paths=[],
        artifact_digests=[],
        provenance=[],
        warnings=[],
        error=None,
    )


def _shortlists(
    artifact: CandidateSitesArtifact | None, top_n: int
) -> dict[str, FinalResultShortlist]:
    defaults = {
        "activity": "Substrate-cleft engineering",
        "stability": "Surface engineering away from the active site",
    }
    return {
        name: FinalResultShortlist(
            objective=artifact.shortlists[name].objective if artifact else defaults[name],
            n_total=artifact.shortlists[name].n_sites if artifact else 0,
            top_n=min(top_n, artifact.shortlists[name].n_sites) if artifact else 0,
            sites=[
                FinalResultSite(
                    rank=site.rank,
                    author_residue=site.author_residue,
                    target_position=site.target_position,
                    one_letter=site.one_letter,
                    conservation=site.conservation,
                    rsa=site.rsa,
                    distance_to_active_site_angstrom=site.distance_to_active_site_angstrom,
                    score=site.score,
                    substitution_options=site.substitution_options,
                    evidence_type=site.evidence_type,
                )
                for site in (artifact.shortlists[name].sites[:top_n] if artifact else [])
            ],
        )
        for name in ("activity", "stability")
    }


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
