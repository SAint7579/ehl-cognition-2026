from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.models import ResearchCapability


@dataclass(frozen=True)
class CapabilitySpec:
    id: ResearchCapability
    title: str
    description: str
    tools: tuple[str, ...]
    outputs: tuple[str, ...]


@dataclass(frozen=True)
class ArtifactDescriptor:
    stage: str
    title: str
    purpose: str


CAPABILITY_SPECS = (
    CapabilitySpec(
        id=ResearchCapability.literature_search,
        title="Literature and database search",
        description="Retrieve focused public records and papers relevant to the scientific question.",
        tools=("public databases", "targeted web retrieval", "Python"),
        outputs=("literature_sources.csv",),
    ),
    CapabilitySpec(
        id=ResearchCapability.sequence_analysis,
        title="Sequence and evolutionary analysis",
        description="Search homologs, align sequences, measure conservation, and compare variants.",
        tools=("MMseqs2", "MAFFT", "HMMER", "bioctl", "Biopython"),
        outputs=("homolog_search.json", "alignment.fasta", "conservation.json"),
    ),
    CapabilitySpec(
        id=ResearchCapability.structure_analysis,
        title="Structure analysis",
        description="Inspect deposited structures, map residues, compare folds, and calculate structural context.",
        tools=("Foldseek", "DSSP", "Biopython", "bioctl"),
        outputs=("structure.pdb", "structure_summary.json", "residue_annotations.json"),
    ),
    CapabilitySpec(
        id=ResearchCapability.molecular_simulation,
        title="Molecular simulation",
        description="Run an appropriate CPU simulation or docking calculation and interpret quantitative outputs.",
        tools=("AutoDock Vina", "Open Babel", "Meeko", "OpenMM", "RDKit", "MDAnalysis", "Python"),
        outputs=("simulation_results.json", "simulation_metrics.csv"),
    ),
    CapabilitySpec(
        id=ResearchCapability.candidate_ranking,
        title="Candidate ranking",
        description="Compare candidate molecules, residues, variants, or hypotheses using explicit computed criteria.",
        tools=("bioctl", "Python", "pandas", "NumPy"),
        outputs=("candidate_sites.json", "candidate_comparison.csv"),
    ),
    CapabilitySpec(
        id=ResearchCapability.data_analysis,
        title="General data analysis",
        description="Clean, analyze, visualize, and statistically compare scientific datasets.",
        tools=("Python", "pandas", "NumPy", "SciPy", "scikit-learn"),
        outputs=("analysis_results.json", "analysis_table.csv"),
    ),
    CapabilitySpec(
        id=ResearchCapability.research_synthesis,
        title="Scientific synthesis",
        description="Integrate retrieved and computed results into conclusions, conflicts, gaps, and next experiments.",
        tools=("Python", "all artifacts produced in the sandbox"),
        outputs=("synthesis.json",),
    ),
)

SPEC_BY_ID = {spec.id: spec for spec in CAPABILITY_SPECS}


def capability_catalog() -> list[CapabilitySpec]:
    return list(CAPABILITY_SPECS)


def resolve_capabilities(
    objective: str,
    requested: list[ResearchCapability],
    include_structure: bool,
) -> list[ResearchCapability]:
    if requested:
        selected = list(dict.fromkeys(requested))
    else:
        text = objective.lower()
        selected: list[ResearchCapability] = []
        if _contains(text, "paper", "literature", "publication", "source", "database", "known about"):
            selected.append(ResearchCapability.literature_search)
        if _contains(text, "protein", "enzyme", "sequence", "homolog", "msa", "conservation", "mutation", "variant"):
            selected.append(ResearchCapability.sequence_analysis)
        if include_structure and _contains(
            text,
            "protein",
            "enzyme",
            "structure",
            "pdb",
            "residue",
            "binding pocket",
            "active site",
        ):
            selected.append(ResearchCapability.structure_analysis)
        if _contains(
            text,
            "simulate",
            "simulation",
            "docking",
            "dock",
            "molecular dynamics",
            "trajectory",
            "ligand",
            "binding affinity",
        ):
            selected.append(ResearchCapability.molecular_simulation)
        if _contains(
            text,
            "rank",
            "candidate",
            "shortlist",
            "engineer",
            "optimize",
            "design",
            "mutation",
            "variant",
        ):
            selected.append(ResearchCapability.candidate_ranking)
        if _contains(text, "csv", "dataset", "statistics", "correlation", "cluster", "plot", "compare"):
            selected.append(ResearchCapability.data_analysis)
        if not selected:
            selected.append(ResearchCapability.data_analysis)
    if ResearchCapability.research_synthesis not in selected:
        selected.append(ResearchCapability.research_synthesis)
    return selected


def capability_prompt(capabilities: list[ResearchCapability]) -> str:
    lines: list[str] = []
    for capability in capabilities:
        spec = SPEC_BY_ID[capability]
        lines.append(
            f"- {spec.title} (`{spec.id.value}`): {spec.description} "
            f"Available tools: {', '.join(spec.tools)}. Expected outputs: {', '.join(spec.outputs)}."
        )
    return "\n".join(lines)


