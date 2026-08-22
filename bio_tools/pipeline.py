"""End-to-end orchestration for the CPU-native protein pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from .conservation import analyze_alignment
from .homology import run_homolog_search
from .models import (
    ConservationArtifact,
    FileDigest,
    ProvenanceRecord,
    RunArtifact,
    StageArtifact,
)
from .msa import run_msa
from .provenance import file_digest
from .versions import environment_block


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
    msa_json = out_dir / "alignment.json"
    alignment_path = out_dir / "alignment.fasta"
    alignment = run_msa(out_dir / "homologs.fasta", alignment_path, threads)
    _write_json(msa_json, alignment)
    conservation_json = out_dir / "conservation.json"
    conservation = analyze_alignment(alignment_path, alignment.target_row_id)
    conservation = conservation.model_copy(
        update={"provenance": _python_provenance(alignment_path, conservation_json)}
    )
    _write_json(conservation_json, conservation)
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
                provenance=[homologs.provenance],
            ),
            StageArtifact(
                stage="msa",
                status="COMPLETED",
                artifact_paths=["alignment.fasta", "alignment.json"],
                provenance=[alignment.provenance],
            ),
            StageArtifact(
                stage="conservation",
                status="COMPLETED",
                artifact_paths=["conservation.json"],
                provenance=[conservation.provenance],  # type: ignore[list-item]
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


def _write_json(path: Path, model: object) -> None:
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")  # type: ignore[attr-defined]


def _python_provenance(input_path: Path, output_path: Path) -> ProvenanceRecord:
    now = datetime.now(timezone.utc)
    return ProvenanceRecord(
        stage="conservation",
        tool_name="python-conservation",
        tool_version="0.1.0",
        argv=["python", "-m", "bio_tools.conservation"],
        parameters={"math": "Shannon entropy base 2 over non-gap residues"},
        input_files=[file_digest(input_path)],
        output_files=[file_digest(output_path)] if output_path.exists() else [],
        started_at=now,
        ended_at=now,
        duration_seconds=0.0,
        exit_code=0,
        evidence_type="CALCULATED",
    )
