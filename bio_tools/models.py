"""Validated artifact models and their JSON schema version."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.0.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileDigest(StrictModel):
    path: str
    sha256: str
    bytes: int


class ProvenanceRecord(StrictModel):
    stage: str
    tool_name: str
    tool_version: str
    argv: list[str]
    parameters: dict[str, Any]
    input_files: list[FileDigest]
    output_files: list[FileDigest]
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    exit_code: int
    evidence_type: Literal["KNOWN", "CALCULATED", "PREDICTED", "EXPERIMENTAL"]
    stdout: str = ""
    stderr: str = ""


class HomologHit(StrictModel):
    accession: str
    description: str
    evalue: float
    bit_score: float
    percent_identity: float
    alignment_length: int
    query_coverage: float
    target_coverage: float


class DiversitySummary(StrictModel):
    n_hits: int
    min_percent_identity: float | None
    median_percent_identity: float | None
    max_percent_identity: float | None


class HomologSearchArtifact(StrictModel):
    schema_version: str = SCHEMA_VERSION
    target_id: str
    database_path: str
    hits: list[HomologHit]
    counts: dict[str, int]
    diversity: DiversitySummary
    provenance: ProvenanceRecord


class AlignmentSequence(StrictModel):
    id: str
    description: str
    gap_count: int


class AlignmentArtifact(StrictModel):
    schema_version: str = SCHEMA_VERSION
    n_sequences: int
    alignment_length: int
    sequences: list[AlignmentSequence]
    target_row_id: str
    provenance: ProvenanceRecord


class ConservationColumn(StrictModel):
    column: int
    n_sequences: int
    gap_count: int
    gap_fraction: float
    entropy: float | None
    max_entropy: float
    conservation: float | None
    coverage_adjusted_conservation: float | None
    most_common_residue: str | None
    most_common_frequency: float | None
    target_position: int | None
    target_residue: str | None
    informative: bool


class TopConservedPosition(StrictModel):
    target_position: int
    target_residue: str
    conservation: float
    entropy: float
    gap_fraction: float


class ConservationSummary(StrictModel):
    mean_conservation: float | None
    median_conservation: float | None
    informative_columns: int
    high_gap_columns: int


class ConservationArtifact(StrictModel):
    schema_version: str = SCHEMA_VERSION
    target_id: str
    columns: list[ConservationColumn]
    top_conserved_positions: list[TopConservedPosition]
    summary: ConservationSummary
    provenance: ProvenanceRecord | None = None


class StageArtifact(StrictModel):
    stage: str
    status: Literal["COMPLETED", "FAILED"]
    artifact_paths: list[str]
    provenance: list[ProvenanceRecord]


class RunArtifact(StrictModel):
    schema_version: str = SCHEMA_VERSION
    pipeline_version: str
    run_id: str
    started_at: datetime
    ended_at: datetime
    input_files: list[FileDigest]
    stages: list[StageArtifact]
    environment: dict[str, Any]
    limitations: list[str]
