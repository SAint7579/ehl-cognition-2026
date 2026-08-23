from __future__ import annotations

import gzip
import json
import mimetypes
import re
from pathlib import Path

from backend.app.capabilities import artifact_descriptor
from backend.app.models import ArtifactInfo
from backend.app.settings import settings

NAMED_ARTIFACTS = (
    "protocol.md",
    "research_plan.json",
    "literature_sources.csv",
    "synthesis.json",
    "simulation_results.json",
    "simulation_metrics.csv",
    "analysis_results.json",
    "analysis_table.csv",
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
# Keep the old name so harvest/import keep working.
ARTIFACT_FILES = NAMED_ARTIFACTS

ALLOWED_EXTENSIONS = {
    ".json",
    ".fasta",
    ".fa",
    ".pdb",
    ".cif",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".csv",
    ".tsv",
    ".md",
    ".txt",
}
SKIP_NAMES = {"job.json"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,78}$")
MAX_LISTED = 40
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
TABLE_EXTENSIONS = {".csv", ".tsv"}
STRUCTURE_EXTENSIONS = {".pdb", ".cif"}


def job_dir(job_id: str) -> Path:
    return settings.runs_dir / job_id


def is_allowed_artifact(filename: str) -> bool:
    name = Path(filename).name
    if name != filename or name in SKIP_NAMES or "/" in filename or "\\" in filename:
        return False
    if not SAFE_NAME.match(name):
        return False
    if name in NAMED_ARTIFACTS:
        return True
    return Path(name).suffix.lower() in ALLOWED_EXTENSIONS


def ensure_structure_pdb(job_id: str) -> Path | None:
    """Serve coordinates Devin attached. Fall back to 6EQE only when this job used it."""
    dest = preferred_structure(job_id)
    if dest is not None:
        return dest
    dest = job_dir(job_id) / "structure.pdb"
    if not _job_used_6eqe(job_id):
        return None
    source = settings.default_structure
    if not source.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.name.endswith(".gz"):
        dest.write_bytes(gzip.decompress(source.read_bytes()))
    else:
        dest.write_bytes(source.read_bytes())
    return dest if dest.is_file() else None


def preferred_structure(job_id: str) -> Path | None:
    directory = job_dir(job_id)
    preferred = directory / "structure.pdb"
    if preferred.is_file() and preferred.stat().st_size > 0:
        return preferred
    extras = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in STRUCTURE_EXTENSIONS and is_allowed_artifact(path.name)
    ) if directory.is_dir() else []
    return extras[0] if extras else None


def _job_used_6eqe(job_id: str) -> bool:
    summary = job_dir(job_id) / "structure_summary.json"
    if not summary.is_file():
        return False
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    deposition = data.get("deposition") if isinstance(data.get("deposition"), dict) else {}
    pdb_id = str(deposition.get("pdb_id") or data.get("structure_id") or "").upper()
    return pdb_id == "6EQE"


def list_artifacts(job_id: str) -> list[ArtifactInfo]:
    directory = job_dir(job_id)
    if (directory / "structure_summary.json").is_file() or (directory / "final_result.json").is_file():
        ensure_structure_pdb(job_id)
    if not directory.is_dir():
        return []
    found: list[ArtifactInfo] = []
    seen: set[str] = set()
    for path in _ordered_paths(directory):
        if path.name in seen or not is_allowed_artifact(path.name):
            continue
        seen.add(path.name)
        descriptor = artifact_descriptor(path.name)
        found.append(
            ArtifactInfo(
                id=f"art_{path.stem}",
                filename=path.name,
                media_type=media_type(path.name),
                bytes=path.stat().st_size,
                stage=descriptor.stage,
                title=descriptor.title,
                purpose=descriptor.purpose,
            )
        )
        if len(found) >= MAX_LISTED:
            break
    return found


def _ordered_paths(directory: Path) -> list[Path]:
    files = [path for path in directory.iterdir() if path.is_file()]
    rank = {name: index for index, name in enumerate(NAMED_ARTIFACTS)}

    def key(path: Path) -> tuple[int, str]:
        suffix = path.suffix.lower()
        if path.name in rank:
            return (0, f"{rank[path.name]:02d}")
        if suffix in IMAGE_EXTENSIONS:
            return (1, path.name.lower())
        if suffix in STRUCTURE_EXTENSIONS:
            return (2, path.name.lower())
        if suffix in TABLE_EXTENSIONS:
            return (3, path.name.lower())
        return (4, path.name.lower())

    return sorted(files, key=key)


def artifact_path(job_id: str, filename: str) -> Path | None:
    if not is_allowed_artifact(filename):
        return None
    path = job_dir(job_id) / Path(filename).name
    return path if path.is_file() else None


def media_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    explicit = {
        ".pdb": "chemical/x-pdb",
        ".cif": "chemical/x-cif",
        ".fasta": "chemical/x-fasta",
        ".fa": "chemical/x-fasta",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }
    return explicit.get(suffix) or mimetypes.guess_type(name)[0] or "application/octet-stream"
