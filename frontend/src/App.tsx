import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  artifactUrl,
  createJob,
  getHealth,
  harvestJob,
  listJobs,
  loadConservation,
  loadFinalResult,
  loadHomologs,
  loadResidues,
  loadStructure,
  loadStructurePdb,
  loadText,
  sendMessage,
  watchJob,
} from "./api";
import { isStatusLine, visibleMessages } from "./chat";
import { InvestigationFlow } from "./InvestigationFlow";
import type { InvestigationSelection } from "./InvestigationFlow";
import { Markdown } from "./Markdown";
import { StructureViewer } from "./StructureViewer";
import type {
  CandidateSite,
  ArtifactInfo,
  ConservationColumn,
  FinalResult,
  Health,
  HomologHit,
  Job,
  ResidueAnnotation,
  StructureSummary,
} from "./types";

const DEFAULT_OBJECTIVE = "";

type TableArtifact = { filename: string; rows: string[][] };

type EvidenceTaskId =
  | "overview"
  | "plan"
  | "homolog-search"
  | "conservation"
  | "structure"
  | "rank"
  | "follow-up"
  | "other";

type EvidenceTaskDefinition = {
  id: Exclude<EvidenceTaskId, "overview">;
  title: string;
  purpose: string;
  stages: string[];
};

type EvidenceTask = EvidenceTaskDefinition & {
  artifacts: ArtifactInfo[];
  summary: string | null;
  updatedAt: string | null;
};

const PETASE_TRIAD = new Set([160, 206, 237]);
const PETASE_STRUCTURES = new Set(["6EQE", "5XJH"]);

const EVIDENCE_TASKS: EvidenceTaskDefinition[] = [
  {
    id: "plan",
    title: "Plan and execution setup",
    purpose: "Define the biological question, analysis stages, inputs, and sandbox work needed for this investigation.",
    stages: ["request", "sandbox", "plan", "new", "working", "running", "import"],
  },
  {
    id: "homolog-search",
    title: "Homolog search and alignment",
    purpose: "Find related sequences and establish the comparison set used by downstream evolutionary analyses.",
    stages: ["homolog-search"],
  },
  {
    id: "conservation",
    title: "Residue conservation analysis",
    purpose: "Measure how strongly each target residue is preserved across the selected homologs.",
    stages: ["conservation"],
  },
  {
    id: "structure",
    title: "Structure and spatial context",
    purpose: "Inspect the target structure and locate catalytic or candidate residues in three-dimensional context.",
    stages: ["structure"],
  },
  {
    id: "rank",
    title: "Candidate ranking and synthesis",
    purpose: "Combine the available evidence into engineering candidates and a reviewable final shortlist.",
    stages: ["rank", "review", "complete"],
  },
  {
    id: "follow-up",
    title: "Follow-up questions",
    purpose: "Preserve later questions and answers alongside the investigation they clarify.",
    stages: ["follow-up", "answer", "waiting_for_user", "waiting_for_approval"],
  },
  {
    id: "other",
    title: "Additional sandbox outputs",
    purpose: "Keep supporting files that do not yet map to a named scientific task.",
    stages: ["other", "error"],
  },
];

const STAGE_LABEL: Record<string, string> = {
  working: "Working in the sandbox…",
  waiting_for_user: "Waiting for you",
  waiting_for_approval: "Waiting for approval in the sandbox…",
  finished: "Finished this turn",
  new: "Starting the sandbox…",
  claimed: "Claiming the sandbox…",
  resuming: "Resuming the sandbox…",
  running: "Working in the sandbox…",
  "homolog-search": "Searching homologs…",
  conservation: "Computing conservation…",
  structure: "Reading the deposited structure…",
  rank: "Ranking candidate sites…",
  "follow-up": "Answering…",
  import: "Pulling result files…",
  sandbox: "Working in the sandbox…",
  plan: "Planning the investigation…",
};

