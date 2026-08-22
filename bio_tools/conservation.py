"""Pure Python/NumPy conservation analysis of a protein MSA."""

from __future__ import annotations

import math
import statistics
from pathlib import Path

import numpy as np
from Bio import AlignIO

from .models import (
    ConservationArtifact,
    ConservationColumn,
    ConservationSummary,
    TopConservedPosition,
)

MAX_ENTROPY = math.log2(20)


def analyze_alignment(
    alignment_path: Path | str,
    target_id: str,
) -> ConservationArtifact:
    alignment = AlignIO.read(str(alignment_path), "fasta")
    records = list(alignment)
    target = next((record for record in records if record.id == target_id), None)
    if target is None:
        raise ValueError(f"target row id {target_id!r} not found in alignment")
    matrix = np.array([list(str(record.seq).upper()) for record in records])
    target_sequence = matrix[records.index(target)]
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
    informative_values = [item.conservation for item in columns if item.informative]
    top = sorted(
        (
            item
            for item in columns
            if item.informative
            and item.target_position is not None
            and item.gap_fraction <= 0.5
        ),
        key=lambda item: (-item.conservation, item.gap_fraction, item.column),  # type: ignore[operator]
    )[:20]
    return ConservationArtifact(
        target_id=target_id,
        columns=columns,
        top_conserved_positions=[
            TopConservedPosition(
                target_position=item.target_position,  # type: ignore[arg-type]
                target_residue=item.target_residue,  # type: ignore[arg-type]
                conservation=item.conservation,  # type: ignore[arg-type]
                entropy=item.entropy,  # type: ignore[arg-type]
                gap_fraction=item.gap_fraction,
            )
            for item in top
        ],
        summary=ConservationSummary(
            mean_conservation=statistics.mean(informative_values) if informative_values else None,
            median_conservation=statistics.median(informative_values) if informative_values else None,
            informative_columns=len(informative_values),
            high_gap_columns=sum(item.gap_fraction > 0.5 for item in columns),
        ),
    )
