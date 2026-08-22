"""End-to-end orchestration for the CPU-native protein pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .conservation import analyze_alignment
from .homology import run_homolog_search
from .models import (
    RunArtifact,
    StageArtifact,
)
from .msa import run_msa
from .provenance import file_digest, write_json_model
from .versions import environment_block

ModelT = TypeVar("ModelT", bound=BaseModel)


def run_pipeline(
    target_path: Path | str,
    database_path: Path | str,
    out_dir: Path | str,
    threads: int | None = None,
) -> RunArtifact:
    target_path = Path(target_path).resolve()
    database_path = Path(database_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    homologs = run_homolog_search(target_path, database_path, out_dir, threads)
    homolog_json = out_dir / "homolog_search.json"
    _write_json(homolog_json, homologs)
    homolog_artifacts = [out_dir / "homologs.fasta", homolog_json]
    msa_json = out_dir / "alignment.json"
    alignment_path = out_dir / "alignment.fasta"
    alignment = run_msa(out_dir / "homologs.fasta", alignment_path, threads)
    _write_json(msa_json, alignment)
    msa_artifacts = [alignment_path, msa_json]
    conservation_json = out_dir / "conservation.json"
    conservation = _write_json(
        conservation_json,
        analyze_alignment(alignment_path, alignment.target_row_id),
    )
    conservation_artifacts = [conservation_json]
    ended = datetime.now(timezone.utc)
    run = RunArtifact(
        pipeline_version="0.1.0",
        run_id=str(uuid.uuid4()),
        started_at=started,
        ended_at=ended,
        input_files=[file_digest(target_path), file_digest(database_path)],
        stages=[
            StageArtifact(
                stage="homolog-search",
                status="COMPLETED",
                artifact_paths=["homologs.fasta", "homolog_search.json"],
                artifact_digests=[file_digest(path) for path in homolog_artifacts],
                provenance=[homologs.provenance],
            ),
            StageArtifact(
                stage="msa",
                status="COMPLETED",
                artifact_paths=["alignment.fasta", "alignment.json"],
                artifact_digests=[file_digest(path) for path in msa_artifacts],
                provenance=[alignment.provenance],
            ),
            StageArtifact(
                stage="conservation",
                status="COMPLETED",
                artifact_paths=["conservation.json"],
                artifact_digests=[file_digest(path) for path in conservation_artifacts],
                provenance=[conservation.provenance],
            ),
        ],
        environment=environment_block(),
        limitations=[
            "All results in this pipeline are computational (CALCULATED).",
            "None of the results are experimentally validated.",
        ],
    )
    _write_json(out_dir / "run.json", run)
    return run


def _write_json(path: Path, model: ModelT) -> ModelT:
    return write_json_model(path, model)
