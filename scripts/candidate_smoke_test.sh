#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/runs/candidate_smoke"
SEQUENCE_OUT="${OUT}/sequence"
STRUCTURE_OUT="${OUT}/structure"
CANDIDATE_OUT="${OUT}/candidates"
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
  --out "${STRUCTURE_OUT}" \
  --threads 1
"${ROOT}/.venv/bin/python" -m bio_tools.cli candidates \
  --annotations "${STRUCTURE_OUT}/residue_annotations.json" \
  --structure "${ROOT}/fixtures/structures/6EQE.pdb.gz" \
  --chain A \
  --alignment "${SEQUENCE_OUT}/alignment.fasta" \
  --out "${CANDIDATE_OUT}" \
  --top 15

"${ROOT}/.venv/bin/python" - "${CANDIDATE_OUT}/candidate_sites.json" <<'PY'
import json
import sys
from pathlib import Path

artifact = json.loads(Path(sys.argv[1]).read_text())
for name in ("activity", "stability"):
    shortlist = artifact["shortlists"][name]
    print(f"{name} shortlist (top {artifact['parameters']['top_n']} of {shortlist['n_sites']}):")
    print("rank author_residue target_position wild_type conservation rsa distance score substitution_options")
    for site in shortlist["sites"][: artifact["parameters"]["top_n"]]:
        options = ",".join(
            f"{item['residue']}({item['count']},{item['frequency']:.3f})"
            for item in site["substitution_options"]
        )
        print(
            f"{site['rank']} {site['author_residue']} {site['target_position']} "
            f"{site['one_letter']} {site['conservation']:.3f} {site['rsa']:.3f} "
            f"{site['distance_to_active_site_angstrom']:.3f} {site['score']:.3f} "
            f"{options}"
        )
PY
