from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    file = path or ROOT / ".env"
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


def env_value(name: str) -> str:
    return os.environ.get(name, "").strip()


def env_float(name: str, default: float) -> float:
    value = env_value(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_path(name: str, default: Path) -> Path:
    value = env_value(name)
    return Path(value).expanduser() if value else default


def env_origins() -> tuple[str, ...]:
    raw = env_value("CORS_ORIGINS")
    if not raw:
        return ("http://localhost:5173", "http://127.0.0.1:5173")
    return tuple(origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip())


load_dotenv()


class Settings(BaseModel):
    root: Path = ROOT
    runs_dir: Path = env_path("RUNS_DIR", ROOT / "runs" / "jobs")
    cors_origins: tuple[str, ...] = env_origins()
    default_target: Path = ROOT / "fixtures" / "target_ispetase.fasta"
    default_database: Path = ROOT / "fixtures" / "homolog_db.fasta"
    default_structure: Path = (
        ROOT / "fixtures" / "structures" / "6EQE.pdb.gz"
    )
    default_references: Path = ROOT / "fixtures" / "structures"
    default_chain: str = "A"
    threads: int = 2
    poll_interval_seconds: float = 0.5
    poll_timeout_seconds: float = env_float("DEVIN_POLL_TIMEOUT_SECONDS", 86400.0)
    poll_idle_timeout_seconds: float = env_float("DEVIN_IDLE_TIMEOUT_SECONDS", 5400.0)
    supabase_health_cache_seconds: float = env_float(
        "SUPABASE_HEALTH_CACHE_SECONDS", 5.0
    )
    supabase_refresh_seconds: float = env_float("SUPABASE_REFRESH_SECONDS", 30.0)
    supabase_url: str = env_value("SUPABASE_URL").rstrip("/")
    supabase_service_role_key: str = env_value("SUPABASE_SERVICE_ROLE_KEY")
    supabase_artifact_bucket: str = (
        env_value("SUPABASE_ARTIFACT_BUCKET") or "research-artifacts"
    )


settings = Settings()
settings.runs_dir.mkdir(parents=True, exist_ok=True)

REQUIRED_DEVIN = ("DEVIN_API_KEY", "DEVIN_ORG_ID")


def missing_devin_settings() -> list[str]:
    return [name for name in REQUIRED_DEVIN if not env_value(name)]


def snapshot_configured() -> bool:
    return bool(env_value("DEVIN_SNAPSHOT_ID"))


def supabase_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_role_key)


def configured_repos() -> list[str]:
    raw = env_value("DEVIN_REPO") or "anirudh027/ehl-cognition-2026"
    return [item.strip() for item in raw.split(",") if item.strip()]
