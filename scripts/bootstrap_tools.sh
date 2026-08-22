#!/usr/bin/env bash
# Install local CPU binaries used by bioctl / the job API.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/.tools/bin"
mkdir -p "$BIN"

if ! command -v brew >/dev/null; then
  echo "Homebrew is required for mmseqs2 and mafft" >&2
  exit 1
fi
brew list mmseqs2 >/dev/null 2>&1 || brew install mmseqs2
brew list mafft >/dev/null 2>&1 || brew install mafft

if [[ ! -x "$BIN/foldseek" ]]; then
  curl -L --fail -o /tmp/foldseek-osx-universal.tar.gz \
    https://mmseqs.com/foldseek/foldseek-osx-universal.tar.gz
  tar -xzf /tmp/foldseek-osx-universal.tar.gz -C /tmp
  cp /tmp/foldseek/bin/foldseek "$BIN/foldseek"
  chmod +x "$BIN/foldseek"
fi

if [[ ! -x "$ROOT/.tools/conda/bin/mkdssp" ]]; then
  conda create -y -p "$ROOT/.tools/conda" -c conda-forge dssp
fi

echo "mmseqs:  $(command -v mmseqs || echo /opt/homebrew/bin/mmseqs)"
echo "mafft:   $(command -v mafft || echo /opt/homebrew/bin/mafft)"
echo "foldseek:$BIN/foldseek"
echo "mkdssp:  $ROOT/.tools/conda/bin/mkdssp"
