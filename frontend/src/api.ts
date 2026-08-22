import type {
  ConservationColumn,
  FinalResult,
  Health,
  HomologHit,
  Job,
  ResidueAnnotation,
  StructureSummary,
} from "./types";

export function getHealth(): Promise<Health> {
  return fetch("/api/health").then((r) => parse<Health>(r));
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export function listJobs(): Promise<Job[]> {
  return fetch("/api/jobs").then((r) => parse<Job[]>(r));
}

export function createJob(objective: string): Promise<Job> {
  return fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ objective, include_structure: true }),
  }).then((r) => parse<Job>(r));
}

export function harvestJob(id: string): Promise<Job> {
  return fetch(`/api/jobs/${id}/harvest`, { method: "POST" }).then((r) => parse<Job>(r));
}

export function getJob(id: string): Promise<Job> {
  return fetch(`/api/jobs/${id}`).then((r) => parse<Job>(r));
}

export function sendMessage(id: string, body: string): Promise<Job> {
  return fetch(`/api/jobs/${id}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  }).then((r) => parse<Job>(r));
}

export function loadJson<T>(jobId: string, filename: string): Promise<T | null> {
  return fetch(`/api/jobs/${jobId}/artifacts/${filename}`).then((response) => {
    if (response.status === 404) return null;
    return parse<T>(response);
  });
}

export function loadHomologs(jobId: string): Promise<HomologHit[]> {
  return loadJson<{ hits: HomologHit[] }>(jobId, "homolog_search.json").then(
    (data) => data?.hits ?? [],
  );
}

export function loadConservation(jobId: string): Promise<ConservationColumn[]> {
  return loadJson<{ columns: ConservationColumn[] }>(jobId, "conservation.json").then(
    (data) => (data?.columns ?? []).filter((col) => col.target_position != null),
  );
}

export function loadStructure(jobId: string): Promise<StructureSummary | null> {
  return loadJson<StructureSummary>(jobId, "structure_summary.json");
}

export function loadResidues(jobId: string): Promise<ResidueAnnotation[]> {
  return loadJson<{ annotations: ResidueAnnotation[] }>(
    jobId,
    "residue_annotations.json",
  ).then((data) => data?.annotations ?? []);
}

export function loadFinalResult(jobId: string): Promise<FinalResult | null> {
  return loadJson<FinalResult>(jobId, "final_result.json");
}

export function loadStructurePdb(jobId: string): Promise<string | null> {
  return fetch(`/api/jobs/${jobId}/artifacts/structure.pdb`).then((response) => {
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(response.statusText);
    return response.text();
  });
}
