from __future__ import annotations

import mimetypes
from pathlib import Path

from backend.app.models import ArtifactInfo
from backend.app.settings import settings

ARTIFACT_FILES = (
    "homolog_search.json",
    "homologs.fasta",
    "alignment.json",
    "alignment.fasta",
    "conservation.json",
    "run.json",
    "structure_summary.json",
    "residue_annotations.json",
)


def job_dir(job_id: str) -> Path:
    return settings.runs_dir / job_id


def list_artifacts(job_id: str) -> list[ArtifactInfo]:
    directory = job_dir(job_id)
    found: list[ArtifactInfo] = []
    for name in ARTIFACT_FILES:
        path = directory / name
        if path.is_file():
            media = mimetypes.guess_type(name)[0] or (
                "application/json" if name.endswith(".json") else "text/plain"
            )
            found.append(
                ArtifactInfo(
                    id=f"art_{path.stem}",
                    filename=name,
                    media_type=media,
                    bytes=path.stat().st_size,
                )
            )
    return found


def artifact_path(job_id: str, filename: str) -> Path | None:
    if filename not in ARTIFACT_FILES or "/" in filename or "\\" in filename:
        return None
    path = job_dir(job_id) / filename
    return path if path.is_file() else None
