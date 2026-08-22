from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from backend.app.artifacts import job_dir
from backend.app.capabilities import CapabilitySpec, capability_catalog
from backend.app.models import ResearchCapability

JsonScalar = str | int | float | bool | None


class CapabilityInfo(BaseModel):
    id: ResearchCapability
    title: str
    description: str
    tools: list[str]
    outputs: list[str]


class ResearchTask(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    capability: ResearchCapability
    status: Literal["PLANNED", "RUNNING", "COMPLETED", "FAILED", "BLOCKED", "SKIPPED"]
    methods: list[str] = Field(default_factory=list)
    output_files: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    objective: str = Field(min_length=1)
    strategy: str = Field(min_length=1)
    tasks: list[ResearchTask] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)


class SynthesisFinding(BaseModel):
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    confidence: Literal["HIGH", "MEDIUM", "LOW", "NOT_ASSESSED"]
    evidence_files: list[str] = Field(default_factory=list)
    implications: list[str] = Field(default_factory=list)


class ResearchSynthesis(BaseModel):
    objective: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    findings: list[SynthesisFinding] = Field(default_factory=list)
    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class SimulationMetric(BaseModel):
    name: str = Field(min_length=1)
    value: JsonScalar
    unit: str | None = None
    interpretation: str = Field(min_length=1)


class SimulationRun(BaseModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    method: str = Field(min_length=1)
    engine: str = Field(min_length=1)
    status: Literal["COMPLETED", "FAILED", "BLOCKED", "SKIPPED"]
    input_files: list[str] = Field(default_factory=list)
    parameters: dict[str, JsonScalar] = Field(default_factory=dict)
    metrics: list[SimulationMetric] = Field(default_factory=list)
    output_files: list[str] = Field(default_factory=list)
    interpretation: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


class SimulationResults(BaseModel):
    objective: str = Field(min_length=1)
    runs: list[SimulationRun] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    recommended_next_steps: list[str] = Field(default_factory=list)


class ResearchWorkspace(BaseModel):
    capabilities: list[CapabilityInfo]
    plan: ResearchPlan | None = None
    synthesis: ResearchSynthesis | None = None
    simulations: SimulationResults | None = None
    validation_errors: dict[str, str] = Field(default_factory=dict)


def catalog_response() -> list[CapabilityInfo]:
    return [_capability_info(spec) for spec in capability_catalog()]


def load_workspace(
    job_id: str,
    capabilities: list[ResearchCapability],
) -> ResearchWorkspace:
    directory = job_dir(job_id)
    errors: dict[str, str] = {}
    plan = _load(directory / "research_plan.json", ResearchPlan, errors)
    synthesis = _load(directory / "synthesis.json", ResearchSynthesis, errors)
    simulations = _load(directory / "simulation_results.json", SimulationResults, errors)
    selected = [spec for spec in capability_catalog() if spec.id in capabilities]
    return ResearchWorkspace(
        capabilities=[_capability_info(spec) for spec in selected],
        plan=plan,
        synthesis=synthesis,
        simulations=simulations,
        validation_errors=errors,
    )


def _capability_info(spec: CapabilitySpec) -> CapabilityInfo:
    return CapabilityInfo(
        id=spec.id,
        title=spec.title,
        description=spec.description,
        tools=list(spec.tools),
        outputs=list(spec.outputs),
    )


def _load[ModelT: BaseModel](
    path: Path,
    model_type: type[ModelT],
    errors: dict[str, str],
) -> ModelT | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return model_type.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        errors[path.name] = str(error)
        return None
