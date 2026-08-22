"""Pure Python/NumPy conservation analysis of a protein MSA."""

from __future__ import annotations

import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from Bio import AlignIO

from . import __version__
from .models import (
    ConservationArtifact,
    ConservationColumn,
    ConservationSummary,
    ProvenanceRecord,
    TopConservedPosition,
)
from .provenance import file_digest

MAX_ENTROPY = math.log2(20)


def analyze_alignment(
    alignment_path: Path | str,
    target_id: str,
) -> ConservationArtifact:
    alignment_path = Path(alignment_path)
    started = datetime.now(timezone.utc)
    start_clock = time.perf_counter()
    alignment = AlignIO.read(str(alignment_path), "fasta")
    records = list(alignment)
    target_match = next(
        ((index, record) for index, record in enumerate(records) if record.id == target_id),
        None,
    )
    if target_match is None:
        raise ValueError(f"target row id {target_id!r} not found in alignment")
    target_index, target = target_match
    matrix = np.array([list(str(record.seq).upper()) for record in records])
    target_sequence = matrix[target_index]
    target_positions: list[int | None] = []
    residue_position = 0
    for residue in target_sequence:
        if residue != "-":
            residue_position += 1
            target_positions.append(residue_position)
        else:
            target_positions.append(None)
    columns: list[ConservationColumn] = []
    for index, column_values in enumerate(matrix.T):
        gap_count = int(np.count_nonzero(column_values == "-"))
        non_gap = [residue for residue in column_values if residue != "-"]
        gap_fraction = gap_count / len(records)
        target_position = target_positions[index]
        target_residue = None if target_position is None else str(target_sequence[index])
        if len(non_gap) < 2:
            entropy = None
            conservation = None
            most_common = None
            most_common_frequency = None
            informative = False
        else:
            unique, counts = np.unique(np.array(non_gap), return_counts=True)
            probabilities = counts / len(non_gap)
            entropy = float(-np.sum(probabilities * np.log2(probabilities)))
            conservation = max(0.0, min(1.0, 1.0 - entropy / MAX_ENTROPY))
            most_common = sorted(
                zip(unique.tolist(), counts.tolist()),
                key=lambda item: (-item[1], item[0]),
            )[0][0]
            most_common_frequency = float(max(counts) / len(non_gap))
            informative = True
        columns.append(
            ConservationColumn(
                column=index + 1,
                n_sequences=len(records),
                gap_count=gap_count,
                gap_fraction=gap_fraction,
                entropy=entropy,
                max_entropy=MAX_ENTROPY,
                conservation=conservation,
                coverage_adjusted_conservation=(
                    conservation * (1 - gap_fraction) if conservation is not None else None
                ),
                most_common_residue=most_common,
                most_common_frequency=most_common_frequency,
                target_position=target_position,
                target_residue=target_residue,
                informative=informative,
            )
        )
    informative_values = [
        item.conservation for item in columns if item.informative and item.conservation is not None
    ]
    eligible: list[tuple[int, str, float, float, int, float]] = []
    for item in columns:
        if (
            item.informative
            and item.target_position is not None
            and item.target_residue is not None
            and item.conservation is not None
            and item.entropy is not None
            and item.gap_fraction <= 0.5
        ):
            eligible.append(
                (
                    item.target_position,
                    item.target_residue,
                    item.conservation,
                    item.gap_fraction,
                    item.column,
                    item.entropy,
                )
            )
    top = sorted(eligible, key=lambda item: (-item[2], item[3], item[4]))[:20]
    ended = datetime.now(timezone.utc)
    return ConservationArtifact(
        target_id=target_id,
        columns=columns,
        top_conserved_positions=[
            TopConservedPosition(
                target_position=target_position,
                target_residue=target_residue,
                conservation=conservation,
                entropy=entropy,
                gap_fraction=gap_fraction,
            )
            for (
                target_position,
                target_residue,
                conservation,
                gap_fraction,
                _column_number,
                entropy,
            ) in top
        ],
        summary=ConservationSummary(
            mean_conservation=statistics.mean(informative_values) if informative_values else None,
            median_conservation=statistics.median(informative_values) if informative_values else None,
            informative_columns=len(informative_values),
            high_gap_columns=sum(item.gap_fraction > 0.5 for item in columns),
        ),
        provenance=ProvenanceRecord(
            stage="conservation",
            tool_name="bio_tools.conservation",
            tool_version=__version__,
            argv=None,
            parameters={
                "entropy": "Shannon entropy over non-gap residues",
                "entropy_base": 2,
                "max_entropy": MAX_ENTROPY,
                "top_n": 20,
                "gap_fraction_threshold": 0.5,
            },
            input_files=[file_digest(alignment_path)],
            output_files=[],
            started_at=started,
            ended_at=ended,
            duration_seconds=time.perf_counter() - start_clock,
            exit_code=None,
            evidence_type="CALCULATED",
        ),
    )
