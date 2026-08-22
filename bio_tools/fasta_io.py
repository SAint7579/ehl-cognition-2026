"""FASTA parsing and validation helpers."""

from __future__ import annotations

from pathlib import Path

from Bio import SeqIO
from Bio.SeqRecord import SeqRecord

PROTEIN_ALPHABET = set("ACDEFGHIKLMNPQRSTVWYBXZJUO")


def read_fasta(path: Path | str) -> list[SeqRecord]:
    return list(SeqIO.parse(str(path), "fasta"))


def validate_target(path: Path | str) -> SeqRecord:
    records = read_fasta(path)
    if len(records) != 1:
        raise ValueError(f"target FASTA must contain exactly one record; found {len(records)}")
    record = records[0]
    sequence = str(record.seq).upper()
    if not sequence:
        raise ValueError("target FASTA sequence must be non-empty")
    invalid = sorted(set(sequence) - PROTEIN_ALPHABET)
    if invalid:
        raise ValueError(
            f"target FASTA contains invalid protein residue(s): {', '.join(invalid)}"
        )
    return record


def write_records(records: list[SeqRecord], path: Path | str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    SeqIO.write(records, str(path), "fasta")


def accession_from_record(record: SeqRecord) -> str:
    return record.id.split("|")[1] if "|" in record.id else record.id


def description_without_id(record: SeqRecord) -> str:
    return record.description[len(record.id) :].strip()
