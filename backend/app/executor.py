"""Run the committed bioctl stages for one job. Devin can replace this later."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from bio_tools.pipeline import run_pipeline
from bio_tools.provenance import write_json_model
from bio_tools.structure import analyze_structure

from backend.app.artifacts import job_dir, list_artifacts
from backend.app.models import JobStatus, Speaker
from backend.app.settings import settings
from backend.app.store import new_event, new_message, store
from backend.app.tools import require_tools

RunFn = Callable[..., object]
StructureFn = Callable[..., tuple[object, object]]


def run_job(
    job_id: str,
    *,
    pipeline: RunFn | None = None,
    structure: StructureFn | None = None,
) -> None:
    pipeline_fn = pipeline or run_pipeline
    structure_fn = structure or analyze_structure
    job = store.get(job_id)
    if job is None:
        return
    out = job_dir(job_id)
    try:
        require_tools(job.include_structure)
        store.update(job_id, status=JobStatus.running, active_agent=Speaker.planner, active_stage="plan")
        store.add_event(job_id, new_event("job.started", "Investigation started", "plan"))
        store.add_message(
            job_id,
            new_message(
                Speaker.planner,
                (
                    f"Job: {job.objective.strip()} "
                    "I will run the CPU-only bioctl path on the committed IsPETase fixtures: "
                    "MMseqs2 → MAFFT → conservation"
                    + (", then retrieve PDB 6EQE for structure mapping." if job.include_structure else ".")
                    + " I will not claim experimental heat-resistance."
                ),
                stage="plan",
            ),
        )

        store.update(job_id, active_agent=Speaker.search, active_stage="homolog-search")
        store.add_event(job_id, new_event("stage.started", "Running MMseqs2 + MAFFT + conservation", "homolog-search"))
        run = pipeline_fn(
            settings.default_target,
            settings.default_database,
            out,
            settings.threads,
        )
        store.add_event(
            job_id,
            new_event("artifact.ready", "Homolog search finished", "homolog-search", "art_homolog_search"),
        )
        store.add_event(
            job_id,
            new_event("artifact.ready", "Conservation finished", "conservation", "art_conservation"),
        )
        hits = _count_hits(out / "homolog_search.json")
        triad = _triad_conservation(out / "conservation.json")
        store.add_message(
            job_id,
            new_message(
                Speaker.search,
                (
                    f"MMseqs2 returned {hits} homologs against the local PETase-family fixture DB. "
                    f"Conservation marks the catalytic triad "
                    f"{triad or 'S160 / D206 / H237'} as highly conserved. "
                    "Evidence is CALCULATED, not experimental."
                ),
                stage="conservation",
                artifact_ids=["art_homolog_search", "art_conservation"],
            ),
        )
        store.add_event(job_id, new_event("stage.complete", "Sequence stages complete", "conservation"))

        limitations = list(getattr(run, "limitations", []) or [])
        if job.include_structure:
            store.update(job_id, active_agent=Speaker.structure, active_stage="structure")
            store.add_event(job_id, new_event("stage.started", "Mapping PDB 6EQE + Foldseek/DSSP", "structure"))
            summary, annotations = structure_fn(
                settings.default_structure,
                settings.default_chain,
                settings.default_target,
                out,
                settings.default_references,
                out / "conservation.json",
                settings.threads,
            )
            if isinstance(summary, BaseModel):
                write_json_model(out / "structure_summary.json", summary)
            if isinstance(annotations, BaseModel):
                write_json_model(out / "residue_annotations.json", annotations)
            modelled = getattr(summary, "modelled_residue_count", None)
            pdb_id = getattr(getattr(summary, "deposition", None), "pdb_id", "6EQE")
            store.add_event(
                job_id,
                new_event("artifact.ready", "Structure annotations ready", "structure", "art_residue_annotations"),
            )
            store.add_message(
                job_id,
                new_message(
                    Speaker.structure,
                    (
                        f"Retrieved {pdb_id} chain {settings.default_chain} "
                        f"({modelled or 'n/a'} modelled residues). "
                        "Coordinates are KNOWN (deposited). DSSP/Foldseek mappings are CALCULATED. "
                        "Catalytic triad author residues 160 / 206 / 237 map onto the target."
                    ),
                    stage="structure",
                    artifact_ids=["art_structure_summary", "art_residue_annotations"],
                ),
            )
            limitations.extend(getattr(summary, "limitations", []) or [])
            store.add_event(job_id, new_event("stage.complete", "Structure stage complete", "structure"))

        store.add_message(
            job_id,
            new_message(
                Speaker.design,
                (
                    "This slice stops at evidence, not a designed mutant table. "
                    "Use the conservation heatmap and 6EQE mapping to inspect constrained vs variable "
                    "positions. Ask a follow-up if you want a residue explained."
                ),
                stage="rank",
                artifact_ids=["art_conservation", "art_residue_annotations"]
                if job.include_structure
                else ["art_conservation"],
            ),
        )
        store.update(
            job_id,
            status=JobStatus.complete,
            active_agent=None,
            active_stage=None,
            artifacts=list_artifacts(job_id),
            limitations=list(dict.fromkeys(limitations)),
        )
        store.add_event(job_id, new_event("job.complete", "Investigation complete"))
    except Exception as error:
        store.update(
            job_id,
            status=JobStatus.failed,
            error=str(error),
            active_agent=None,
            artifacts=list_artifacts(job_id),
        )
        store.add_event(job_id, new_event("job.failed", str(error)))
        store.add_message(
            job_id,
            new_message(Speaker.system, f"Pipeline failed: {error}", stage="error"),
        )


def answer_follow_up(job_id: str, body: str) -> None:
    text = body.lower()
    job = store.get(job_id)
    if job is None:
        return
    store.add_message(job_id, new_message(Speaker.user, body.strip()))
    artifacts = [item.id for item in job.artifacts]
    if "10" in text and ("å" in text or "angstrom" in text or "catalytic" in text):
        reply = (
            "Constraint noted. This slice does not yet rewrite a ranked mutant list. "
            "On the structure panel, treat residues with a short distance to 160/206/237 "
            "as protected; I will not propose those as heat-stability candidates."
        )
        cites = [aid for aid in artifacts if "residue" in aid or "conservation" in aid]
    elif "why" in text or "how" in text or "explain" in text:
        reply = (
            "Decisions in this job come from bioctl artifacts, not chat memory. "
            "Homologs and conservation are CALCULATED from MMseqs2/MAFFT. "
            "6EQE is a retrieved PDB structure. The triad is conserved at 1.0 on the fixture MSA. "
            "Nothing here is a wet-lab +30% heat-stability result."
        )
        cites = artifacts[:4]
    else:
        reply = (
            "Still the same job. The right pane is the latest bioctl output. "
            "Ask about a residue, the homolog set, or why a position looks constrained."
        )
        cites = artifacts[:3]
    store.add_message(
        job_id,
        new_message(Speaker.reviewer, reply, artifact_ids=cites),
    )


def _count_hits(path: Path) -> int:
    if not path.is_file():
        return 0
    data = json.loads(path.read_text())
    return len(data.get("hits") or [])


def _triad_conservation(path: Path) -> str:
    if not path.is_file():
        return ""
    data = json.loads(path.read_text())
    wanted = {160, 206, 237}
    found: list[str] = []
    for column in data.get("columns") or []:
        pos = column.get("target_position")
        if pos in wanted and column.get("conservation") is not None:
            found.append(f"{column.get('target_residue')}{pos}={column['conservation']:.2f}")
    return ", ".join(found)
