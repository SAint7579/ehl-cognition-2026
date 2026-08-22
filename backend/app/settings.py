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


settings = Settings()
settings.runs_dir.mkdir(parents=True, exist_ok=True)
