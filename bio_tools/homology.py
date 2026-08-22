"""MMseqs2 homolog search and hit artifact generation.

MMseqs2 reports ``fident`` as a fraction from 0 to 1; artifacts expose it as
``percent_identity`` on the conventional 0-100 scale.
"""

from __future__ import annotations

import os
import shutil
import statistics
from pathlib import Path

from Bio.SeqRecord import SeqRecord

from .fasta_io import accession_from_record, description_without_id, read_fasta, validate_target, write_records
from .models import DiversitySummary, HomologHit, HomologSearchArtifact
from .provenance import run_tool

MMSEQS_PARAMETERS = {
    "sensitivity": 7.5,
    "evalue": 1e-3,
    "max_seqs": 300,
    "format_output": "query,target,fident,alnlen,mismatch,gapopen,qstart,qend,tstart,tend,evalue,bits",
}


def parse_m8(path: Path | str, records: dict[str, SeqRecord]) -> list[HomologHit]:
    hits: list[HomologHit] = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 12:
            raise ValueError(f"invalid MMseqs m8 row {line_number}: expected 12 columns")
        (
            query,
            target,
            fident,
            alnlen,
            _mismatch,
            _gapopen,
            qstart,
            qend,
            tstart,
            tend,
            evalue,
            bits,
        ) = fields
        query_record = records.get(query) or records.get(_accession(query))
        target_record = records.get(target) or records.get(_accession(target))
        if target_record is None:
            continue
        query_length = len(query_record.seq) if query_record is not None else len(target_record.seq)
        hit_length = len(target_record.seq)
        hits.append(
            HomologHit(
                accession=accession_from_record(target_record),
                description=description_without_id(target_record),
                evalue=float(evalue),
                bit_score=float(bits),
                percent_identity=float(fident) * 100,
                alignment_length=int(alnlen),
                query_coverage=(int(qend) - int(qstart) + 1) / query_length,
                target_coverage=(int(tend) - int(tstart) + 1) / hit_length,
            )
        )
    unique: dict[str, HomologHit] = {}
    for hit in sorted(hits, key=lambda item: (item.evalue, item.accession)):
        unique.setdefault(hit.accession, hit)
    return list(unique.values())


def run_homolog_search(
    target_path: Path | str,
    database_path: Path | str,
    out_dir: Path | str,
    threads: int | None = None,
) -> HomologSearchArtifact:
    target_path = Path(target_path)
    database_path = Path(database_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = validate_target(target_path)
    database_records = read_fasta(database_path)
    if not database_records:
        raise ValueError("homolog database FASTA must contain at least one record")
    records = {record.id: record for record in database_records}
    records.update({accession_from_record(record): record for record in database_records})
    target_key = accession_from_record(target)
    records.setdefault(target.id, target)
    records.setdefault(target_key, target)
    thread_count = threads or min(4, os.cpu_count() or 1)
    m8_path = out_dir / "homologs.m8"
    homologs_path = out_dir / "homologs.fasta"
    tmp_dir = out_dir / "mmseqs_tmp"
    tmp_dir.mkdir(exist_ok=True)
    argv = [
        "mmseqs",
        "easy-search",
        str(target_path),
        str(database_path),
        str(m8_path),
        str(tmp_dir),
        "-s",
        str(MMSEQS_PARAMETERS["sensitivity"]),
        "-e",
        str(MMSEQS_PARAMETERS["evalue"]),
        "--max-seqs",
        str(MMSEQS_PARAMETERS["max_seqs"]),
        "--format-output",
        str(MMSEQS_PARAMETERS["format_output"]),
        "--threads",
        str(thread_count),
    ]
    parameters = {**MMSEQS_PARAMETERS, "threads": thread_count}
    provenance = run_tool(
        "homolog-search",
        "mmseqs",
        argv,
        parameters,
        [target_path, database_path],
        [m8_path],
    )
    if provenance.exit_code != 0:
        raise RuntimeError(f"mmseqs homolog search failed: {provenance.stderr.strip()}")
    # Keep the temporary directory on subprocess failure for debugging.
    shutil.rmtree(tmp_dir)
    hits = parse_m8(m8_path, records)
    hit_records = [records[hit.accession] for hit in hits if hit.accession in records]
    target_record = records.get(target_key, target)
    if target_record.id not in {record.id for record in hit_records}:
        hit_records.insert(0, target_record)
    else:
        hit_records = [target_record] + [record for record in hit_records if record.id != target_record.id]
    write_records(hit_records, homologs_path)
    identities = [hit.percent_identity for hit in hits]
    artifact = HomologSearchArtifact(
        target_id=target_record.id,
        database_path=str(database_path.resolve()),
        hits=hits,
        counts={"n_hits": len(hits), "n_sequences_written": len(hit_records)},
        diversity=DiversitySummary(
            n_hits=len(hits),
            min_percent_identity=min(identities) if identities else None,
            median_percent_identity=statistics.median(identities) if identities else None,
            max_percent_identity=max(identities) if identities else None,
        ),
        provenance=provenance,
    )
    return artifact


def _accession(identifier: str) -> str:
    parts = identifier.split("|")
    return parts[1] if len(parts) > 1 else identifier