export function App() {
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [homologs, setHomologs] = useState<HomologHit[]>([]);
  const [columns, setColumns] = useState<ConservationColumn[]>([]);
  const [structure, setStructure] = useState<StructureSummary | null>(null);
  const [residues, setResidues] = useState<ResidueAnnotation[]>([]);
  const [result, setResult] = useState<FinalResult | null>(null);
  const [pdbText, setPdbText] = useState<string | null>(null);
  const [tables, setTables] = useState<TableArtifact[]>([]);
  const [focusResidue, setFocusResidue] = useState<number | null>(null);
  const [selectedEvidenceTask, setSelectedEvidenceTask] = useState<EvidenceTaskId>("overview");
  const [starting, setStarting] = useState(false);
  const [clock, setClock] = useState(Date.now());
  const restored = useRef<string | null>(null);
  const composing = useRef(false);
  const artifactSig = useRef<string>("");

  useEffect(() => {
    getHealth().then(setHealth).catch(() => undefined);
    listJobs()
      .then((items) => {
        const ordered = [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
        setJobs(ordered);
        if (ordered[0] && !composing.current) setJob(ordered[0]);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!job) return;
    const live =
      job.status === "queued" ||
      job.status === "running" ||
      job.active_stage === "waiting_for_approval";
    if (!live) return;
    return watchJob(job.id, (next) => {
      setJob(next);
      setJobs((current) => upsert(current, next));
    });
  }, [job?.id, job?.status, job?.active_stage]);

  useEffect(() => {
    const live =
      job?.status === "queued" ||
      job?.status === "running" ||
      job?.active_stage === "waiting_for_approval";
    if (!live) return;
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, job?.active_stage]);

  useEffect(() => {
    if (!job) {
      artifactSig.current = "";
      setHomologs([]);
      setColumns([]);
      setStructure(null);
      setResidues([]);
      setResult(null);
      setPdbText(null);
      setTables([]);
      setFocusResidue(null);
      return;
    }
    let cancelled = false;
    const needsRestore =
      Boolean(job.devin_session_id) &&
      job.artifacts.length === 0 &&
      job.status !== "running" &&
      job.status !== "queued" &&
      restored.current !== job.id &&
      !job.messages.some((item) => item.speaker !== "user" && item.speaker !== "system" && item.body.length > 80);
    if (needsRestore) {
      restored.current = job.id;
      harvestJob(job.id)
        .then((next) => {
          if (cancelled) return;
          setJob(next);
          setJobs((current) => upsert(current, next));
        })
        .catch(() => undefined);
    }
    const signature = `${job.id}:${job.artifacts.map((item) => `${item.filename}:${item.bytes}`).join(",")}`;
    if (artifactSig.current === signature) {
      return () => {
        cancelled = true;
      };
    }
    artifactSig.current = signature;
    const has = (name: string) => job.artifacts.some((item) => item.filename === name);
    setHomologs([]);
    setColumns([]);
    setStructure(null);
    setResidues([]);
    setResult(null);
    setPdbText(null);
    if (has("homolog_search.json")) {
      loadHomologs(job.id)
        .then((value) => {
          if (!cancelled) setHomologs(value);
        })
        .catch(() => undefined);
    }
    if (has("conservation.json")) {
      loadConservation(job.id)
        .then((value) => {
          if (!cancelled) setColumns(value);
        })
        .catch(() => undefined);
    }
    if (has("structure_summary.json")) {
      loadStructure(job.id)
        .then((value) => {
          if (!cancelled) setStructure(value);
        })
        .catch(() => undefined);
    }
    if (has("residue_annotations.json")) {
      loadResidues(job.id)
        .then((value) => {
          if (!cancelled) setResidues(value);
        })
        .catch(() => undefined);
    }
    if (has("final_result.json")) {
      loadFinalResult(job.id)
        .then((value) => {
          if (!cancelled) setResult(value);
        })
        .catch(() => undefined);
    }
    const pdbName =
      job.artifacts.find((item) => item.filename === "structure.pdb")?.filename ??
      job.artifacts.find((item) => /\.pdb$/i.test(item.filename))?.filename;
    if (pdbName || has("structure_summary.json") || has("final_result.json")) {
      loadStructurePdb(job.id, pdbName ?? "structure.pdb")
        .then((value) => {
          if (!cancelled) setPdbText(value);
        })
        .catch(() => undefined);
    }
    const tableFiles = job.artifacts.filter((item) => /\.(csv|tsv)$/i.test(item.filename));
    if (tableFiles.length) {
      Promise.all(
        tableFiles.map((item) =>
          loadText(job.id, item.filename).then((text) =>
            text ? { filename: item.filename, rows: parseDelimited(text, item.filename) } : null,
          ),
        ),
      ).then((rows) => {
        if (!cancelled) setTables(rows.filter((item): item is TableArtifact => item !== null));
      });
    } else {
      setTables([]);
    }
    return () => {
      cancelled = true;
    };
  }, [job]);

  useEffect(() => {
    setSelectedEvidenceTask("overview");
  }, [job?.id]);

  const triad = useMemo(() => {
    const pdb = (structure?.deposition?.pdb_id ?? structure?.structure_id ?? "").toUpperCase();
    if (!PETASE_STRUCTURES.has(pdb)) return [];
    return residues.filter((row) => PETASE_TRIAD.has(row.author_residue));
  }, [residues, structure]);
  const turns = useMemo(() => (job ? visibleMessages(job.messages) : []), [job]);
  const evidenceTasks = useMemo(() => (job ? buildEvidenceTasks(job) : []), [job]);
  const onFlowSelection = useCallback((selection: InvestigationSelection) => {
    setSelectedEvidenceTask(evidenceTaskForStage(selection.stage));
  }, []);
  const awaitingConfirm = job?.active_stage === "waiting_for_approval";
  const awaitingUser = job?.active_stage === "waiting_for_user";
  const working =
    job?.status === "queued" ||
    (job?.status === "running" && !awaitingConfirm && !awaitingUser);
  const elapsed = job && working
    ? Math.max(0, Math.floor((clock - workStartedAt(job)) / 1000))
    : 0;
  async function onStart(event: FormEvent) {
    event.preventDefault();
    if (starting) return;
    setError(null);
    setStarting(true);
    try {
      const created = await createJob(objective);
      composing.current = false;
      setJob(created);
      setJobs((current) => upsert(current, created));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the investigation.");
    } finally {
      setStarting(false);
    }
  }

  async function onSendText(text: string) {
    if (!job || !text.trim() || working) return;
    setDraft("");
    const updated = await sendMessage(job.id, text.trim());
    setJob(updated);
    setJobs((current) => upsert(current, updated));
  }

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    await onSendText(draft);
  }

  function onNew() {
    composing.current = true;
    setJob(null);
    setError(null);
    setStarting(false);
    setHomologs([]);
    setColumns([]);
    setStructure(null);
    setResidues([]);
    setResult(null);
    setPdbText(null);
    setFocusResidue(null);
    setSelectedEvidenceTask("overview");
    artifactSig.current = "";
  }

  if (!job) {
    return (
      <div className="shell compose">
        <Sidebar
          jobs={jobs}
          activeId={null}
          onSelect={(item) => {
            composing.current = false;
            setJob(item);
          }}
          onNew={onNew}
        />
        <form className="start" onSubmit={onStart}>
          <p className="eyebrow">Investigation</p>
          <h1>What should we look at?</h1>
          <p className="lede">
            Ask in plain language. The work runs in a Devin Cloud sandbox. This
            window is the conversation and the evidence. There is no default
            enzyme — the request is the spec.
          </p>
          {health && !health.configured ? (
            <p className="warn">Add DEVIN_API_KEY and DEVIN_ORG_ID to .env, then restart the API.</p>
          ) : null}
          <textarea
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="Name the protein, reaction, or question…"
          />
          <button
            type="submit"
            disabled={starting || health?.configured === false || !objective.trim()}
          >
            {starting ? "Starting…" : "Start investigation"}
          </button>
          {error ? <p className="warn">{error}</p> : null}
        </form>
      </div>
    );
  }

  return (
    <div className="shell">
      <Sidebar jobs={jobs} activeId={job.id} onSelect={setJob} onNew={onNew} />
      <section className="chat">
        <header className="chat-top">
          <div>
            <h1>{job.title}</h1>
            <p className="status">
              {awaitingConfirm
                ? "Waiting for you to confirm the next step"
                : working
                  ? `${STAGE_LABEL[job.active_stage ?? ""] ?? "Working in the sandbox…"} · ${formatElapsed(elapsed)}`
                  : job.error
                    ? "Could not finish"
                    : "Ready for a follow-up"}
              {job.session_url ? (
                <>
                  {" · "}
                  <a href={job.session_url} target="_blank" rel="noreferrer">
                    Watch steps in Devin
                  </a>
                </>
              ) : null}
            </p>
          </div>
        </header>
        <div className="investigation-body">
          <InvestigationFlow
            key={job.id}
            job={job}
            working={working}
            onSelectionChange={onFlowSelection}
          />
          <section className="worklog-panel" aria-label="Live Devin worklog">
            <header className="worklog-heading">
              <div>
                <p className="eyebrow">Live worklog</p>
                <h2>Devin output</h2>
              </div>
              {working ? (
                <span className="streaming-label">
                  <span />
                  Streaming
                </span>
              ) : null}
            </header>
            <div className="worklog-stream" aria-live="polite" aria-relevant="additions text">
              <article className="worklog-entry user-entry">
                <div className="worklog-meta">
                  <span>You</span>
                  <time>{formatClock(job.created_at)}</time>
                </div>
                <Markdown>{job.objective}</Markdown>
              </article>
              {turns.map((turn, index) => {
                const status = turn.speaker !== "user" && isStatusLine(turn.body);
                const streaming = working && index === turns.length - 1 && turn.speaker !== "user";
                const followUpAnswer =
                  turn.speaker !== "user" &&
                  turns.slice(0, index).some((message) => message.speaker === "user");
                return (
                  <article
                    className={`worklog-entry ${turn.speaker === "user" ? "user-entry" : ""}${status ? " status-entry" : ""}`}
                    key={turn.id}
                  >
                    <div className="worklog-meta">
                      <span>
                        {status
                          ? "Progress"
                          : turn.speaker === "user"
                            ? "You"
                            : followUpAnswer
                              ? "Answer"
                              : stageName(turn.stage)}
                      </span>
                      <time>{formatClock(turn.created_at)}</time>
                    </div>
                    <Markdown>{turn.body}</Markdown>
                    {streaming ? <span className="stream-caret" aria-label="Content is streaming" /> : null}
                  </article>
                );
              })}
              {awaitingConfirm ? (
                <article className="worklog-entry confirm-entry">
                  <div className="worklog-meta">
                    <span>Approval needed</span>
                  </div>
                  <p>Confirm the next step to continue this investigation.</p>
                  <button
                    type="button"
                    className="confirm-go"
                    onClick={() => void onSendText("Yes, proceed with the next step.")}
                  >
                    Yes, proceed
                  </button>
                </article>
              ) : null}
              {working && !turns.length ? (
                <article className="worklog-entry status-entry">
                  <div className="worklog-meta">
                    <span>{stageName(job.active_stage)}</span>
                    <time>{formatElapsed(elapsed)}</time>
                  </div>
                  <p>The first worklog entry will appear here as Devin generates it.</p>
                  <span className="stream-caret" aria-label="Waiting for streamed content" />
                </article>
              ) : null}
            </div>
          </section>
        </div>
        <form className="composer" onSubmit={onSend}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ask a follow-up, add a constraint, or request another analysis"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void onSend(event);
              }
            }}
          />
          <button type="submit" disabled={working || !draft.trim()}>
            Send
          </button>
        </form>
      </section>
      <section className="evidence">
        <header className="evidence-top">
          <p className="eyebrow">Investigation evidence</p>
          <h2>{job.title}</h2>
          <p className="evidence-objective">{job.objective}</p>
          <p className="evidence-record">
            Updated {formatDateTime(job.updated_at)} · {job.artifacts.length} saved output
            {job.artifacts.length === 1 ? "" : "s"}
            {job.session_url ? (
              <>
                {" · "}
                <a href={job.session_url} target="_blank" rel="noreferrer">
                  Devin execution session
                </a>
              </>
            ) : null}
          </p>
        </header>
        <div className="results">
          {job.error && !working ? <div className="card warn-card">{friendlyError(job.error)}</div> : null}
          <TaskNavigation
            tasks={evidenceTasks}
            selected={selectedEvidenceTask}
            onSelect={setSelectedEvidenceTask}
          />
          {selectedEvidenceTask === "overview" ? (
            <TaskOverview tasks={evidenceTasks} onSelect={setSelectedEvidenceTask} working={working} />
          ) : (
            <TaskEvidence
              job={job}
              task={evidenceTasks.find((task) => task.id === selectedEvidenceTask) ?? null}
              tables={tables}
              homologs={homologs}
              columns={columns}
              structure={structure}
              pdbText={pdbText}
              triad={triad}
              result={result}
              focus={focusResidue}
              onFocus={setFocusResidue}
              working={working}
            />
          )}
          {job.limitations.length ? (
            <details className="notes">
              <summary>Limitations</summary>
              {job.limitations.map((item) => (
                <p key={item}>{item}</p>
              ))}
            </details>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function Sidebar({
  jobs,
  activeId,
  onSelect,
  onNew,
}: {
  jobs: Job[];
  activeId: string | null;
  onSelect: (job: Job) => void;
  onNew: () => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">ehl cognition</div>
      <button type="button" className="ghost" onClick={onNew}>
        New investigation
      </button>
      <div className="history">
        {jobs.map((item) => (
          <button
            type="button"
            key={item.id}
            className={`history-item ${item.id === activeId ? "current" : ""}`}
            onClick={() => onSelect(item)}
          >
            <span>{item.title}</span>
            <small>
              {item.status === "running" || item.status === "queued"
                ? "Working now"
                : `${formatShortDate(item.updated_at)} · ${item.artifacts.length} outputs`}
            </small>
          </button>
        ))}
      </div>
    </aside>
  );
}

function workStartedAt(job: Job): number {
  const lastUser = [...job.messages].reverse().find((message) => message.speaker === "user");
  return Date.parse(lastUser?.created_at ?? job.created_at);
}

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

function formatClock(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function formatShortDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function stageName(stage: string | null): string {
  const label = STAGE_LABEL[stage ?? ""] ?? "Devin";
  return label.replace(/…$/, "");
}

function upsert(jobs: Job[], next: Job): Job[] {
  return [next, ...jobs.filter((item) => item.id !== next.id)].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );
}

function friendlyError(error: string): string {
  const text = error.toLowerCase();
  if (text.includes("no route") || text.includes("errno 65") || text.includes("timed out") || text.includes("connection")) {
    return "Lost the connection to the sandbox for a moment. The earlier results are still here. Send the last follow-up again.";
  }
  if (text.includes("attachment")) {
    return "The sandbox finished. Restoring the result files now.";
  }
  if (text.includes("not on this mac") || text.includes("devin")) {
    return "The sandbox is not available. Check the Devin key in .env.";
  }
  return "Something went wrong in the sandbox. Try a follow-up, or start a new investigation.";
}

function buildEvidenceTasks(job: Job): EvidenceTask[] {
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
    (task) =>
      task.id !== "other" ||
      task.artifacts.length > 0 ||
      Boolean(task.summary),
  );
}

function evidenceTaskForStage(stage: string): EvidenceTaskId {
  if (stage === "complete" || stage === "request" || stage === "error") return "overview";
  return taskForStage(stage);
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
  if (filename === "run.json") return "plan";
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

function figures(artifacts: ArtifactInfo[]): ArtifactInfo[] {
  return artifacts.filter((item) => /\.(png|jpe?g|webp|gif|svg)$/i.test(item.filename));
}

function prettyName(filename: string): string {
  const text = filename.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
  return text.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function outputPresentation(
  artifact: ArtifactInfo,
  task: EvidenceTaskDefinition,
): { title: string; purpose: string } {
  const known: Record<string, { title: string; purpose: string }> = {
    "run.json": {
      title: "Sandbox run record",
      purpose: "Records execution details that can support a later audit or reproducible rerun.",
    },
    "homolog_search.json": {
      title: "Homolog search results",
      purpose: "Lists related sequences used to define the evolutionary comparison set.",
    },
    "homologs.fasta": {
      title: "Homolog sequence collection",
      purpose: "Preserves the exact sequences selected for downstream alignment and analysis.",
    },
    "alignment.json": {
      title: "Multiple-sequence alignment data",
      purpose: "Stores residue correspondence across the target and selected homologs.",
    },
    "alignment.fasta": {
      title: "Multiple-sequence alignment",
      purpose: "Provides the aligned sequences used to calculate residue conservation.",
    },
    "conservation.json": {
      title: "Residue conservation profile",
      purpose: "Reports how strongly each target position is preserved across the aligned homologs.",
    },
    "structure_summary.json": {
      title: "Structure identity and quality summary",
      purpose: "Identifies the structure source and records the structural context used for interpretation.",
    },
    "residue_annotations.json": {
      title: "Structure-mapped residue annotations",
      purpose: "Connects sequence positions, conservation values, accessibility, and structure residue numbers.",
    },
    "structure.pdb": {
      title: "3D structure coordinates",
      purpose: "Provides the coordinates rendered in the interactive structure view.",
    },
    "candidate_sites.json": {
      title: "Ranked candidate-site data",
      purpose: "Stores the scored residue candidates used to compare possible engineering sites.",
    },
    "final_result.json": {
      title: "Investigation shortlist and synthesis",
      purpose: "Preserves the final candidate groups, supporting evidence, and stated limitations.",
    },
  };
  const exact = known[artifact.filename.toLowerCase()];
  if (exact) return exact;
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
      purpose: `Provides the row-level data produced during ${task.title.toLowerCase()} for inspection or reuse.`,
    };
  }
  return {
    title,
    purpose: `Supporting output retained from ${task.title.toLowerCase()}.`,
  };
}

function TaskNavigation({
  tasks,
  selected,
  onSelect,
}: {
  tasks: EvidenceTask[];
  selected: EvidenceTaskId;
  onSelect: (task: EvidenceTaskId) => void;
}) {
  return (
    <nav className="task-navigation" aria-label="Evidence tasks">
      <button
        type="button"
        className={selected === "overview" ? "selected" : ""}
        onClick={() => onSelect("overview")}
      >
        All tasks
      </button>
      {tasks.map((task) => (
        <button
          type="button"
          className={selected === task.id ? "selected" : ""}
          onClick={() => onSelect(task.id)}
          key={task.id}
        >
          {task.title}
          {task.artifacts.length ? <span>{task.artifacts.length}</span> : null}
        </button>
      ))}
    </nav>
  );
}

function TaskOverview({
  tasks,
  onSelect,
  working,
}: {
  tasks: EvidenceTask[];
  onSelect: (task: EvidenceTaskId) => void;
  working: boolean;
}) {
  return (
    <section className="task-overview" aria-label="Investigation task outputs">
      <div className="task-overview-heading">
        <div>
          <p className="eyebrow">Task map</p>
          <h3>What each stage was for</h3>
        </div>
        <span>{working ? "Updating live" : "Saved investigation record"}</span>
      </div>
      <div className="task-summary-list">
        {tasks.map((task, index) => (
          <button type="button" className="task-summary-card" onClick={() => onSelect(task.id)} key={task.id}>
            <span className="task-number">Task {index + 1}</span>
            <strong>{task.title}</strong>
            <p>{task.purpose}</p>
            {task.summary ? <blockquote>{task.summary}</blockquote> : null}
            <span className="task-output-count">
              {task.artifacts.length
                ? `${task.artifacts.length} saved output${task.artifacts.length === 1 ? "" : "s"}`
                : "No saved output"}
              {task.updatedAt ? ` · ${formatDateTime(task.updatedAt)}` : ""}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function TaskEvidence({
  job,
  task,
  tables,
  homologs,
  columns,
  structure,
  pdbText,
  triad,
  result,
  focus,
  onFocus,
  working,
}: {
  job: Job;
  task: EvidenceTask | null;
  tables: TableArtifact[];
  homologs: HomologHit[];
  columns: ConservationColumn[];
  structure: StructureSummary | null;
  pdbText: string | null;
  triad: ResidueAnnotation[];
  result: FinalResult | null;
  focus: number | null;
  onFocus: (residue: number) => void;
  working: boolean;
}) {
  if (!task) return null;
  const taskIndex = EVIDENCE_TASKS.findIndex((definition) => definition.id === task.id) + 1;
  const tableNames = new Set(task.artifacts.map((artifact) => artifact.filename));
  const taskTables = tables.filter((table) => tableNames.has(table.filename));
  const taskFigures = figures(task.artifacts);
  return (
    <section className="task-evidence" aria-label={`${task.title} evidence`}>
      <header className="task-context">
        <p className="eyebrow">Task {taskIndex}</p>
        <h3>{task.title}</h3>
        <p>{task.purpose}</p>
        {task.summary ? (
          <div className="task-recap">
            <span>What Devin reported</span>
            <p>{task.summary}</p>
          </div>
        ) : null}
      </header>
      <OutputManifest jobId={job.id} task={task} />
      {task.id === "homolog-search" ? <HomologCard hits={homologs} /> : null}
      {task.id === "conservation" ? <ConservationCard columns={columns} /> : null}
      {task.id === "structure" ? (
        <StructureViewCard
          pdbText={pdbText}
          structure={structure}
          triad={triad}
          result={result}
          focus={focus}
          onFocus={onFocus}
        />
      ) : null}
      {task.id === "rank" ? <CandidatesCard result={result} onFocus={onFocus} /> : null}
      <FigureCard jobId={job.id} images={taskFigures} task={task} />
      <TableCard tables={taskTables} task={task} />
      {!task.artifacts.length ? (
        <div className="card task-empty">
          <h3>{working ? "No output saved yet" : "Context only"}</h3>
          <p className="card-meta">
            {working
              ? "This task is still part of the live investigation. Its outputs will appear here when Devin saves them."
              : "This task recorded the investigation context or discussion, but did not create a separate file."}
          </p>
        </div>
      ) : null}
    </section>
  );
}

function OutputManifest({ jobId, task }: { jobId: string; task: EvidenceTask }) {
  if (!task.artifacts.length) return null;
  return (
    <div className="card output-manifest">
      <p className="card-kicker">Saved outputs</p>
      <h3>Files produced for this task</h3>
      <p className="card-meta">Each output stays attached to the stage that produced it.</p>
      <ul>
        {task.artifacts.map((artifact) => {
          const presentation = outputPresentation(artifact, task);
          return (
            <li key={artifact.id}>
              <div>
                <strong>{presentation.title}</strong>
                <p>{presentation.purpose}</p>
                <small>
                  {artifact.filename} · {Math.max(1, Math.round(artifact.bytes / 1024))} KB
                </small>
              </div>
              <a href={artifactUrl(jobId, artifact.filename)} target="_blank" rel="noreferrer">
                Open
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function parseDelimited(text: string, filename: string): string[][] {
  const delimiter = filename.toLowerCase().endsWith(".tsv") ? "\t" : ",";
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 12)
    .map((line) => line.split(delimiter).slice(0, 8));
}

function FigureCard({
  jobId,
  images,
  task,
}: {
  jobId: string;
  images: ArtifactInfo[];
  task: EvidenceTaskDefinition;
}) {
  if (!images.length) return null;
  return (
    <>
      {images.map((item) => {
        const presentation = outputPresentation(item, task);
        return (
          <div className="card figure-card" key={item.filename}>
            <p className="card-kicker">Generated figure</p>
            <h3>{presentation.title}</h3>
            <p className="card-meta">{presentation.purpose} Not an experimental image.</p>
            <figure>
              <img src={artifactUrl(jobId, item.filename)} alt={prettyName(item.filename)} />
              <figcaption>{item.filename}</figcaption>
            </figure>
          </div>
        );
      })}
    </>
  );
}

function TableCard({ tables, task }: { tables: TableArtifact[]; task: EvidenceTaskDefinition }) {
  if (!tables.length) return null;
  return (
    <>
      {tables.map((table) => {
        const presentation = outputPresentation(
          { id: table.filename, filename: table.filename, media_type: "text/csv", bytes: 0 },
          task,
        );
        return (
          <div className="card" key={table.filename}>
            <p className="card-kicker">Generated table</p>
            <h3>{presentation.title}</h3>
            <p className="card-meta">{presentation.purpose}</p>
            <table>
              <tbody>
                {table.rows.map((row, index) => (
                  <tr key={`${table.filename}-${index}`}>
                    {row.map((cell, cellIndex) =>
                      index === 0 ? <th key={cellIndex}>{cell}</th> : <td key={cellIndex}>{cell}</td>,
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </>
  );
}

function HomologCard({ hits }: { hits: HomologHit[] }) {
  if (!hits.length) return null;
  return (
    <div className="card">
      <p className="card-kicker">Interpreted result</p>
      <h3>Homolog search results</h3>
      <p className="card-meta">
        {hits.length} related sequences used to establish the evolutionary comparison set.
      </p>
      <table>
        <thead>
          <tr>
            <th>Accession</th>
            <th>Identity</th>
            <th>E-value</th>
          </tr>
        </thead>
        <tbody>
          {hits.slice(0, 8).map((hit) => (
            <tr key={hit.accession}>
              <td>{hit.accession}</td>
              <td>{hit.percent_identity.toFixed(1)}%</td>
              <td>{hit.evalue.toExponential(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConservationCard({ columns }: { columns: ConservationColumn[] }) {
  if (!columns.length) return null;
  return (
    <div className="card">
      <p className="card-kicker">Generated chart</p>
      <h3>Residue conservation across the target sequence</h3>
      <p className="card-meta">
        Each cell is one target residue; darker cells are more conserved across the selected homologs.
      </p>
      <div className="heatmap" aria-label="conservation heatmap">
        {columns.map((col) => {
          const value = col.conservation ?? 0;
          return (
            <div
              key={col.target_position}
              className="cell"
              title={`${col.target_residue}${col.target_position}: ${value.toFixed(2)}`}
              style={{ opacity: 0.25 + value * 0.75 }}
            />
          );
        })}
      </div>
    </div>
  );
}

function StructureViewCard({
  pdbText,
  structure,
  triad,
  result,
  focus,
  onFocus,
}: {
  pdbText: string | null;
  structure: StructureSummary | null;
  triad: ResidueAnnotation[];
  result: FinalResult | null;
  focus: number | null;
  onFocus: (residue: number) => void;
}) {
  if (!pdbText && !structure) return null;
  const activity = (result?.shortlists?.activity?.sites ?? []).map((site) => site.author_residue);
  const stability = (result?.shortlists?.stability?.sites ?? []).map((site) => site.author_residue);
  const triadResi = triad.map((row) => row.author_residue);
  const top = structure?.foldseek_hits?.[0];
  const structureId = structure?.deposition?.pdb_id ?? structure?.structure_id;
  return (
    <div className="card viewer-card">
      <p className="card-kicker">Interactive 3D output</p>
      <h3>{structureId ? `3D structure view · ${structureId}` : "3D structure view"}</h3>
      <p className="card-meta">
        Inspect where catalytic and ranked candidate residues sit in the target structure. Deposited coordinates, not a computed fold
        {structure ? ` · ${structure.modelled_residue_count} modelled residues` : ""}
        {top ? ` · closest Foldseek ${top.target}` : ""}
      </p>
      {pdbText ? (
        <StructureViewer
          pdbText={pdbText}
          triad={triadResi}
          activity={activity}
          stability={stability}
          focus={focus}
        />
      ) : null}
      <div className="legend">
        <span className="swatch triad" /> Catalytic triad
        <span className="swatch activity" /> Activity sites
        <span className="swatch stability" /> Stability sites
      </div>
      {triad.length ? (
        <table>
          <thead>
            <tr>
              <th>Residue</th>
              <th>Target</th>
              <th>Conservation</th>
              <th>RSA</th>
            </tr>
          </thead>
          <tbody>
            {triad.map((row) => (
              <tr key={row.author_residue} className="click-row" onClick={() => onFocus(row.author_residue)}>
                <td>
                  {row.one_letter}
                  {row.author_residue}
                </td>
                <td>{row.target_position ?? "—"}</td>
                <td>{row.conservation?.toFixed(2) ?? "—"}</td>
                <td>{row.rsa?.toFixed(2) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

function CandidatesCard({
  result,
  onFocus,
}: {
  result: FinalResult | null;
  onFocus: (residue: number) => void;
}) {
  const activity = result?.shortlists?.activity?.sites ?? [];
  const stability = result?.shortlists?.stability?.sites ?? [];
  if (!activity.length && !stability.length) return null;
  return (
    <div className="card">
      <p className="card-kicker">Decision support</p>
      <h3>Ranked engineering candidates</h3>
      <p className="card-meta">
        Heuristic shortlists for activity and stability hypotheses. Click a residue to inspect it in 3D.
      </p>
      <ShortlistTable title="Activity" sites={activity} onFocus={onFocus} />
      <ShortlistTable title="Stability" sites={stability} onFocus={onFocus} />
    </div>
  );
}

function ShortlistTable({
  title,
  sites,
  onFocus,
}: {
  title: string;
  sites: CandidateSite[];
  onFocus: (residue: number) => void;
}) {
  if (!sites.length) return null;
  return (
    <>
      <h4>{title}</h4>
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Residue</th>
            <th>Score</th>
            <th>Conservation</th>
          </tr>
        </thead>
        <tbody>
          {sites.slice(0, 5).map((site) => (
            <tr
              key={`${title}-${site.author_residue}`}
              className="click-row"
              onClick={() => onFocus(site.author_residue)}
            >
              <td>{site.rank}</td>
              <td>
                {site.one_letter}
                {site.author_residue}
              </td>
              <td>{site.score.toFixed(2)}</td>
              <td>{site.conservation.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
