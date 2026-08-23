from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    complete = "complete"
    failed = "failed"


class Speaker(str, Enum):
    user = "user"
    planner = "planner"
    search = "search"
    structure = "structure"
    design = "design"
    reviewer = "reviewer"
    system = "system"


class ResearchCapability(str, Enum):
    literature_search = "literature-search"
    research_synthesis = "research-synthesis"
    sequence_analysis = "sequence-analysis"
    structure_analysis = "structure-analysis"
    molecular_simulation = "molecular-simulation"
    candidate_ranking = "candidate-ranking"
    data_analysis = "data-analysis"


class JobCreate(BaseModel):
    objective: str = Field(min_length=3, max_length=4000)
    title: str | None = None
    include_structure: bool = True
    devin_session_id: str | None = Field(default=None, max_length=400)
    capabilities: list[ResearchCapability] = Field(default_factory=list)


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class Message(BaseModel):
    id: str
    speaker: Speaker
    body: str
    stage: str | None = None
    source_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class Event(BaseModel):
    id: int
    type: Literal[
        "job.started",
        "stage.started",
        "stage.complete",
        "artifact.ready",
        "agent.message",
        "agent.error",
        "job.complete",
        "job.failed",
    ]
    stage: str | None = None
    message: str
    artifact_id: str | None = None
    created_at: datetime


class ArtifactInfo(BaseModel):
    id: str
    filename: str
    media_type: str
    bytes: int
    stage: str
    title: str
    purpose: str


class Job(BaseModel):
    id: str
    owner_id: str | None = None
    title: str
    objective: str
    playbook: str = "protein-engineering-v1"
    status: JobStatus
    active_agent: Speaker | None = None
    active_stage: str | None = None
    error: str | None = None
    include_structure: bool = True
    capabilities: list[ResearchCapability] = Field(default_factory=list)
    devin_session_id: str | None = None
    session_url: str | None = None
    seen_devin_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
