import { visibleMessages } from "./chat";
import type { ArtifactInfo, Job, ResearchTask, ResearchWorkspace } from "./types";

export type EvidenceTaskId =
  | "overview"
  | "plan"
  | "homolog-search"
  | "conservation"
  | "structure"
  | "literature"
  | "analysis"
  | "simulation"
  | "synthesis"
  | "rank"
  | "follow-up"
  | "other";

export type EvidenceTaskDefinition = {
  id: Exclude<EvidenceTaskId, "overview">;
  title: string;
  shortTitle: string;
  purpose: string;
  stages: string[];
};

export type EvidenceTask = EvidenceTaskDefinition & {
  artifacts: ArtifactInfo[];
  summary: string | null;
  updatedAt: string | null;
};

export const EVIDENCE_TASK_CAPABILITIES: Record<Exclude<EvidenceTaskId, "overview">, string> = {
  plan: "plan",
  literature: "literature-search",
  "homolog-search": "homolog-search",
  conservation: "conservation-analysis",
  structure: "structure-analysis",
  analysis: "data-analysis",
  simulation: "molecular-simulation",
  rank: "candidate-ranking",
  synthesis: "research-synthesis",
  "follow-up": "follow-up",
  other: "other",
};

const PLAN_CAPABILITY_MATCHES: Record<Exclude<EvidenceTaskId, "overview">, string[]> = {
  plan: ["plan", "setup"],
  literature: ["literature", "database", "retrieval"],
  "homolog-search": ["homolog", "sequence", "alignment"],
  conservation: ["conservation", "evolution"],
  structure: ["structure", "spatial"],
  analysis: ["analysis", "data"],
  simulation: ["simulation", "docking", "molecular"],
  rank: ["rank", "candidate", "shortlist"],
  synthesis: ["synthesis", "report"],
  "follow-up": ["follow", "answer"],
  other: ["other", "sandbox"],
};

export const EVIDENCE_TASKS: EvidenceTaskDefinition[] = [
  {
    id: "plan",
    title: "Plan and execution setup",
    shortTitle: "Plan",
    purpose: "Define the question, stages, inputs, and sandbox work needed for this investigation.",
    stages: ["request", "sandbox", "plan", "new", "working", "running", "import"],
  },
  {
    id: "literature",
    title: "Literature and database search",
    shortTitle: "Literature",
    purpose: "Collect the focused records and publications used to answer the research question.",
    stages: ["literature"],
  },
  {
    id: "homolog-search",
    title: "Homolog search and alignment",
    shortTitle: "Homologs",
    purpose: "Find related sequences and establish the comparison set for evolutionary analyses.",
    stages: ["homolog-search"],
  },
  {
    id: "conservation",
    title: "Residue conservation analysis",
    shortTitle: "Conservation",
    purpose: "Measure how strongly each target residue is preserved across the selected homologs.",
    stages: ["conservation"],
  },
  {
    id: "structure",
    title: "Structure and spatial context",
    shortTitle: "Structure",
    purpose: "Locate catalytic and candidate residues in three-dimensional structural context.",
    stages: ["structure"],
  },
  {
    id: "analysis",
    title: "Scientific data analysis",
    shortTitle: "Analysis",
    purpose: "Clean, compare, visualize, and statistically analyze scientific datasets.",
    stages: ["analysis"],
  },
  {
    id: "simulation",
    title: "Molecular simulation",
    shortTitle: "Simulation",
    purpose: "Run and interpret quantitative docking or simulation calculations.",
    stages: ["simulation"],
  },
  {
    id: "rank",
    title: "Candidate ranking",
    shortTitle: "Candidates",
    purpose: "Combine available evidence into a reviewable candidate shortlist.",
    stages: ["rank", "review", "complete"],
  },
  {
    id: "synthesis",
    title: "Scientific synthesis",
    shortTitle: "Synthesis",
    purpose: "Integrate evidence into findings, conflicts, limitations, and next experiments.",
    stages: ["synthesis"],
  },
  {
    id: "follow-up",
    title: "Follow-up questions",
    shortTitle: "Follow-up",
    purpose: "Preserve later questions and answers alongside the investigation they clarify.",
    stages: ["follow-up", "answer", "waiting_for_user", "waiting_for_approval"],
  },
  {
    id: "other",
    title: "Additional sandbox outputs",
    shortTitle: "Additional",
    purpose: "Keep supporting files that do not yet map to a named scientific task.",
    stages: ["other", "error"],
  },
];

