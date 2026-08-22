"""Command-line interface for bioctl."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .candidates import analyze_candidates
from .conservation import analyze_alignment
from .homology import run_homolog_search
from .investigate import run_investigation
from .msa import run_msa
from .pipeline import run_pipeline
from .provenance import write_json_model
from .structure import analyze_structure

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

    structure = subparsers.add_parser("structure", help="analyze a protein structure")
    structure.add_argument("--structure", required=True, type=Path)
    structure.add_argument("--chain", required=True)
    structure.add_argument("--target", required=True, type=Path)
    structure.add_argument("--conservation", type=Path)
    structure.add_argument("--references", required=True, type=Path)
    structure.add_argument("--out", required=True, type=Path)
    structure.add_argument("--threads", type=int)

    candidates = subparsers.add_parser("candidates", help="rank candidate engineering sites")
    candidates.add_argument("--annotations", required=True, type=Path)
    candidates.add_argument("--structure", required=True, type=Path)
    candidates.add_argument("--chain", required=True)
    candidates.add_argument("--alignment", type=Path)
    candidates.add_argument("--catalytic-residue", type=int, default=160)
    candidates.add_argument("--catalytic-atom", default="OG")
    candidates.add_argument("--exclude", default="160,206,237")
    candidates.add_argument("--top", type=int, default=15)
    candidates.add_argument("--out", required=True, type=Path)

    investigate = subparsers.add_parser("investigate", help="run the protein-engineering playbook")
    investigate.add_argument("--objective", required=True)
    investigate.add_argument("--target", required=True, type=Path)
    investigate.add_argument("--database", required=True, type=Path)
    investigate.add_argument("--structure", required=True, type=Path)
    investigate.add_argument("--chain", required=True)
    investigate.add_argument("--references", required=True, type=Path)
    investigate.add_argument("--out", required=True, type=Path)
    investigate.add_argument("--constraint", action="append", default=[])
    investigate.add_argument("--threads", type=int)
    investigate.add_argument("--top", type=int, default=10)
    investigate.add_argument("--catalytic-residue", type=int, default=160)
    investigate.add_argument("--catalytic-atom", default="OG")
    investigate.add_argument("--exclude", default="160,206,237")
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
        elif args.command == "conservation":
            artifact = analyze_alignment(args.alignment, args.target_id)
            _write(args.out / "conservation.json", artifact)
            print(f"conservation complete: {artifact.summary.informative_columns} informative columns")
        elif args.command == "structure":
            summary, annotations = analyze_structure(
                args.structure,
                args.chain,
                args.target,
                args.out,
                args.references,
                args.conservation,
                args.threads,
            )
            _write(args.out / "structure_summary.json", summary)
            _write(args.out / "residue_annotations.json", annotations)
            print(f"structure complete: {summary.modelled_residue_count} modelled residues")
        elif args.command == "candidates":
            exclude = _parse_exclude(args.exclude)
            artifact = analyze_candidates(
                args.annotations,
                args.structure,
                args.chain,
                args.out,
                args.alignment,
                args.catalytic_residue,
                args.catalytic_atom,
                exclude,
                args.top,
            )
            _write(args.out / "candidate_sites.json", artifact)
            print(
                "candidates complete: "
                f"{artifact.shortlists['activity'].n_sites} activity, "
                f"{artifact.shortlists['stability'].n_sites} stability sites"
            )
        else:
            exclude = _parse_exclude(args.exclude)
            artifact, success = run_investigation(
                args.objective,
                args.target,
                args.database,
                args.structure,
                args.chain,
                args.references,
                args.out,
                args.constraint,
                args.threads,
                args.top,
                args.catalytic_residue,
                args.catalytic_atom,
                exclude,
            )
            _write(args.out / "final_result.json", artifact)
            if not success:
                error = next(
                    stage.error for stage in artifact.stages if stage.status == "FAILED"
                )
                print(f"bioctl: {error}", file=sys.stderr)
                return 1
            print("investigation complete")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"bioctl: {error}", file=sys.stderr)
        return 1
    return 0


def _write(path: Path, model: ModelT) -> ModelT:
    return write_json_model(path, model)


def _parse_exclude(value: str) -> list[int]:
    try:
        return [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise ValueError(f"invalid --exclude list: {value!r}") from error


if __name__ == "__main__":
    raise SystemExit(main())