def artifact_descriptor(filename: str) -> ArtifactDescriptor:
    name = filename.lower()
    known = {
        "protocol.md": ArtifactDescriptor(
            "plan",
            "Protocol used for this investigation",
            "The Devin laboratory protocol attached to this investigation at launch.",
        ),
        "research_plan.json": ArtifactDescriptor(
            "plan",
            "Research plan",
            "The staged scientific work Devin selected for this question.",
        ),
        "literature_sources.csv": ArtifactDescriptor(
            "literature",
            "Literature and database sources",
            "The focused source set used by the synthesis.",
        ),
        "synthesis.json": ArtifactDescriptor(
            "synthesis",
            "Scientific synthesis",
            "Integrated findings, disagreements, knowledge gaps, and next experiments.",
        ),
        "simulation_results.json": ArtifactDescriptor(
            "simulation",
            "Simulation results",
            "Methods, parameters, quantitative metrics, interpretation, and limitations for sandbox simulations.",
        ),
        "simulation_metrics.csv": ArtifactDescriptor(
            "simulation",
            "Simulation metrics",
            "Tabular quantitative outputs from the sandbox simulation.",
        ),
        "ligand_summary.json": ArtifactDescriptor(
            "simulation",
            "Ligand preparation summary",
            "Ligand identity, preparation method, and files used for molecular simulation.",
        ),
        "analysis_results.json": ArtifactDescriptor(
            "analysis",
            "Analysis results",
            "Structured results from a general scientific data analysis.",
        ),
        "analysis_table.csv": ArtifactDescriptor(
            "analysis",
            "Analysis table",
            "Tabular results produced by a general scientific analysis.",
        ),
        "homolog_search.json": ArtifactDescriptor(
            "homolog-search",
            "Homolog search results",
            "Related sequences used for evolutionary comparison.",
        ),
        "homologs.fasta": ArtifactDescriptor(
            "homolog-search",
            "Homolog sequence collection",
            "Sequences selected for alignment and comparative analysis.",
        ),
        "alignment.json": ArtifactDescriptor(
            "homolog-search",
            "Alignment summary",
            "Structured metadata for the multiple-sequence alignment.",
        ),
        "alignment.fasta": ArtifactDescriptor(
            "homolog-search",
            "Multiple-sequence alignment",
            "Aligned target and homolog sequences.",
        ),
        "conservation.json": ArtifactDescriptor(
            "conservation",
            "Residue conservation profile",
            "Per-position evolutionary conservation calculated from the alignment.",
        ),
        "structure_summary.json": ArtifactDescriptor(
            "structure",
            "Structure summary",
            "Structure identity, mapping quality, and calculated structural properties.",
        ),
        "residue_annotations.json": ArtifactDescriptor(
            "structure",
            "Residue annotations",
            "Sequence, conservation, and structural context mapped per residue.",
        ),
        "structure.pdb": ArtifactDescriptor(
            "structure",
            "3D structure coordinates",
            "Coordinates used for structural inspection and calculations.",
        ),
        "candidate_sites.json": ArtifactDescriptor(
            "rank",
            "Ranked candidate sites",
            "Computed candidate shortlists and their ranking criteria.",
        ),
        "final_result.json": ArtifactDescriptor(
            "synthesis",
            "Protein investigation result",
            "Integrated output from the protein-engineering pipeline.",
        ),
        "run.json": ArtifactDescriptor(
            "plan",
            "Pipeline run summary",
            "Stage outcomes and output files from the executed pipeline.",
        ),
    }
    if name in known:
        return known[name]
    suffix = Path(name).suffix
    if "simulation" in name or "docking" in name or "trajectory" in name or "ligand" in name:
        return ArtifactDescriptor("simulation", _title(filename), "Supporting output from a sandbox simulation.")
    if "literature" in name or "source" in name or "citation" in name:
        return ArtifactDescriptor("literature", _title(filename), "Source material used by the investigation.")
    if "synthesis" in name or "summary" in name or "conclusion" in name:
        return ArtifactDescriptor("synthesis", _title(filename), "Integrated interpretation of the investigation results.")
    if suffix in {".pdb", ".cif"} or "structure" in name or "residue" in name:
        return ArtifactDescriptor("structure", _title(filename), "Supporting structural output.")
    if "candidate" in name or "ranking" in name or "shortlist" in name:
        return ArtifactDescriptor("rank", _title(filename), "Supporting candidate comparison or ranking.")
    if "conservation" in name:
        return ArtifactDescriptor("conservation", _title(filename), "Supporting evolutionary conservation output.")
    if "homolog" in name or "alignment" in name or "sequence" in name:
        return ArtifactDescriptor("homolog-search", _title(filename), "Supporting sequence-analysis output.")
    if suffix in {".csv", ".tsv", ".json", ".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return ArtifactDescriptor("analysis", _title(filename), "Supporting output from a sandbox analysis.")
    return ArtifactDescriptor("other", _title(filename), "Supporting file produced by the sandbox.")


def _contains(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _title(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip().title()
