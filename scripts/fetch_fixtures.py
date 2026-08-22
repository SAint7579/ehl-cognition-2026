#!/usr/bin/env python3
"""Fetch and manifest the pinned UniProt fixture sequences."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
ACCESSIONS = [
    "A0A0K8P6T7",
    "A0A0K8P8E7",
    "Q6A0I4",
    "G9BY57",
    "D1A9G5",
    "D1A2H1",
    "E9LVH8",
    "P00590",
    "P41365",
    "P37967",
]


def fetch(accession: str) -> str:
    url = f"https://rest.uniprot.org/uniprotkb/{accession}.fasta"
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def main() -> None:
    FIXTURES.mkdir(exist_ok=True)
    entries: list[dict[str, object]] = []
    fetched_at = datetime.now(timezone.utc).date().isoformat()
    target = fetch(ACCESSIONS[0])
    (FIXTURES / "target_ispetase.fasta").write_text(target, encoding="utf-8")
    all_records = [target]
    for accession in ACCESSIONS[1:]:
        all_records.append(fetch(accession))
    (FIXTURES / "homolog_db.fasta").write_text("".join(all_records), encoding="utf-8")
    for fasta in all_records:
        header, *sequence_lines = fasta.strip().splitlines()
        sequence = "".join(sequence_lines)
        match = re.match(r">(\S+)\s*(.*)", header)
        if match is None:
            raise ValueError(f"unexpected FASTA header: {header}")
        identifier, description = match.groups()
        accession = identifier.split("|")[1] if "|" in identifier else identifier
        entry_name = identifier.split("|")[-1]
        sv_match = re.search(r"SV=(\d+)", description)
        entries.append(
            {
                "accession": accession,
                "entry_name": entry_name,
                "protein_name": description.split(" OS=")[0].removeprefix(" ") or entry_name,
                "organism": _field(description, "OS=", " OX="),
                "sequence_version": int(sv_match.group(1)) if sv_match else None,
                "sequence_length": len(sequence),
                "sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "source_url": f"https://rest.uniprot.org/uniprotkb/{accession}.fasta",
                "retrieval_date": fetched_at,
                "evidence_type": "KNOWN",
            }
        )
    (FIXTURES / "MANIFEST.json").write_text(
        json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _field(description: str, start: str, end: str) -> str:
    return description.split(start, 1)[1].split(end, 1)[0].strip()


if __name__ == "__main__":
    main()
