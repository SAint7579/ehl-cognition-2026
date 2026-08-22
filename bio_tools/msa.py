"""MAFFT multiple sequence alignment stage."""

from __future__ import annotations

import os
from pathlib import Path

from Bio import AlignIO
from Bio import SeqIO

from .models import AlignmentArtifact, AlignmentSequence
from .provenance import run_tool


def run_msa(
    homologs_path: Path | str,
    alignment_path: Path | str,
    threads: int | None = None,
) -> AlignmentArtifact:
    homologs_path = Path(homologs_path)
    alignment_path = Path(alignment_path)
    records = list(SeqIO.parse(str(homologs_path), "fasta"))
    if len(records) < 2:
        raise ValueError("MAFFT requires at least 2 sequences; homolog FASTA has fewer")
    alignment_path.parent.mkdir(parents=True, exist_ok=True)
    thread_count = threads or min(4, os.cpu_count() or 1)
    argv = ["mafft", "--auto", "--anysymbol", "--thread", str(thread_count), str(homologs_path)]
    provenance = run_tool(
        "msa",
        "mafft",
        argv,
        {"auto": True, "anysymbol": True, "threads": thread_count},
        [homologs_path],
        [alignment_path],
        stdout_path=alignment_path,
    )
    if provenance.exit_code != 0:
        raise RuntimeError(f"mafft alignment failed: {provenance.stderr.strip()}")
    alignment = AlignIO.read(str(alignment_path), "fasta")
    target_row_id = records[0].id
    artifact = AlignmentArtifact(
        n_sequences=len(alignment),
        alignment_length=alignment.get_alignment_length(),
        sequences=[
            AlignmentSequence(
                id=record.id,
                description=record.description[len(record.id) :].strip(),
                gap_count=str(record.seq).count("-"),
            )
            for record in alignment
        ],
        target_row_id=target_row_id,
        provenance=provenance,
    )
    return artifact
