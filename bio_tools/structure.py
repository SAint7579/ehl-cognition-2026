"""Structure analysis for a target protein and a Foldseek reference set."""

from __future__ import annotations

import gzip
import json
import shutil
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from Bio.Align import PairwiseAligner, substitution_matrices
from Bio.Data.PDBData import protein_letters_3to1
from Bio.PDB import PDBParser, is_aa
from Bio.PDB.DSSP import make_dssp_dict, residue_max_acc
from Bio.PDB.Residue import Residue

from . import __version__
from .fasta_io import validate_target
from .models import (
    FoldseekHit,
    MappingQuality,
    NumberingException,
    NumberingSummary,
    ProvenanceRecord,
    ResidueAnnotation,
    ResidueAnnotationsArtifact,
    ReverseIndexEntry,
    SecondaryStructureComposition,
    StructureDeposition,
    StructureSummaryArtifact,
    StructureWarning,
)
from .provenance import file_digest, run_tool

FOLDSEEK_COLUMNS = (
    "query,target,fident,alnlen,qstart,qend,tstart,tend,evalue,bits,"
    "alntmscore,qtmscore,ttmscore,lddt,prob,qcov,tcov"
)
LIMITATIONS = [
    "Deposited coordinates and deposition metadata are KNOWN evidence.",
    "DSSP, Foldseek, sequence mapping, and annotations are CALCULATED evidence.",
    "None of these structural results constitute experimental validation.",
]
MAPPING_IDENTITY_THRESHOLD = 0.9


@dataclass(frozen=True)
class StructureResidue:
    author_residue: int
    insertion_code: str | None
    resname: str
    one_letter: str
    altloc_present: bool


@dataclass(frozen=True)
class AnnotationData:
    structure_index: int
    author_residue: int
    insertion_code: str | None
    resname: str
    one_letter: str
    altloc_present: bool
    target_position: int | None
    target_residue: str | None
    msa_column: int | None
    conservation: float | None
    gap_fraction: float | None
    entropy: float | None
    dssp_8state: str | None
    secondary_structure: str | None
    acc: float | None
    rsa: float | None


