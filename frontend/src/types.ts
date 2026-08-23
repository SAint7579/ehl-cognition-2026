export type JobStatus = "queued" | "running" | "complete" | "failed";

export type Speaker =
  | "user"
  | "planner"
  | "search"
  | "structure"
  | "design"
  | "reviewer"
  | "system";

export type Message = {
  id: string;
  speaker: Speaker;
  body: string;
  stage: string | null;
  artifact_ids: string[];
  created_at: string;
};

export type ArtifactInfo = {
  id: string;
  filename: string;
  media_type: string;
  bytes: number;
  stage: string;
  title: string;
  purpose: string;
};

export type JobEvent = {
  id: number;
  type: string;
  stage: string | null;
  message: string;
  artifact_id: string | null;
  created_at: string;
};

export type Job = {
  id: string;
  title: string;
  objective: string;
  playbook: string;
  status: JobStatus;
  active_agent: Speaker | null;
  active_stage: string | null;
  error: string | null;
  include_structure: boolean;
  capabilities: string[];
  devin_session_id: string | null;
  session_url: string | null;
  created_at: string;
  updated_at: string;
  messages: Message[];
  events: JobEvent[];
  artifacts: ArtifactInfo[];
  limitations: string[];
};

export type Health = {
  status: "ok" | "not_configured";
  runtime: string;
  configured: boolean;
  missing: string[];
  snapshot_configured: boolean;
};

export type HomologHit = {
  accession: string;
  description: string;
  percent_identity: number;
  evalue: number;
};

export type ConservationColumn = {
  target_position: number | null;
  target_residue: string | null;
  conservation: number | null;
  entropy: number | null;
  informative: boolean;
};

export type ResidueAnnotation = {
  author_residue: number;
  target_position: number | null;
  one_letter: string;
  conservation: number | null;
  rsa: number | null;
  secondary_structure: string | null;
};

export type StructureSummary = {
  structure_id: string;
  chain: string;
  modelled_residue_count: number;
  deposition?: { pdb_id: string; experimental_method: string | null };
  foldseek_hits?: { target: string; alignment_tm_score: number }[];
};

export type CandidateSite = {
  rank: number;
  author_residue: number;
  one_letter: string;
  target_position: number;
  score: number;
  conservation: number;
};

export type FinalResult = {
  limitations?: string[];
  shortlists?: {
    activity?: { sites?: CandidateSite[] };
    stability?: { sites?: CandidateSite[] };
  };
};

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type ResearchTask = {
  id: string;
  title: string;
  purpose: string;
  capability: string;
  status: "PLANNED" | "RUNNING" | "COMPLETED" | "FAILED" | "BLOCKED" | "SKIPPED";
  methods: string[];
  output_files: string[];
};

export type ResearchPlan = {
  objective: string;
  strategy: string;
  tasks: ResearchTask[];
  assumptions: string[];
  required_inputs: string[];
};

export type SynthesisFinding = {
  title: string;
  statement: string;
  confidence: "HIGH" | "MEDIUM" | "LOW" | "NOT_ASSESSED";
  evidence_files: string[];
  implications: string[];
};

export type ResearchSynthesis = {
  objective: string;
  summary: string;
  findings: SynthesisFinding[];
  agreements: string[];
  disagreements: string[];
  knowledge_gaps: string[];
  recommended_next_steps: string[];
  limitations: string[];
};

export type SimulationMetric = {
  name: string;
  value: string | number | boolean | null;
  unit: string | null;
  interpretation: string;
};

export type SimulationRun = {
  id: string;
  question: string;
  method: string;
  engine: string;
  status: "COMPLETED" | "FAILED" | "BLOCKED" | "SKIPPED";
  input_files: string[];
  parameters: Record<string, string | number | boolean | null>;
  metrics: SimulationMetric[];
  output_files: string[];
  interpretation: string;
  limitations: string[];
};

export type SimulationResults = {
  objective: string;
  runs: SimulationRun[];
  summary: string;
  recommended_next_steps: string[];
};

export type ResearchWorkspace = {
  plan: ResearchPlan | null;
  plan_filename: string | null;
  synthesis: ResearchSynthesis | null;
  synthesis_filename: string | null;
  simulations: SimulationResults | null;
  simulations_filename: string | null;
  validation_errors: Record<string, string>;
};

export type StructuredArtifact = {
  artifact: ArtifactInfo;
  value: JsonValue;
};
