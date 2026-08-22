#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
if [[ -z "${DEVIN_API_KEY:-}" || -z "${DEVIN_ORG_ID:-}" ]]; then
  echo "DEVIN_API_KEY and DEVIN_ORG_ID are required. Science will not run on this Mac." >&2
  exit 1
fi
if [[ -z "${DEVIN_SNAPSHOT_ID:-}" ]]; then
  echo "Warning: DEVIN_SNAPSHOT_ID is unset. Use a Linux snapshot with the CPU toolchain." >&2
fi
echo "API: http://127.0.0.1:8000  UI: http://127.0.0.1:5173  runtime: Devin sandbox"
python -m uvicorn backend.app.main:app --reload --port 8000
