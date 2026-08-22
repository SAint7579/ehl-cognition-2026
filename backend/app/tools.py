"""Ensure CPU scientific CLIs are on PATH before bioctl runs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from backend.app.settings import settings

REQUIRED = (
    "mmseqs",
    "mafft",
    "foldseek",
    "mkdssp",
)

INSTALL_HINT = (
    "Install the CPU toolchain, then restart the API: "
    "brew install mmseqs2 mafft; "
    "curl -L https://mmseqs.com/foldseek/foldseek-osx-universal.tar.gz | tar xz; "
    "conda create -p .tools/conda -c conda-forge dssp"
)


def tool_search_dirs() -> list[Path]:
    return [
        settings.root / ".tools" / "bin",
        settings.root / ".tools" / "conda" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ]


def prepend_tool_path() -> None:
    extra = [str(path) for path in tool_search_dirs() if path.is_dir()]
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([*extra, current])


def missing_tools(names: tuple[str, ...] = REQUIRED) -> list[str]:
    prepend_tool_path()
    return [name for name in names if shutil.which(name) is None]


def require_tools(include_structure: bool) -> None:
    names = REQUIRED if include_structure else ("mmseqs", "mafft")
    missing = missing_tools(names)
    if missing:
        raise RuntimeError(
            "Missing scientific binaries: "
            + ", ".join(missing)
            + ". "
            + INSTALL_HINT
        )
