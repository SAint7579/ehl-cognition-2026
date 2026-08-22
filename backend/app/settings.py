from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    root: Path = Path(__file__).resolve().parents[2]
    runs_dir: Path = Path(__file__).resolve().parents[2] / "runs" / "jobs"
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    default_target: Path = Path(__file__).resolve().parents[2] / "fixtures" / "target_ispetase.fasta"
    default_database: Path = Path(__file__).resolve().parents[2] / "fixtures" / "homolog_db.fasta"
    default_structure: Path = (
        Path(__file__).resolve().parents[2] / "fixtures" / "structures" / "6EQE.pdb.gz"
    )
    default_references: Path = Path(__file__).resolve().parents[2] / "fixtures" / "structures"
    default_chain: str = "A"
    threads: int = 2
    poll_interval_seconds: float = 8.0
    poll_timeout_seconds: float = 1800.0


settings = Settings()
settings.runs_dir.mkdir(parents=True, exist_ok=True)

REQUIRED_DEVIN = ("DEVIN_API_KEY", "DEVIN_ORG_ID")


def load_dotenv(path: Path | None = None) -> None:
    file = path or settings.root / ".env"
    if not file.is_file():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def env_value(name: str) -> str:
    return os.environ.get(name, "").strip()


def missing_devin_settings() -> list[str]:
    return [name for name in REQUIRED_DEVIN if not env_value(name)]


def snapshot_configured() -> bool:
    return bool(env_value("DEVIN_SNAPSHOT_ID"))


def configured_repos() -> list[str]:
    raw = env_value("DEVIN_REPO") or "anirudh027/ehl-cognition-2026"
    return [item.strip() for item in raw.split(",") if item.strip()]