def analyze_structure(
    structure_path: Path | str,
    chain_id: str,
    target_path: Path | str,
    out_dir: Path | str,
    references_dir: Path | str,
    conservation_path: Path | str | None = None,
    threads: int | None = None,
) -> tuple[StructureSummaryArtifact, ResidueAnnotationsArtifact]:
    structure_path = Path(structure_path).resolve()
    original_structure_path = structure_path
    target_path = Path(target_path).resolve()
    out_dir = Path(out_dir).resolve()
    references_dir = Path(references_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = validate_target(target_path)
    target_sequence = str(target.seq).upper()
    warnings: list[StructureWarning] = []
    pdb_path = _decompress_structure(structure_path, out_dir)
    residues, structure_sequence, residue_warnings = _extract_residues(pdb_path, chain_id)
    warnings.extend(residue_warnings)
    mapping_started = datetime.now(timezone.utc)
    mapping_clock = time.perf_counter()
    mapping, alignment_parameters = _map_to_target(structure_sequence, target_sequence)
    mapping_ended = datetime.now(timezone.utc)
    mapped_pairs = [
        (residue, target_position)
        for residue, target_position in zip(residues, mapping)
        if target_position is not None
    ]
    mapped_positions = len(mapped_pairs)
    identity_fraction = (
        sum(residue.one_letter == target_sequence[target_position - 1]
            for residue, target_position in mapped_pairs)
        / mapped_positions
        if mapped_positions
        else 0.0
    )
    alignment_parameters.update(
        {
            "mapped_positions": mapped_positions,
            "identity_fraction": identity_fraction,
            "identity_threshold": MAPPING_IDENTITY_THRESHOLD,
        }
    )
    if identity_fraction < MAPPING_IDENTITY_THRESHOLD:
        warnings.append(
            StructureWarning(
                code="LOW_MAPPING_IDENTITY",
                message=(
                    f"Only {identity_fraction:.3f} of mapped residues match the target; "
                    f"threshold is {MAPPING_IDENTITY_THRESHOLD:.3f}."
                ),
                severity="ERROR",
            )
        )
    mapping_provenance = ProvenanceRecord(
        stage="structure-mapping",
        tool_name="bio_tools.structure",
        tool_version=__version__,
        argv=None,
        parameters=alignment_parameters,
        input_files=[file_digest(structure_path), file_digest(target_path)],
        output_files=[],
        started_at=mapping_started,
        ended_at=mapping_ended,
        duration_seconds=time.perf_counter() - mapping_clock,
        exit_code=None,
        evidence_type="CALCULATED",
    )
    mapped_target_positions = {position for position in mapping if position is not None}
    unmodelled_positions = {
        index
        for index in range(1, len(target_sequence) + 1)
        if index not in mapped_target_positions
    }
    unmodelled = _ranges(unmodelled_positions)
    if unmodelled:
        warnings.append(
            StructureWarning(
                code="UNMODELLED_TARGET_RESIDUES",
                message=f"Target residues not represented by the structure: {', '.join(unmodelled)}.",
                severity="WARNING",
            )
        )
    outside_target = sum(position is None for position in mapping)
    if outside_target:
        warnings.append(
            StructureWarning(
                code="RESIDUE_OUTSIDE_TARGET",
                message=f"{outside_target} modelled residues have no counterpart in the target sequence.",
                severity="WARNING",
            )
        )
    numbering_exceptions: list[NumberingException] = []
    for index, residue in enumerate(residues, start=1):
        target_position = mapping[index - 1]
        residue_mismatch = (
            target_position is not None
            and residue.one_letter != target_sequence[target_position - 1]
        )
        if (
            target_position != residue.author_residue
            or residue.insertion_code is not None
            or residue_mismatch
        ):
            numbering_exceptions.append(
                NumberingException(
                    structure_index=index,
                    author_residue=residue.author_residue,
                    insertion_code=residue.insertion_code,
                    target_position=target_position,
                    reason=(
                        "author numbering differs from target position"
                        if target_position != residue.author_residue
                        else "insertion code present"
                        if residue.insertion_code is not None
                        else "structure residue differs from mapped target residue"
                    ),
                )
            )
    numbering = NumberingSummary(
        author_numbering_matches_target=all(
            target_position is None
            or (
                target_position == residue.author_residue
                and residue.insertion_code is None
                and residue.one_letter == target_sequence[target_position - 1]
            )
            for residue, target_position in zip(residues, mapping)
        ),
        exceptions=numbering_exceptions,
        mapping_quality=MappingQuality(
            mapped_positions=mapped_positions,
            identity_fraction=identity_fraction,
            identity_threshold=MAPPING_IDENTITY_THRESHOLD,
        ),
    )
    conservation = _load_conservation(conservation_path)
    if conservation is None:
        warnings.append(
            StructureWarning(
                code="CONSERVATION_NOT_PROVIDED",
                message="No conservation artifact was supplied; MSA and conservation fields are null.",
                severity="WARNING",
            )
        )
    msa_by_target = {}
    if conservation is not None:
        msa_by_target = {
            item["target_position"]: item
            for item in conservation["columns"]
            if item["target_position"] is not None
        }
    dssp_path = out_dir / "structure.dssp"
    dssp_parameters = {
        "command": "mkdssp --output-format dssp <input.pdb> <output.dssp>",
        "decompression": str(structure_path.suffix == ".gz"),
        "chain": chain_id,
        "rsa_scale": "Sander",
        "rsa_formula": "acc / residue_max_acc['Sander'][RESNAME3]",
    }
    try:
        dssp_provenance = run_tool(
            "dssp",
            "mkdssp",
            ["mkdssp", "--output-format", "dssp", str(pdb_path), str(dssp_path)],
            dssp_parameters,
            [pdb_path],
            [dssp_path],
        )
    except OSError as error:
        dssp_provenance = None
        warnings.append(
            StructureWarning(
                code="DSSP_FAILED",
                message=f"mkdssp could not be started ({error}). Secondary structure and RSA are omitted.",
                severity="WARNING",
            )
        )
    dssp_data: dict[tuple[str, tuple[str, int, str]], tuple[object, ...]] = {}
    if dssp_provenance is not None and dssp_provenance.exit_code == 0 and dssp_path.exists():
        dssp_data, _ = make_dssp_dict(str(dssp_path))
    elif dssp_provenance is not None:
        detail = (dssp_provenance.stderr or dssp_provenance.stdout or "").strip()
        if not detail:
            detail = f"exit {dssp_provenance.exit_code} with no output (crash)"
        warnings.append(
            StructureWarning(
                code="DSSP_FAILED",
                message=f"mkdssp failed: {detail}. Secondary structure and RSA are omitted.",
                severity="WARNING",
            )
        )
    annotations, dssp_warnings = _annotate_residues(
        residues, mapping, chain_id, dssp_data, target_sequence, msa_by_target
    )
    warnings.extend(dssp_warnings)
    composition = _secondary_composition(annotations)
    foldseek_path = out_dir / "foldseek.m8"
    foldseek_tmp = out_dir / "foldseek_tmp"
    reference_files = sorted(
        path
        for path in references_dir.iterdir()
        if path.is_file() and path.name.endswith((".pdb", ".pdb.gz", ".cif", ".cif.gz"))
        and path.resolve() != structure_path.resolve()
    )
    foldseek_references = out_dir / "foldseek_references"
    foldseek_references.mkdir(exist_ok=True)
    for reference in reference_files:
        link = foldseek_references / reference.name
        if not link.exists():
            link.symlink_to(reference)
    foldseek_argv = [
        "foldseek",
        "easy-search",
        str(structure_path),
        str(foldseek_references),
        str(foldseek_path),
        str(foldseek_tmp),
        "-e",
        "10",
        "--max-seqs",
        "100",
        "--threads",
        str(threads or 1),
        "--format-output",
        FOLDSEEK_COLUMNS,
    ]
    foldseek_provenance = run_tool(
        "foldseek",
        "foldseek",
        foldseek_argv,
        {
            "evalue": 10,
            "max_seqs": 100,
            "threads": threads or 1,
            "significance_threshold": 1e-3,
            "format_output": FOLDSEEK_COLUMNS.split(","),
            "query_coordinate_system": "structure_index",
            "reference_staging": "symlinks in the run output foldseek_references directory",
        },
        [structure_path, *reference_files],
        [foldseek_path],
    )
    if foldseek_provenance.exit_code != 0:
        raise RuntimeError(f"Foldseek failed: {foldseek_provenance.stderr.strip()}")
    if foldseek_tmp.exists():
        # Keep Foldseek temporary files on failure for debugging.
        shutil.rmtree(foldseek_tmp)
    foldseek_hits = _parse_foldseek(foldseek_path)
    reverse_index = [
        ReverseIndexEntry(
            msa_column=annotation.msa_column,
            target_position=annotation.target_position,
            structure_index=annotation.structure_index,
            author_residue=annotation.author_residue,
            insertion_code=annotation.insertion_code,
        )
        for annotation in annotations
    ]
    deposition, deposition_warnings = _deposition(original_structure_path, chain_id)
    warnings.extend(deposition_warnings)
    summary = StructureSummaryArtifact(
        structure_id=structure_path.name.split(".")[0].upper(),
        chain=chain_id,
        deposition=deposition,
        target_id=target.id,
        target_length=len(target_sequence),
        residue_counts={
            "target": len(target_sequence),
            "modelled_standard": len(residues),
            "unmodelled_target": len(unmodelled_positions),
            "dssp_annotated": sum(item.dssp_8state is not None for item in annotations),
        },
        modelled_residue_count=len(residues),
        modelled_range=_modelled_range(residues),
        unmodelled_target_ranges=unmodelled,
        secondary_structure=composition,
        foldseek_hits=foldseek_hits,
        numbering=numbering,
        reverse_index=reverse_index,
        warnings=warnings,
        provenance=[mapping_provenance, dssp_provenance, foldseek_provenance],
        limitations=LIMITATIONS,
    )
    annotation_artifact = ResidueAnnotationsArtifact(
        structure_id=summary.structure_id,
        target_id=target.id,
        chain=chain_id,
        annotations=[
            ResidueAnnotation(
                structure_index=annotation.structure_index,
                author_residue=annotation.author_residue,
                insertion_code=annotation.insertion_code,
                resname=annotation.resname,
                one_letter=annotation.one_letter,
                target_position=annotation.target_position,
                target_residue=annotation.target_residue,
                msa_column=annotation.msa_column,
                conservation=annotation.conservation,
                gap_fraction=annotation.gap_fraction,
                entropy=annotation.entropy,
                dssp_8state=annotation.dssp_8state,
                secondary_structure=annotation.secondary_structure,
                acc=annotation.acc,
                rsa=annotation.rsa,
                altloc_present=annotation.altloc_present,
                evidence_type="CALCULATED",
            )
            for annotation in annotations
        ],
        warnings=warnings,
        limitations=LIMITATIONS,
    )
    return summary, annotation_artifact


def _decompress_structure(path: Path, out_dir: Path) -> Path:
    if path.suffix != ".gz":
        return path
    output = out_dir / "structure_input.pdb"
    with gzip.open(path, "rb") as source, output.open("wb") as destination:
        shutil.copyfileobj(source, destination)
    return output


def _extract_residues(
    path: Path, chain_id: str
) -> tuple[list[StructureResidue], str, list[StructureWarning]]:
    structure = PDBParser(QUIET=True).get_structure(path.stem, str(path))
    model = next(structure.get_models())
    if chain_id not in model:
        raise ValueError(f"chain {chain_id!r} not found in structure")
    chain = model[chain_id]
    residues: list[StructureResidue] = []
    warning_details: dict[str, list[str]] = {}
    previous_author: tuple[int, str | None] | None = None
    for residue in chain:
        hetflag, resseq, insertion = residue.id
        insertion_code = insertion.strip() or None
        if hetflag != " ":
            code = "WATER_EXCLUDED" if residue.resname.strip() == "HOH" else "HETATM_EXCLUDED"
            warning_details.setdefault(code, []).append(str(resseq))
            continue
        if not is_aa(residue, standard=True):
            warning_details.setdefault("NONSTANDARD_RESIDUE", []).append(
                f"{residue.resname}:{resseq}{insertion_code or ''}"
            )
            continue
        current_author = (resseq, insertion_code)
        if previous_author is not None and _has_author_gap(previous_author, current_author):
            warning_details.setdefault("AUTHOR_NUMBERING_GAP", []).append(
                f"{previous_author[0] + 1}-{resseq - 1}"
            )
        previous_author = current_author
        if insertion_code is not None:
            warning_details.setdefault("INSERTION_CODE", []).append(
                f"{resseq}{insertion_code}"
            )
        altloc_present = any(atom.is_disordered() for atom in residue.get_atoms())
        if altloc_present:
            warning_details.setdefault("ALTERNATE_LOCATION", []).append(str(resseq))
            _select_altlocs(residue)
        try:
            one_letter = protein_letters_3to1[residue.resname.upper()]
        except KeyError as error:
            raise ValueError(f"unsupported standard residue {residue.resname!r}") from error
        residues.append(
            StructureResidue(
                author_residue=int(resseq),
                insertion_code=insertion_code,
                resname=residue.resname.upper(),
                one_letter=one_letter,
                altloc_present=altloc_present,
            )
        )
    warnings = [
        StructureWarning(code=code, message=_warning_message(code, values), severity="WARNING")
        for code, values in warning_details.items()
    ]
    return residues, "".join(item.one_letter for item in residues), warnings


def _has_author_gap(
    previous: tuple[int, str | None], current: tuple[int, str | None]
) -> bool:
    previous_resseq, previous_code = previous
    current_resseq, current_code = current
    if current_resseq > previous_resseq + 1:
        return True
    if current_resseq != previous_resseq:
        return False
    if previous_code is None or current_code is None:
        return False
    previous_rank = ord(previous_code)
    current_rank = ord(current_code)
    return current_rank > previous_rank + 1


def _select_altlocs(residue: Residue) -> None:
    for atom in residue.get_atoms():
        if atom.is_disordered():
            choices = atom.disordered_get_list()
            selected = next((item for item in choices if item.get_altloc() == "A"), None)
            if selected is None:
                selected = max(choices, key=lambda item: item.get_occupancy() or 0.0)
            atom.disordered_select(selected.get_altloc())


def _map_to_target(structure_sequence: str, target_sequence: str) -> tuple[list[int | None], dict[str, object]]:
    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.substitution_matrix = substitution_matrices.load("BLOSUM62")
    aligner.open_gap_score = -10.0
    aligner.extend_gap_score = -0.5
    alignment = aligner.align(target_sequence, structure_sequence)[0]
    mapping: list[int | None] = [None] * len(structure_sequence)
    for (target_start, target_end), (structure_start, structure_end) in zip(
        alignment.aligned[0], alignment.aligned[1]
    ):
        for target_index, structure_index in zip(
            range(target_start, target_end), range(structure_start, structure_end)
        ):
            mapping[structure_index] = target_index + 1
    return mapping, {
        "mode": "global",
        "substitution_matrix": "BLOSUM62",
        "gap_open_score": -10.0,
        "gap_extend_score": -0.5,
    }


def _load_conservation(path: Path | str | None) -> dict[str, object] | None:
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _annotate_residues(
    residues: list[StructureResidue],
    mapping: list[int | None],
    chain_id: str,
    dssp_data: dict[tuple[str, tuple[str, int, str]], tuple[object, ...]],
    target_sequence: str,
    msa_by_target: dict[int, dict[str, object]],
) -> tuple[list[AnnotationData], list[StructureWarning]]:
    annotations: list[AnnotationData] = []
    missing: list[str] = []
    for index, (residue, target_position) in enumerate(zip(residues, mapping), start=1):
        key = (chain_id, (" ", residue.author_residue, residue.insertion_code or " "))
        dssp = dssp_data.get(key)
        if dssp is None:
            missing.append(str(residue.author_residue))
        dssp_8state = str(dssp[1]) if dssp else None
        acc = float(dssp[2]) if dssp else None
        rsa = None
        if dssp is not None:
            max_acc = residue_max_acc["Sander"][residue.resname]
            rsa = acc / max_acc
        msa_item = msa_by_target.get(target_position) if target_position is not None else None
        annotations.append(
            AnnotationData(
                structure_index=index,
                author_residue=residue.author_residue,
                insertion_code=residue.insertion_code,
                resname=residue.resname,
                one_letter=residue.one_letter,
                altloc_present=residue.altloc_present,
                target_position=target_position,
                target_residue=(
                    target_sequence[target_position - 1] if target_position is not None else None
                ),
                msa_column=msa_item["column"] if msa_item else None,
                conservation=msa_item["conservation"] if msa_item else None,
                gap_fraction=msa_item["gap_fraction"] if msa_item else None,
                entropy=msa_item["entropy"] if msa_item else None,
                dssp_8state=dssp_8state,
                secondary_structure=_simplify_secondary(dssp_8state),
                acc=acc,
                rsa=rsa,
            )
        )
    warnings = []
    if missing and dssp_data:
        warnings.append(
            StructureWarning(
                code="ABSENT_FROM_DSSP",
                message=f"Modelled residues absent from DSSP output: {', '.join(missing)}.",
                severity="WARNING",
            )
        )
    high_rsa = [
        item.structure_index
        for item in annotations
        if item.rsa is not None and item.rsa > 1
    ]
    if high_rsa:
        warnings.append(
            StructureWarning(
                code="RSA_ABOVE_ONE",
                message=f"Relative solvent accessibility exceeds 1 at structure indices {high_rsa}.",
                severity="WARNING",
            )
        )
    return annotations, warnings


def _parse_foldseek(path: Path) -> list[FoldseekHit]:
    if not path.exists():
        return []
    hits = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        values = line.split("\t")
        if len(values) != len(FOLDSEEK_COLUMNS.split(",")):
            raise ValueError(f"Foldseek output has {len(values)} columns; expected 17")
        (
            query,
            target,
            fident,
            alnlen,
            qstart,
            qend,
            tstart,
            tend,
            evalue,
            bits,
            alntmscore,
            qtmscore,
            ttmscore,
            lddt,
            prob,
            qcov,
            tcov,
        ) = values
        hits.append(
            FoldseekHit(
                query=query,
                target=target,
                fident=float(fident),
                alignment_length=int(alnlen),
                qstart=int(qstart),
                qend=int(qend),
                tstart=int(tstart),
                tend=int(tend),
                evalue=float(evalue),
                bits=float(bits),
                alignment_tm_score=float(alntmscore),
                query_tm_score=float(qtmscore),
                target_tm_score=float(ttmscore),
                lddt=float(lddt),
                probability=float(prob),
                query_coverage=float(qcov),
                target_coverage=float(tcov),
                significant=float(evalue) <= 1e-3,
            )
        )
    return sorted(hits, key=lambda item: (item.evalue, item.target))


def _secondary_composition(annotations: list[AnnotationData]) -> SecondaryStructureComposition:
    eight = Counter(item.dssp_8state or "-" for item in annotations)
    three = Counter(_simplify_secondary(item.dssp_8state) for item in annotations)
    total = len(annotations)
    return SecondaryStructureComposition(
        counts_8state=dict(sorted(eight.items())),
        fractions_8state={key: value / total for key, value in sorted(eight.items())},
        counts_3state=dict(sorted(three.items())),
        fractions_3state={key: value / total for key, value in sorted(three.items())},
        simplification="H/G/I -> H (helix), E/B -> E (strand), all other DSSP states -> C (coil).",
    )


def _simplify_secondary(value: str | None) -> str:
    return "H" if value in {"H", "G", "I"} else "E" if value in {"E", "B"} else "C"


def _ranges(values: Iterable[int]) -> list[str]:
    ordered = sorted(values)
    if not ordered:
        return []
    result = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value != previous + 1:
            result.append(str(start) if start == previous else f"{start}-{previous}")
            start = value
        previous = value
    result.append(str(start) if start == previous else f"{start}-{previous}")
    return result


def _modelled_range(residues: list[StructureResidue]) -> str:
    if not residues:
        return ""
    first = residues[0].author_residue
    last = residues[-1].author_residue
    return str(first) if first == last else f"{first}-{last}"


def _warning_message(code: str, values: list[str]) -> str:
    messages = {
        "WATER_EXCLUDED": "Water residues were excluded from standard-residue annotations.",
        "HETATM_EXCLUDED": "HETATM residues were excluded from standard-residue annotations.",
        "NONSTANDARD_RESIDUE": "Non-standard or modified residues were excluded: ",
        "AUTHOR_NUMBERING_GAP": "Author numbering gaps were observed: ",
        "INSERTION_CODE": "Insertion codes were observed: ",
        "ALTERNATE_LOCATION": "Alternate locations were observed; altloc A was preferred, otherwise highest occupancy: ",
    }
    return messages.get(code, code) + (", ".join(values) if values else "")


def _deposition(
    path: Path, chain: str
) -> tuple[StructureDeposition, list[StructureWarning]]:
    raw = gzip.open(path, "rt", encoding="utf-8", errors="replace") if path.suffix == ".gz" else path.open(
        encoding="utf-8", errors="replace"
    )
    with raw as handle:
        header_lines = [line for line in handle if line.startswith("HEADER")]
    pdb_id = ""
    if header_lines:
        pdb_id = header_lines[0][62:66].strip().upper()
    if not pdb_id:
        pdb_id = path.name.split(".")[0].upper()
    manifest_path = path.parent / "MANIFEST.json"
    entries = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    item = next((entry for entry in entries if entry["pdb_id"] == pdb_id), {})
    warnings: list[StructureWarning] = []
    if not item:
        warnings.append(
            StructureWarning(
                code="DEPOSITION_METADATA_UNAVAILABLE",
                message=f"No deposition manifest metadata found for structure {pdb_id}.",
                severity="WARNING",
            )
        )
    return StructureDeposition(
        pdb_id=pdb_id,
        chain=chain,
        title=item.get("title"),
        experimental_method=item.get("experimental_method"),
        resolution_angstrom=item.get("resolution"),
        evidence_type="KNOWN",
    ), warnings
