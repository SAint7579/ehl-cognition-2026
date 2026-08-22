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
    argv: list[str] | None = None
    parameters: dict[str, Any]
    input_files: list[FileDigest]
    output_files: list[FileDigest]
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    exit_code: int | None = None
    evidence_type: Literal["KNOWN", "CALCULATED", "PREDICTED", "EXPERIMENTAL"]
    stdout: str = ""
    stderr: str = ""


class HomologHit(StrictModel):
    accession: str
    description: str
    evalue: float
    bit_score: float
    percent_identity: float = Field(
        description="Pairwise identity as a percentage on a 0-100 scale."
    )
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
    provenance: ProvenanceRecord


class StageArtifact(StrictModel):
    stage: str
    status: Literal["COMPLETED", "FAILED"]
    artifact_paths: list[str]
    artifact_digests: list[FileDigest]
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


class StructureWarning(StrictModel):
    code: str
    message: str
    severity: Literal["INFO", "WARNING", "ERROR"]


class StructureDeposition(StrictModel):
    pdb_id: str
    chain: str
    title: str | None
    experimental_method: str | None
    resolution_angstrom: float | None
    evidence_type: Literal["KNOWN"]


class SecondaryStructureComposition(StrictModel):
    counts_8state: dict[str, int]
    fractions_8state: dict[str, float]
    counts_3state: dict[str, int]
    fractions_3state: dict[str, float]
    simplification: str


class FoldseekHit(StrictModel):
    query: str
    target: str
    fident: float = Field(description="Foldseek fractional identity on a 0-1 scale.")
    alignment_length: int
    qstart: int
    qend: int
    tstart: int
    tend: int
    evalue: float
    bits: float
    alignment_tm_score: float
    query_tm_score: float
    target_tm_score: float
    lddt: float
    probability: float
    query_coverage: float
    target_coverage: float
    significant: bool


class NumberingException(StrictModel):
    structure_index: int
    author_residue: int
    insertion_code: str | None
    target_position: int | None
    reason: str


class MappingQuality(StrictModel):
    mapped_positions: int
    identity_fraction: float
    identity_threshold: float


class NumberingSummary(StrictModel):
    author_numbering_matches_target: bool
    exceptions: list[NumberingException]
    mapping_quality: MappingQuality


class ReverseIndexEntry(StrictModel):
    msa_column: int | None
    target_position: int | None
    structure_index: int
    author_residue: int
    insertion_code: str | None


class ResidueAnnotation(StrictModel):
    structure_index: int
    author_residue: int
    insertion_code: str | None
    resname: str
    one_letter: str
    target_position: int | None
    target_residue: str | None
    msa_column: int | None
    conservation: float | None
    gap_fraction: float | None
    entropy: float | None
    dssp_8state: str | None
    secondary_structure: str | None
    acc: float | None
    rsa: float | None
    altloc_present: bool
    evidence_type: Literal["CALCULATED"]


class ResidueAnnotationsArtifact(StrictModel):
    schema_version: str = SCHEMA_VERSION
    structure_id: str
    chain: str
    annotations: list[ResidueAnnotation]
    warnings: list[StructureWarning]
    limitations: list[str]


class StructureSummaryArtifact(StrictModel):
    schema_version: str = SCHEMA_VERSION
    structure_id: str
    chain: str
    deposition: StructureDeposition
    target_id: str
    target_length: int
    residue_counts: dict[str, int]
    modelled_residue_count: int
    modelled_range: str
    unmodelled_target_ranges: list[str]
    secondary_structure: SecondaryStructureComposition
    foldseek_hits: list[FoldseekHit]
    numbering: NumberingSummary
    reverse_index: list[ReverseIndexEntry]
    warnings: list[StructureWarning]
    provenance: list[ProvenanceRecord]
    limitations: list[str]


class CandidateSubstitutionOption(StrictModel):
    residue: str
    count: int
    frequency: float
    source: Literal["observed_in_homologs"]
    evidence_type: Literal["CALCULATED"] = "CALCULATED"


class CandidateSubScores(StrictModel):
    proximity: float
    remoteness: float
    burial: float
    exposure: float
    plasticity: float
    variability: float
    loop: float
    evidence_type: Literal["CALCULATED"] = "CALCULATED"


class CandidateSite(StrictModel):
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
    score: float
    rank: int
    substitution_options: list[CandidateSubstitutionOption]
    evidence_type: Literal["CALCULATED"] = "CALCULATED"


class CandidateShortlist(StrictModel):
    objective: str
    filters: dict[str, str]
    weights: dict[str, float]
    n_sites: int
    sites: list[CandidateSite]
    evidence_type: Literal["CALCULATED"] = "CALCULATED"


class CandidateSitesArtifact(StrictModel):
    schema_version: str = SCHEMA_VERSION
    target_id: str
    provenance: ProvenanceRecord
    parameters: dict[str, Any]
    feature_definitions: dict[str, str]
    score_definitions: dict[str, str]
    shortlists: dict[Literal["activity", "stability"], CandidateShortlist]
    warnings: list[StructureWarning]
    evidence_type: Literal["CALCULATED"] = "CALCULATED"
    limitations: list[str]
