#!/usr/bin/env python3
"""Export committed JSON Schemas from the Pydantic artifact models."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bio_tools.models import (
    AlignmentArtifact,
    ConservationArtifact,
    HomologSearchArtifact,
    ResidueAnnotationsArtifact,
    RunArtifact,
    SCHEMA_VERSION,
    StructureSummaryArtifact,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "homolog_search": HomologSearchArtifact,
    "alignment": AlignmentArtifact,
    "conservation": ConservationArtifact,
    "run": RunArtifact,
    "structure_summary": StructureSummaryArtifact,
    "residue_annotations": ResidueAnnotationsArtifact,
}


def export_schemas(output_dir: Path) -> None:
    output_dir.mkdir(exist_ok=True)
    for name, model in SCHEMAS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://example.org/bio-tools/schemas/{name}.schema.json"
        schema["schema_version"] = SCHEMA_VERSION
        path = output_dir / f"{name}.schema.json"
        path.write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    export_schemas(ROOT / "schemas")


if __name__ == "__main__":
    main()
