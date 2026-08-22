"""Command-line interface for bioctl."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .conservation import analyze_alignment
from .homology import run_homolog_search
from .msa import run_msa
from .pipeline import run_pipeline
from .provenance import write_json_model

ModelT = TypeVar("ModelT", bound=BaseModel)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bioctl")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run all pipeline stages")
    _common_inputs(run)
    run.add_argument("--threads", type=int)

    homolog = subparsers.add_parser("homolog-search", help="run MMseqs2 homolog search")
    homolog.add_argument("--target", required=True, type=Path)
    homolog.add_argument("--database", required=True, type=Path)
    homolog.add_argument("--out", required=True, type=Path)
    homolog.add_argument("--threads", type=int)

    msa = subparsers.add_parser("msa", help="run MAFFT on homolog sequences")
    msa.add_argument("--homologs", required=True, type=Path)
    msa.add_argument("--out", required=True, type=Path)
    msa.add_argument("--threads", type=int)

    conservation = subparsers.add_parser("conservation", help="analyze an alignment")
    conservation.add_argument("--alignment", required=True, type=Path)
    conservation.add_argument("--target-id", required=True)
    conservation.add_argument("--out", required=True, type=Path)
    return parser


def _common_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            run_pipeline(args.target, args.database, args.out, args.threads)
            print(f"pipeline complete: {args.out}")
        elif args.command == "homolog-search":
            artifact = run_homolog_search(args.target, args.database, args.out, args.threads)
            _write(args.out / "homolog_search.json", artifact)
            print(f"homolog search complete: {len(artifact.hits)} hits")
        elif args.command == "msa":
            artifact = run_msa(args.homologs, args.out / "alignment.fasta", args.threads)
            _write(args.out / "alignment.json", artifact)
            print(f"alignment complete: {artifact.n_sequences} sequences")
        else:
            artifact = analyze_alignment(args.alignment, args.target_id)
            _write(args.out / "conservation.json", artifact)
            print(f"conservation complete: {artifact.summary.informative_columns} informative columns")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"bioctl: {error}", file=sys.stderr)
        return 1
    return 0


def _write(path: Path, model: ModelT) -> ModelT:
    return write_json_model(path, model)


if __name__ == "__main__":
    raise SystemExit(main())
