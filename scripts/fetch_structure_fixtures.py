#!/usr/bin/env python3
"""Fetch pinned RCSB PDB fixtures and their metadata manifest."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRUCTURES = ROOT / "fixtures" / "structures"
PDB_IDS = ("6EQE", "5XJH", "4CG1", "1JFR", "1CEX", "1UBQ")


def main() -> None:
    STRUCTURES.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(timezone.utc).isoformat()
    manifest: list[dict[str, object]] = []
    for pdb_id in PDB_IDS:
        url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        compressed = gzip.compress(data, mtime=0)
        path = STRUCTURES / f"{pdb_id}.pdb.gz"
        path.write_bytes(compressed)
        text = data.decode("utf-8", errors="replace")
        method = _first_record(text, "EXPDTA") or "Unknown"
        resolution_match = re.search(r"REMARK\s+2 RESOLUTION\.\s+([0-9.]+)\s+ANGSTROMS", text)
        chains = "A,B" if pdb_id == "1JFR" else "A"
        manifest.append(
            {
                "pdb_id": pdb_id,
                "title": " ".join(_records(text, "TITLE")),
                "experimental_method": method,
                "resolution": float(resolution_match.group(1)) if resolution_match else None,
                "chain": chains,
                "source_url": url,
                "retrieval_date": retrieved,
                "sha256_uncompressed": hashlib.sha256(data).hexdigest(),
                "sha256_gz": hashlib.sha256(compressed).hexdigest(),
                "evidence_type": "KNOWN",
                "license": "RCSB PDB data license CC0 1.0",
            }
        )
    (STRUCTURES / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _records(text: str, record_name: str) -> list[str]:
    values = []
    for line in text.splitlines():
        if line.startswith(record_name):
            values.append(line[10:].strip())
    return values


def _first_record(text: str, record_name: str) -> str | None:
    values = _records(text, record_name)
    return values[0] if values else None


if __name__ == "__main__":
    main()
