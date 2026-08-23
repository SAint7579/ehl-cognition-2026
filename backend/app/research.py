from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.app.artifacts import job_dir
from backend.app.capabilities import CapabilitySpec, artifact_descriptor, capability_catalog
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

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        aliases = {
            "PENDING": "PLANNED",
            "IN_PROGRESS": "RUNNING",
        }
        if isinstance(value, str):
            return aliases.get(value.upper(), value.upper())
        return value


class ResearchPlan(BaseModel):
    objective: str = Field(min_length=1)
    strategy: str = Field(min_length=1)
    tasks: list[ResearchTask] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)

    @field_validator("strategy", mode="before")
    @classmethod
    def normalize_strategy(cls, value: object) -> object:
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return "\n".join(value)
        return value

    @field_validator("required_inputs", mode="before")
    @classmethod
    def normalize_required_inputs(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        for item in value:
            if isinstance(item, str):
                normalized.append(item)
                continue
            if not isinstance(item, dict):
                return value
            name = item.get("name")
            status = item.get("status")
            if not isinstance(name, str):
                return value
            normalized.append(f"{name} ({status})" if isinstance(status, str) else name)
        return normalized


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
    plan_filename: str | None = None
    synthesis: ResearchSynthesis | None = None
    synthesis_filename: str | None = None
    simulations: SimulationResults | None = None
    simulations_filename: str | None = None
    validation_errors: dict[str, str] = Field(default_factory=dict)


def catalog_response() -> list[CapabilityInfo]:
    return [_capability_info(spec) for spec in capability_catalog()]


def load_workspace(
    job_id: str,
    capabilities: list[ResearchCapability],
    objective: str = "",
) -> ResearchWorkspace:
    directory = job_dir(job_id)
    errors: dict[str, str] = {}
    plan, plan_filename = _load_first(
        _artifact_candidates(directory, "plan", ("research_plan.json",)),
        ResearchPlan,
        errors,
    )
    synthesis, synthesis_filename = _load_synthesis(directory, errors, objective)
    simulations, simulations_filename = _load_first(
        _artifact_candidates(directory, "simulation", ("simulation_results.json",)),
        SimulationResults,
        errors,
    )
    selected = [spec for spec in capability_catalog() if spec.id in capabilities]
    return ResearchWorkspace(
        capabilities=[_capability_info(spec) for spec in selected],
        plan=plan,
        plan_filename=plan_filename,
        synthesis=synthesis,
        synthesis_filename=synthesis_filename,
        simulations=simulations,
        simulations_filename=simulations_filename,
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


def _load_first[ModelT: BaseModel](
    paths: list[Path],
    model_type: type[ModelT],
    errors: dict[str, str],
) -> tuple[ModelT | None, str | None]:
    for path in paths:
        value = _load(path, model_type, errors)
        if value is not None:
            return value, path.name
    return None, None


def _load_synthesis(
    directory: Path,
    errors: dict[str, str],
    objective: str,
) -> tuple[ResearchSynthesis | None, str | None]:
    for path in _artifact_candidates(directory, "synthesis", ("synthesis.json",)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            normalized = _normalize_synthesis(payload, objective)
            return ResearchSynthesis.model_validate(normalized), path.name
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            errors[path.name] = str(error)
    return None, None


def _artifact_candidates(
    directory: Path,
    stage: str,
    preferred: tuple[str, ...],
) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".json"
        and artifact_descriptor(path.name).stage == stage
    ]
    rank = {name: index for index, name in enumerate(preferred)}
    return sorted(files, key=lambda path: (rank.get(path.name, len(rank)), path.name.lower()))


def _normalize_synthesis(payload: object, objective: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("A synthesis artifact must contain a JSON object.")
    normalized: dict[str, object] = dict(payload)
    if not isinstance(normalized.get("objective"), str) or not str(normalized["objective"]).strip():
        normalized["objective"] = objective or "Research investigation"
    if not isinstance(normalized.get("summary"), str) or not str(normalized["summary"]).strip():
        summary = _first_string(
            normalized,
            ("synthesis_summary", "executive_summary", "final_summary", "conclusion"),
        )
        if summary:
            normalized["summary"] = summary
    findings = normalized.get("findings")
    if isinstance(findings, list):
        normalized["findings"] = [
            _normalize_finding(item, index)
            for index, item in enumerate(findings)
        ]
    aliases = {
        "knowledge_gaps": ("gaps", "open_questions"),
        "recommended_next_steps": ("next_steps", "recommendations"),
        "disagreements": ("conflicts", "counter_evidence"),
        "agreements": ("evidence_agreements",),
    }
    for target, sources in aliases.items():
        if target not in normalized:
            value = _first_list(normalized, sources)
            if value is not None:
                normalized[target] = value
    return normalized


def _normalize_finding(value: object, index: int) -> object:
    if isinstance(value, str):
        return {
            "title": f"Finding {index + 1}",
            "statement": value,
            "confidence": "NOT_ASSESSED",
        }
    if not isinstance(value, dict):
        return value
    finding: dict[str, object] = dict(value)
    statement = _first_string(finding, ("statement", "finding", "result", "conclusion"))
    if statement and "statement" not in finding:
        finding["statement"] = statement
    if not isinstance(finding.get("title"), str) or not str(finding["title"]).strip():
        finding["title"] = f"Finding {index + 1}"
    confidence = finding.get("confidence")
    finding["confidence"] = (
        confidence.upper()
        if isinstance(confidence, str)
        else "NOT_ASSESSED"
    )
    if "evidence_files" not in finding:
        evidence = _first_list(finding, ("evidence", "sources", "artifacts"))
        if evidence is not None and all(isinstance(item, str) for item in evidence):
            finding["evidence_files"] = evidence
    if "implications" not in finding:
        implications = _first_list(finding, ("why_it_matters", "impact"))
        if implications is not None:
            finding["implications"] = implications
    return finding


def _first_string(payload: dict[str, object], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _first_list(payload: dict[str, object], names: tuple[str, ...]) -> list[object] | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, list):
            return value
    return None
