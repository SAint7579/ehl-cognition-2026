from __future__ import annotations

import gzip
import json
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
    "candidate_sites.json",
    "final_result.json",
    "structure.pdb",
)


def job_dir(job_id: str) -> Path:
    return settings.runs_dir / job_id


def ensure_structure_pdb(job_id: str) -> Path | None:
    """Deposited 6EQE for the browser viewer. This is retrieved coordinates, not a fold."""
    dest = job_dir(job_id) / "structure.pdb"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    source = settings.default_structure
    if not source.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.name.endswith(".gz"):
        dest.write_bytes(gzip.decompress(source.read_bytes()))
    else:
        dest.write_bytes(source.read_bytes())
    return dest if dest.is_file() else None


def list_artifacts(job_id: str) -> list[ArtifactInfo]:
    directory = job_dir(job_id)
    if (directory / "structure_summary.json").is_file() or (directory / "final_result.json").is_file():
        ensure_structure_pdb(job_id)
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
