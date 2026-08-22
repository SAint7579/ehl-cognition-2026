#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/runs/smoke"
cd "${ROOT}"
rm -rf "${OUT}"
"${ROOT}/.venv/bin/python" -m bio_tools.cli run \
  --target "${ROOT}/fixtures/target_ispetase.fasta" \
  --database "${ROOT}/fixtures/homolog_db.fasta" \
  --out "${OUT}"
"${ROOT}/.venv/bin/python" - "${OUT}" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
homologs = json.loads((out / "homolog_search.json").read_text())
alignment = json.loads((out / "alignment.json").read_text())
conservation = json.loads((out / "conservation.json").read_text())
positions = [item["target_position"] for item in conservation["top_conserved_positions"][:10]]
print(f"n hits: {len(homologs['hits'])}")
print(f"alignment length: {alignment['alignment_length']}")
print(f"top conserved target positions: {positions}")
PY
