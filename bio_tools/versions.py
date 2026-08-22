"""Executable and package version discovery."""

from __future__ import annotations

import importlib.metadata
import platform
import subprocess
import sys
from typing import Mapping


def tool_version(tool: str) -> str:
    """Return a version string obtained by invoking an installed executable."""
    commands = {
        "mmseqs": ["mmseqs", "version"],
        "mafft": ["mafft", "--version"],
    }
    command = commands.get(tool, [tool, "--version"])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else "unknown"


def package_versions() -> Mapping[str, str]:
    names = ("biopython", "numpy", "pandas", "scipy", "pydantic", "jsonschema")
    return {
        name: importlib.metadata.version(name)
        for name in names
        if _installed(name)
    }


def _installed(name: str) -> bool:
    try:
        importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def environment_block() -> dict[str, object]:
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "mmseqs_version": tool_version("mmseqs"),
        "mafft_version": tool_version("mafft"),
        "package_versions": dict(package_versions()),
    }
