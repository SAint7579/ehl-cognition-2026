#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "API: http://127.0.0.1:8000  UI: http://127.0.0.1:5173"
python -m uvicorn backend.app.main:app --reload --port 8000
