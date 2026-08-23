import type {
  ConservationColumn,
  FinalResult,
  Health,
  HomologHit,
  Job,
  JsonValue,
  ResidueAnnotation,
  ResearchWorkspace,
  StructureSummary,
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export function getHealth(): Promise<Health> {
  return fetch(apiUrl("/api/health")).then((r) => parse<Health>(r));
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export function listJobs(): Promise<Job[]> {
  return fetch(apiUrl("/api/jobs")).then((r) => parse<Job[]>(r));
}

export function createJob(objective: string): Promise<Job> {
  return fetch(apiUrl("/api/jobs"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ objective, include_structure: true }),
  }).then((r) => parse<Job>(r));
}

export function harvestJob(id: string): Promise<Job> {
  return fetch(apiUrl(`/api/jobs/${id}/harvest`), { method: "POST" }).then((r) => parse<Job>(r));
}

export function getJob(id: string): Promise<Job> {
  return fetch(apiUrl(`/api/jobs/${id}`)).then((r) => parse<Job>(r));
}

export function getResearchWorkspace(id: string): Promise<ResearchWorkspace> {
  return fetch(apiUrl(`/api/jobs/${id}/research`)).then((r) => parse<ResearchWorkspace>(r));
}

export function watchJob(id: string, onJob: (job: Job) => void): () => void {
  const source = new EventSource(apiUrl(`/api/jobs/${id}/events`));
  let closed = false;
  let fallback: number | undefined;
  const apply = (job: Job) => {
    onJob(job);
    if (job.status === "complete" || job.status === "failed") {
      closed = true;
      source.close();
      if (fallback !== undefined) window.clearInterval(fallback);
    }
  };
  source.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data) as { job?: Job };
      if (payload.job) apply(payload.job);
    } catch {
      return;
    }
  };
  source.onerror = () => {
    if (closed || fallback !== undefined) return;
    fallback = window.setInterval(() => {
      getJob(id).then(apply).catch(() => undefined);
    }, 1000);
  };
  return () => {
    closed = true;
    source.close();
    if (fallback !== undefined) window.clearInterval(fallback);
  };
}

export function sendMessage(id: string, body: string): Promise<Job> {
  return fetch(apiUrl(`/api/jobs/${id}/messages`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  }).then((r) => parse<Job>(r));
}

export function loadJson<T>(jobId: string, filename: string): Promise<T | null> {
  return fetch(apiUrl(`/api/jobs/${jobId}/artifacts/${encodeURIComponent(filename)}`)).then((response) => {
    if (response.status === 404) return null;
    return parse<T>(response);
  });
}

export function loadStructuredArtifact(jobId: string, filename: string): Promise<JsonValue | null> {
  return loadJson<JsonValue>(jobId, filename);
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

export function loadStructurePdb(jobId: string, filename = "structure.pdb"): Promise<string | null> {
  return fetch(artifactUrl(jobId, filename)).then((response) => {
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(response.statusText);
    return response.text();
  });
}

export function artifactUrl(jobId: string, filename: string): string {
  return apiUrl(`/api/jobs/${jobId}/artifacts/${encodeURIComponent(filename)}`);
}

export function loadText(jobId: string, filename: string): Promise<string | null> {
  return fetch(artifactUrl(jobId, filename)).then((response) => {
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(response.statusText);
    return response.text();
  });
}
