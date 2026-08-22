#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/runs/structure_smoke"
SEQUENCE_OUT="${OUT}/sequence"
cd "${ROOT}"
rm -rf "${OUT}"

"${ROOT}/.venv/bin/python" -m bio_tools.cli run \
  --target "${ROOT}/fixtures/target_ispetase.fasta" \
  --database "${ROOT}/fixtures/homolog_db.fasta" \
  --out "${SEQUENCE_OUT}" \
  --threads 1
"${ROOT}/.venv/bin/python" -m bio_tools.cli structure \
  --structure "${ROOT}/fixtures/structures/6EQE.pdb.gz" \
  --chain A \
  --target "${ROOT}/fixtures/target_ispetase.fasta" \
  --conservation "${SEQUENCE_OUT}/conservation.json" \
  --references "${ROOT}/fixtures/structures" \
  --out "${OUT}" \
  --threads 1

"${ROOT}/.venv/bin/python" - "${OUT}" "${SEQUENCE_OUT}" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
sequence = Path(sys.argv[2])
summary = json.loads((out / "structure_summary.json").read_text())
conservation = json.loads((sequence / "conservation.json").read_text())
by_position = {item["target_position"]: item for item in conservation["columns"]}
print(f"modelled residues: {summary['modelled_residue_count']}")
print(f"unmodelled target ranges: {summary['unmodelled_target_ranges']}")
print(f"secondary structure (3-state): {summary['secondary_structure']['counts_3state']}")
top = summary["foldseek_hits"][0]
print(f"top Foldseek hit: {top['target']} (TM-score: {top['alignment_tm_score']})")
print("triad: author_residue -> target_position -> msa_column -> conservation")
annotations = json.loads((out / "residue_annotations.json").read_text())["annotations"]
for author_residue in (160, 206, 237):
    item = next(row for row in annotations if row["author_residue"] == author_residue)
    column = by_position[item["target_position"]]
    print(
        f"{author_residue} -> {item['target_position']} -> "
        f"{column['column']} -> {column['conservation']}"
    )
PY
