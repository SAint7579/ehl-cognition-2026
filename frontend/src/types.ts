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
  created_at: string;
  updated_at: string;
  messages: Message[];
  artifacts: ArtifactInfo[];
  limitations: string[];
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
