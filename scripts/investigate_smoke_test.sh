#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/runs/investigate_smoke"
cd "${ROOT}"
rm -rf "${OUT}"

"${ROOT}/.venv/bin/bioctl" investigate \
  --objective "Identify substrate-cleft and surface engineering sites for IsPETase" \
  --target "${ROOT}/fixtures/target_ispetase.fasta" \
  --database "${ROOT}/fixtures/homolog_db.fasta" \
  --structure "${ROOT}/fixtures/structures/6EQE.pdb.gz" \
  --chain A \
  --references "${ROOT}/fixtures/structures" \
  --out "${OUT}" \
  --constraint exclude_residues=160,206,237,183 \
  --constraint max_mutations=3 \
  --threads 1 \
  --top 5

"${ROOT}/.venv/bin/python" - "${OUT}/final_result.json" <<'PY'
import json
import sys
from pathlib import Path

artifact = json.loads(Path(sys.argv[1]).read_text())
print(f"objective: {artifact['objective']}")
print("constraints:")
print("key value enforcement")
for constraint in artifact["constraints"]:
    print(
        f"{constraint['key']} {constraint['value']} "
        f"{constraint['enforcement']}"
    )
print("stages:")
print("stage status duration_seconds")
for stage in artifact["stages"]:
    print(f"{stage['stage']} {stage['status']} {stage['duration_seconds']}")
for name in ("activity", "stability"):
    shortlist = artifact["shortlists"][name]
    print(
        f"{name} shortlist (top {shortlist['top_n']} "
        f"of {shortlist['n_total']}):"
    )
    print("rank author_residue target_position wild_type conservation rsa distance score substitution_options")
    for site in shortlist["sites"]:
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
print("evidence labels:")
for label, reason in artifact["evidence_labels"].items():
    print(f"{label}: {reason}")
print(
    f"playbook: {artifact['playbook']['id']} "
    f"version {artifact['playbook']['version']} "
    f"digest {artifact['playbook']['digest']['sha256']}"
)
PY
