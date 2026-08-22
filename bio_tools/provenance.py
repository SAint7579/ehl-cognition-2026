"""Subprocess execution with reproducible file and tool provenance."""

from __future__ import annotations

import hashlib
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, TypeVar, cast

from pydantic import BaseModel

from .models import FileDigest, ProvenanceRecord
from .versions import tool_version

OUTPUT_CAP = 8192
ModelT = TypeVar("ModelT", bound=BaseModel)


def file_digest(path: Path | str) -> FileDigest:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return FileDigest(path=str(path), sha256=digest.hexdigest(), bytes=path.stat().st_size)


def run_tool(
    stage: str,
    tool: str,
    argv: Sequence[str],
    parameters: dict[str, object],
    input_files: Sequence[Path | str],
    output_files: Sequence[Path | str],
    evidence_type: str = "CALCULATED",
    stdout_path: Path | str | None = None,
) -> ProvenanceRecord:
    started = datetime.now(timezone.utc)
    start_clock = time.perf_counter()
    if stdout_path is None:
        completed = subprocess.run(list(argv), capture_output=True, text=True, check=False)
    else:
        with Path(stdout_path).open("w", encoding="utf-8") as stdout_handle:
            completed = subprocess.run(
                list(argv),
                stdout=stdout_handle,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
    ended = datetime.now(timezone.utc)
    return ProvenanceRecord(
        stage=stage,
        tool_name=tool,
        tool_version=tool_version(tool),
        argv=list(argv),
        parameters=parameters,
        input_files=[file_digest(path) for path in input_files],
        output_files=[file_digest(path) for path in output_files if Path(path).exists()],
        started_at=started,
        ended_at=ended,
        duration_seconds=time.perf_counter() - start_clock,
        exit_code=completed.returncode,
        evidence_type=evidence_type,
        stdout=(completed.stdout or "")[-OUTPUT_CAP:],
        stderr=(completed.stderr or "")[-OUTPUT_CAP:],
    )


def write_json_model(path: Path | str, model: ModelT) -> ModelT:
    """Write a validated model and finalize an in-process output digest."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    provenance = getattr(model, "provenance", None)
    if isinstance(provenance, ProvenanceRecord) and not provenance.output_files:
        finalized = provenance.model_copy(update={"output_files": [file_digest(path)]})
        model = cast(ModelT, model.model_copy(update={"provenance": finalized}))
        path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return model