export function buildEvidenceTasks(job: Job): EvidenceTask[] {
  const artifactStages = new Map<string, string>();
  for (const event of job.events) {
    if (event.type === "artifact.ready" && event.artifact_id && event.stage) {
      artifactStages.set(event.artifact_id, event.stage);
    }
  }

  const summaries = new Map<EvidenceTaskId, { text: string; updatedAt: string }>();
  let handlingFollowUp = false;
  for (const message of visibleMessages(job.messages)) {
    if (message.speaker === "user") handlingFollowUp = true;
    const taskId = handlingFollowUp
      ? "follow-up"
      : taskForStage(message.stage ?? speakerStage(message.speaker));
    summaries.set(taskId, { text: summarizeText(message.body), updatedAt: message.created_at });
  }
  for (const event of job.events) {
    if (!event.stage || !["artifact.ready", "agent.error"].includes(event.type)) continue;
    const taskId = taskForStage(event.stage);
    const current = summaries.get(taskId);
    if (!current || current.updatedAt < event.created_at) {
      summaries.set(taskId, {
        text: current?.text ?? event.message,
        updatedAt: event.created_at,
      });
    }
  }

  return EVIDENCE_TASKS.map((definition) => {
    const artifacts = job.artifacts.filter(
      (artifact) => taskForArtifact(artifact, artifactStages.get(artifact.id)) === definition.id,
    );
    const summary = summaries.get(definition.id);
    return {
      ...definition,
      artifacts,
      summary: summary?.text ?? null,
      updatedAt: summary?.updatedAt ?? null,
    };
  }).filter(
    (task) => task.id !== "other" || task.artifacts.length > 0 || Boolean(task.summary),
  );
}

export function matchingResearchTask(
  task: EvidenceTask,
  research: ResearchWorkspace | null,
): ResearchTask | undefined {
  return (research?.plan?.tasks ?? []).find((candidate) => {
    if (
      candidate.output_files.some((file) =>
        task.artifacts.some((artifact) => artifact.filename === file),
      )
    ) {
      return true;
    }
    const capability = candidate.capability.toLowerCase();
    return PLAN_CAPABILITY_MATCHES[task.id].some((term) => capability.includes(term));
  });
}

export function visibleEvidenceTasks(
  tasks: EvidenceTask[],
  research: ResearchWorkspace | null,
): EvidenceTask[] {
  return tasks.filter(
    (task) =>
      task.artifacts.length > 0 ||
      Boolean(task.summary) ||
      Boolean(matchingResearchTask(task, research)),
  );
}

export function labelCapability(value: string): string {
  return value.replace(/-/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function evidenceTaskForStage(stage: string): EvidenceTaskId {
  if (stage === "complete" || stage === "request" || stage === "error") return "overview";
  return EVIDENCE_TASKS.find((task) => task.stages.includes(stage))?.id ?? "overview";
}

export function outputPresentation(
  artifact: ArtifactInfo,
  task: EvidenceTaskDefinition,
): { title: string; purpose: string } {
  if (artifact.title && artifact.purpose) {
    return { title: artifact.title, purpose: artifact.purpose };
  }
  const title = prettyName(artifact.filename);
  if (/\.(png|jpe?g|webp|gif|svg)$/i.test(artifact.filename)) {
    return {
      title,
      purpose: `Visualizes a result produced during ${task.title.toLowerCase()}.`,
    };
  }
  if (/\.(csv|tsv)$/i.test(artifact.filename)) {
    return {
      title,
      purpose: `Provides row-level data from ${task.title.toLowerCase()} for inspection or reuse.`,
    };
  }
  return {
    title,
    purpose: `Supporting output retained from ${task.title.toLowerCase()}.`,
  };
}

export function prettyName(filename: string): string {
  const text = filename.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
  return text.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function taskForStage(stage: string | null | undefined): Exclude<EvidenceTaskId, "overview"> {
  if (!stage) return "other";
  return EVIDENCE_TASKS.find((task) => task.stages.includes(stage))?.id ?? "other";
}

function speakerStage(speaker: Job["messages"][number]["speaker"]): string {
  return {
    planner: "plan",
    search: "homolog-search",
    structure: "structure",
    design: "rank",
    reviewer: "review",
    user: "follow-up",
    system: "sandbox",
  }[speaker];
}

function taskForArtifact(
  artifact: ArtifactInfo,
  recordedStage?: string,
): Exclude<EvidenceTaskId, "overview"> {
  const filename = artifact.filename.toLowerCase();
  if (["protocol.md", "research_plan.json", "run.json"].includes(filename)) return "plan";
  if (filename === "literature_sources.csv") return "literature";
  if (["analysis_results.json", "analysis_table.csv"].includes(filename)) return "analysis";
  if (
    ["simulation_results.json", "simulation_metrics.csv", "ligand_summary.json"].includes(filename)
  ) {
    return "simulation";
  }
  if (filename === "synthesis.json") return "synthesis";
  if (["homolog_search.json", "homologs.fasta", "alignment.json", "alignment.fasta"].includes(filename)) {
    return "homolog-search";
  }
  if (filename === "conservation.json") return "conservation";
  if (
    ["structure_summary.json", "residue_annotations.json", "structure.pdb"].includes(filename) ||
    /\.(pdb|cif)$/i.test(filename)
  ) {
    return "structure";
  }
  if (["candidate_sites.json", "final_result.json"].includes(filename)) return "rank";
  if (artifact.stage) return taskForStage(artifact.stage);
  if (recordedStage) return taskForStage(recordedStage);
  return "other";
}

function summarizeText(value: string): string {
  const text = value
    .replace(/[#*_`>|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > 240 ? `${text.slice(0, 240)}…` : text;
}
