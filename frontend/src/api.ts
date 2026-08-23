import type {
  ConservationColumn,
  FinalResult,
  Health,
  HomologHit,
  Job,
  JsonValue,
  ResidueAnnotation,
  ResearchWorkspace,
  Protocol,
  StructureSummary,
} from "./types";
import { getSession } from "./auth";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

async function requestHeaders(headers: HeadersInit = {}): Promise<Headers> {
  const result = new Headers(headers);
  const session = await getSession();
  if (session?.access_token) result.set("Authorization", `Bearer ${session.access_token}`);
  return result;
}

export function getHealth(): Promise<Health> {
  return requestHeaders().then((headers) =>
    fetch(apiUrl("/api/health"), { headers }),
  ).then((r) => parse<Health>(r));
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export function listJobs(): Promise<Job[]> {
  return requestHeaders().then((headers) =>
    fetch(apiUrl("/api/jobs"), { headers }),
  ).then((r) => parse<Job[]>(r));
}

export function listProtocols(): Promise<Protocol[]> {
  return requestHeaders().then((headers) =>
    fetch(apiUrl("/api/protocols"), { headers }),
  ).then((r) => parse<Protocol[]>(r));
}

export async function createJob(objective: string, playbookId?: string): Promise<Job> {
  const headers = await requestHeaders({ "Content-Type": "application/json" });
  return parse<Job>(await fetch(apiUrl("/api/jobs"), {
    method: "POST",
    headers,
    body: JSON.stringify({
      objective,
      include_structure: true,
      ...(playbookId ? { playbook_id: playbookId } : {}),
    }),
  }));
}

export async function harvestJob(id: string): Promise<Job> {
  const headers = await requestHeaders();
  return parse<Job>(await fetch(apiUrl(`/api/jobs/${id}/harvest`), { method: "POST", headers }));
}

export async function getJob(id: string): Promise<Job> {
  const headers = await requestHeaders();
  return parse<Job>(await fetch(apiUrl(`/api/jobs/${id}`), { headers }));
}

export async function getResearchWorkspace(id: string): Promise<ResearchWorkspace> {
  const headers = await requestHeaders();
  return parse<ResearchWorkspace>(await fetch(apiUrl(`/api/jobs/${id}/research`), { headers }));
}

export function watchJob(id: string, onJob: (job: Job) => void): () => void {
  const controller = new AbortController();
  let closed = false;
  let fallback: number | undefined;
  const apply = (job: Job) => {
    onJob(job);
    if (job.status === "complete" || job.status === "failed") {
      closed = true;
      controller.abort();
      if (fallback !== undefined) window.clearInterval(fallback);
    }
  };
  const startFallback = () => {
    if (closed || fallback !== undefined) return;
    fallback = window.setInterval(() => {
      getJob(id).then(apply).catch(() => undefined);
    }, 1000);
  };
  void (async () => {
    try {
      const headers = await requestHeaders({ Accept: "text/event-stream" });
      const response = await fetch(apiUrl(`/api/jobs/${id}/events`), {
        headers,
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error("SSE stream unavailable");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const data = frame
            .split(/\r?\n/)
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart())
            .join("\n");
          if (!data) continue;
          try {
            const payload = JSON.parse(data) as { job?: Job };
            if (payload.job) apply(payload.job);
          } catch {
            continue;
          }
        }
      }
      if (!closed) startFallback();
    } catch {
      if (!closed) startFallback();
    }
  })();
  return () => {
    closed = true;
    controller.abort();
    if (fallback !== undefined) window.clearInterval(fallback);
  };
}

export async function sendMessage(id: string, body: string): Promise<Job> {
  const headers = await requestHeaders({ "Content-Type": "application/json" });
  return parse<Job>(await fetch(apiUrl(`/api/jobs/${id}/messages`), {
    method: "POST",
    headers,
    body: JSON.stringify({ body }),
  }));
}

export async function loadJson<T>(jobId: string, filename: string): Promise<T | null> {
  const headers = await requestHeaders();
  return fetch(apiUrl(`/api/jobs/${jobId}/artifacts/${encodeURIComponent(filename)}`), { headers }).then((response) => {
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
  return loadArtifactResponse(jobId, filename).then((response) => {
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(response.statusText);
    return response.text();
  });
}

export function artifactUrl(jobId: string, filename: string): string {
  return apiUrl(`/api/jobs/${jobId}/artifacts/${encodeURIComponent(filename)}`);
}

export function loadText(jobId: string, filename: string): Promise<string | null> {
  return loadArtifactResponse(jobId, filename).then((response) => {
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(response.statusText);
    return response.text();
  });
}

async function loadArtifactResponse(jobId: string, filename: string): Promise<Response> {
  const headers = await requestHeaders();
  return fetch(artifactUrl(jobId, filename), { headers });
}

export async function loadArtifactBlob(jobId: string, filename: string): Promise<Blob | null> {
  const response = await loadArtifactResponse(jobId, filename);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(response.statusText);
  return response.blob();
}
