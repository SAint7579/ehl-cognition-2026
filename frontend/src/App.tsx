import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  createJob,
  getHealth,
  getResearchWorkspace,
  harvestJob,
  listJobs,
  listProtocols,
  loadConservation,
  loadFinalResult,
  loadHomologs,
  loadResidues,
  loadStructure,
  loadStructurePdb,
  loadStructuredArtifact,
  loadText,
  sendMessage,
  watchJob,
} from "./api";
import { visibleMessages } from "./chat";
import { EvidenceWorkspace, parseDelimited } from "./EvidenceWorkspace";
import type { TableArtifact } from "./EvidenceWorkspace";
import { buildEvidenceTasks } from "./evidence";
import type { EvidenceTaskId } from "./evidence";
import { InvestigationGraph } from "./InvestigationGraph";
import { Sidebar } from "./Sidebar";
import {
  authEnabled,
  getSession,
  onAuthStateChange,
  signIn,
  signOut,
  signUp,
} from "./auth";
import type { Session } from "@supabase/supabase-js";
import type {
  ConservationColumn,
  FinalResult,
  Health,
  HomologHit,
  Job,
  Protocol,
  ResidueAnnotation,
  ResearchWorkspace,
  StructuredArtifact,
  StructureSummary,
} from "./types";
import { formatElapsed, stageStatus, Worklog } from "./Worklog";

const EXAMPLE_QUESTIONS = [
  "Compare deposited structures and identify conserved active-site residues",
  "Search the literature and synthesize evidence for this disease mechanism",
  "Dock a ligand into a deposited structure and report quantitative outputs",
];
const PETASE_TRIAD = new Set([160, 206, 237]);
const PETASE_STRUCTURES = new Set(["6EQE", "5XJH"]);

export function App() {
  const [objective, setObjective] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [protocols, setProtocols] = useState<Protocol[]>([]);
  const [selectedProtocolId, setSelectedProtocolId] = useState("");
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
  const [research, setResearch] = useState<ResearchWorkspace | null>(null);
  const [structuredArtifacts, setStructuredArtifacts] = useState<StructuredArtifact[]>([]);
  const [focusResidue, setFocusResidue] = useState<number | null>(null);
  const [selectedEvidenceTask, setSelectedEvidenceTask] = useState<EvidenceTaskId>("overview");
  const [starting, setStarting] = useState(false);
  const [clock, setClock] = useState(Date.now());
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(!authEnabled);
  const [authError, setAuthError] = useState<string | null>(null);
  const restored = useRef<string | null>(null);
  const composing = useRef(false);

  useEffect(() => {
    if (!authEnabled) return;
    let active = true;
    getSession().then((current) => {
      if (active) {
        setSession(current);
        setAuthReady(true);
      }
    }).catch(() => {
      if (active) setAuthReady(true);
    });
    return onAuthStateChange((current) => {
      setSession(current);
      setAuthError(null);
    });
  }, []);

  useEffect(() => {
    if (!authReady) return;
    clearEvidence();
    setJob(null);
    setJobs([]);
    restored.current = null;
    if (authEnabled && !session) return;
    getHealth().then(setHealth).catch(() => undefined);
    listProtocols()
      .then((items) => {
        setProtocols(items);
        setSelectedProtocolId(items.find((protocol) => protocol.is_default)?.id ?? "");
      })
      .catch(() => {
        setProtocols([]);
        setSelectedProtocolId("");
      });
    listJobs()
      .then((items) => {
        const ordered = [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
        setJobs(ordered);
        if (ordered[0] && !composing.current) setJob(ordered[0]);
      })
      .catch(() => undefined);
  }, [authReady, session?.user.id]);

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
    if (!job) return;
    let cancelled = false;
    const needsRestore =
      Boolean(job.devin_session_id) &&
      job.artifacts.length === 0 &&
      job.status !== "running" &&
      job.status !== "queued" &&
      restored.current !== job.id &&
      !job.messages.some(
        (item) =>
          item.speaker !== "user" &&
          item.speaker !== "system" &&
          item.body.length > 80,
      );
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
    return () => {
      cancelled = true;
    };
  }, [job?.id]);

  const artifactSignature = job
    ? `${job.id}:${job.artifacts.map((item) => `${item.filename}:${item.bytes}`).join(",")}`
    : "";

  useEffect(() => {
    if (!job) {
      clearEvidence();
      return;
    }
    let cancelled = false;
    const has = (name: string) => job.artifacts.some((item) => item.filename === name);
    clearEvidence();
    if (has("homolog_search.json")) {
      loadHomologs(job.id).then((value) => !cancelled && setHomologs(value)).catch(() => undefined);
    }
    if (has("conservation.json")) {
      loadConservation(job.id).then((value) => !cancelled && setColumns(value)).catch(() => undefined);
    }
    if (has("structure_summary.json")) {
      loadStructure(job.id).then((value) => !cancelled && setStructure(value)).catch(() => undefined);
    }
    if (has("residue_annotations.json")) {
      loadResidues(job.id).then((value) => !cancelled && setResidues(value)).catch(() => undefined);
    }
    if (has("final_result.json")) {
      loadFinalResult(job.id).then((value) => !cancelled && setResult(value)).catch(() => undefined);
    }
    if (
      job.artifacts.some(
        (artifact) =>
          /\.json$/i.test(artifact.filename) &&
          ["plan", "synthesis", "simulation"].includes(artifact.stage),
      )
    ) {
      getResearchWorkspace(job.id)
        .then((value) => !cancelled && setResearch(value))
        .catch(() => undefined);
    }
    const pdbName =
      job.artifacts.find((item) => item.filename === "structure.pdb")?.filename ??
      job.artifacts.find((item) => /\.pdb$/i.test(item.filename))?.filename;
    if (pdbName || has("structure_summary.json") || has("final_result.json")) {
      loadStructurePdb(job.id, pdbName ?? "structure.pdb")
        .then((value) => !cancelled && setPdbText(value))
        .catch(() => undefined);
    }
    const tableFiles = job.artifacts.filter((item) => /\.(csv|tsv)$/i.test(item.filename));
    if (tableFiles.length) {
      Promise.all(
        tableFiles.map((item) =>
          loadText(job.id, item.filename).then((text) =>
            text
              ? { artifact: item, filename: item.filename, rows: parseDelimited(text, item.filename) }
              : null,
          ),
        ),
      ).then((rows) => {
        if (!cancelled) {
          setTables(rows.filter((item): item is TableArtifact => item !== null));
        }
      });
    }
    const jsonFiles = job.artifacts.filter((item) => /\.json$/i.test(item.filename));
    if (jsonFiles.length) {
      Promise.all(
        jsonFiles.map((artifact) =>
          loadStructuredArtifact(job.id, artifact.filename).then((value) =>
            value === null ? null : { artifact, value },
          ),
        ),
      ).then((items) => {
        if (!cancelled) {
          setStructuredArtifacts(items.filter((item) => item !== null));
        }
      });
    }
    return () => {
      cancelled = true;
    };
  }, [artifactSignature, job?.id]);

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
  const awaitingConfirm = job?.active_stage === "waiting_for_approval";
  const awaitingUser = job?.active_stage === "waiting_for_user";
  const working =
    job?.status === "queued" ||
    (job?.status === "running" && !awaitingConfirm && !awaitingUser);
  const elapsed = job && working
    ? Math.max(0, Math.floor((clock - workStartedAt(job)) / 1000))
    : 0;

  function clearEvidence() {
    setHomologs([]);
    setColumns([]);
    setStructure(null);
    setResidues([]);
    setResult(null);
    setPdbText(null);
    setTables([]);
    setResearch(null);
    setStructuredArtifacts([]);
    setFocusResidue(null);
  }

  async function onStart(event: FormEvent) {
    event.preventDefault();
    if (starting || !objective.trim()) return;
    setError(null);
    setStarting(true);
    try {
      const created = await createJob(objective, selectedProtocolId || undefined);
      composing.current = false;
      setJob(created);
      setJobs((current) => upsert(current, created));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start the investigation.");
    } finally {
      setStarting(false);
    }
  }

  async function onSendText(text: string) {
    if (!job || !text.trim() || working) return;
    setDraft("");
    setError(null);
    try {
      const updated = await sendMessage(job.id, text.trim());
      setJob(updated);
      setJobs((current) => upsert(current, updated));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not send the follow-up.");
    }
  }

  async function onRecheck() {
    if (!job?.devin_session_id) return;
    setError(null);
    try {
      const updated = await harvestJob(job.id);
      setJob(updated);
      setJobs((current) => upsert(current, updated));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not re-check the Devin session.");
    }
  }

  function onNew() {
    composing.current = true;
    setJob(null);
    setObjective("");
    setSelectedProtocolId(protocols.find((protocol) => protocol.is_default)?.id ?? "");
    setError(null);
    setStarting(false);
    clearEvidence();
    setSelectedEvidenceTask("overview");
  }

  if (!job) {
    if (authEnabled && !authReady) return null;
    if (authEnabled && !session) {
      return <LoginScreen error={authError} onError={setAuthError} />;
    }
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
          email={session?.user.email}
          onSignOut={authEnabled ? () => void signOut() : undefined}
        />
        <main className="start-page">
          <div className="start-glow" />
          <form className="start" onSubmit={onStart}>
            <div className="start-label">
              <span className="sandbox-dot" />
              Devin scientific sandbox
            </div>
            <h1>Move from a research question to reviewable evidence.</h1>
            <p className="lede">
              Describe the biological problem in plain language. Devin handles the code,
              compute, scientific tools, and result files while you keep control of the investigation.
            </p>
            {health && !health.configured ? (
              <p className="warn">The backend is missing its Devin API configuration.</p>
            ) : null}
            <label className="objective-field">
              <span>Research question</span>
              <textarea
                value={objective}
                onChange={(event) => setObjective(event.target.value)}
                placeholder="What do you want to investigate?"
                autoFocus
              />
            </label>
            {protocols.length ? (
              <label className="objective-field">
                <span>Protocol</span>
                <select
                  value={selectedProtocolId}
                  onChange={(event) => setSelectedProtocolId(event.target.value)}
                >
                  {!protocols.some((protocol) => protocol.is_default) ? (
                    <option value="">Use the default protocol</option>
                  ) : null}
                  {protocols.map((protocol) => (
                    <option key={protocol.id} value={protocol.id}>
                      {protocol.title}
                      {protocol.is_default && !/\(default\)$/i.test(protocol.title)
                        ? " (default)"
                        : ""}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <div className="example-prompts">
              <span>Try an example</span>
              <div>
                {EXAMPLE_QUESTIONS.map((question) => (
                  <button type="button" key={question} onClick={() => setObjective(question)}>
                    {question}
                  </button>
                ))}
              </div>
            </div>
            <button
              className="start-button"
              type="submit"
              disabled={starting || health?.configured === false || !objective.trim()}
            >
              {starting ? "Opening sandbox…" : "Start investigation"}
              <span aria-hidden="true">→</span>
            </button>
            {error ? <p className="warn">{error}</p> : null}
            <div className="start-footnote">
              <span>Literature</span>
              <span>Sequence</span>
              <span>Structure</span>
              <span>Simulation</span>
              <span>Synthesis</span>
            </div>
          </form>
        </main>
      </div>
    );
  }

  return (
    <div className="shell">
      <Sidebar
        jobs={jobs}
        activeId={job.id}
        onSelect={setJob}
        onNew={onNew}
        email={session?.user.email}
        onSignOut={authEnabled ? () => void signOut() : undefined}
      />
      <section className="chat">
        <header className="chat-top">
          <div className="chat-title">
            <p className="eyebrow">Active investigation</p>
            <h1>{job.title}</h1>
            <p className="status">
              {awaitingConfirm
                ? "Review the proposed next step"
                : working
                  ? `${stageStatus(job.active_stage)} · ${formatElapsed(elapsed)}`
                  : job.error
                    ? "The latest turn needs attention"
                    : "Ready for a follow-up"}
            </p>
            {job.playbook_title ? <p className="status">Protocol: {job.playbook_title}</p> : null}
          </div>
          {job.session_url ? (
            <a className="session-link" href={job.session_url} target="_blank" rel="noreferrer">
              Open Devin session
              <span aria-hidden="true">↗</span>
            </a>
          ) : null}
          {job.status === "failed" && job.devin_session_id ? (
            <button type="button" className="session-link" onClick={() => void onRecheck()}>
              Re-check Devin session
              <span aria-hidden="true">↻</span>
            </button>
          ) : null}
        </header>
        {health?.supabase_configured && health.supabase_healthy === false ? (
          <div className="persistence-warning" role="alert">
            <strong>Results are not being saved.</strong>
            {health.supabase_last_failure ? (
              <span>
                {" "}
                {health.supabase_last_failure.operation}:{" "}
                {health.supabase_last_failure.message}
              </span>
            ) : null}
          </div>
        ) : null}
        {error ? <div className="inline-error">{error}</div> : null}
        <div className="investigation-body">
          <InvestigationGraph
            key={job.id}
            job={job}
            working={working}
            research={research}
            columns={columns}
            pdbText={pdbText}
            triad={triad}
            result={result}
            selected={selectedEvidenceTask}
            onSelect={setSelectedEvidenceTask}
          />
          <Worklog
            job={job}
            turns={turns}
            working={working}
            awaitingConfirm={Boolean(awaitingConfirm)}
            elapsed={elapsed}
            onProceed={() => void onSendText("Yes, proceed with the next step.")}
          />
        </div>
        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            void onSendText(draft);
          }}
        >
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask a follow-up, add a constraint, or request another analysis…"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void onSendText(draft);
              }
            }}
          />
          <button type="submit" disabled={working || !draft.trim()} aria-label="Send follow-up">
            <span aria-hidden="true">↑</span>
          </button>
        </form>
      </section>
      <EvidenceWorkspace
        job={job}
        tasks={evidenceTasks}
        selected={selectedEvidenceTask}
        onSelect={setSelectedEvidenceTask}
        tables={tables}
        homologs={homologs}
        columns={columns}
        structure={structure}
        pdbText={pdbText}
        triad={triad}
        result={result}
        research={research}
        structuredArtifacts={structuredArtifacts}
        focus={focusResidue}
        onFocus={setFocusResidue}
        working={working}
      />
    </div>
  );
}

function LoginScreen({
  error,
  onError,
}: {
  error: string | null;
  onError: (message: string | null) => void;
}) {
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setNotice(null);
    onError(null);
    try {
      const result = mode === "sign-in"
        ? await signIn(email.trim(), password)
        : await signUp(email.trim(), password);
      if (result.error) throw result.error;
      if (mode === "sign-up" && !result.data.session) {
        setNotice("Check your email to confirm your account, then sign in.");
      }
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="start-page auth-page">
      <div className="start-glow" />
      <form className="start auth-form" onSubmit={submit}>
        <div className="start-label">
          <span className="sandbox-dot" />
          Devin scientific sandbox
        </div>
        <h1>{mode === "sign-in" ? "Sign in to your research control room." : "Create your scientist account."}</h1>
        <p className="lede">
          Keep investigations private to your account while Devin handles the compute and evidence.
        </p>
        <label className="objective-field">
          <span>Email</span>
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required />
        </label>
        <label className="objective-field">
          <span>Password</span>
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "sign-in" ? "current-password" : "new-password"} minLength={6} required />
        </label>
        <button className="start-button" type="submit" disabled={busy}>
          {busy ? "Working…" : mode === "sign-in" ? "Sign in" : "Sign up"}
          <span aria-hidden="true">→</span>
        </button>
        {error ? <p className="warn">{error}</p> : null}
        {notice ? <p className="auth-notice">{notice}</p> : null}
        <button
          className="auth-toggle"
          type="button"
          onClick={() => {
            setMode(mode === "sign-in" ? "sign-up" : "sign-in");
            onError(null);
            setNotice(null);
          }}
        >
          {mode === "sign-in" ? "Need an account? Sign up" : "Already registered? Sign in"}
        </button>
      </form>
    </main>
  );
}

function workStartedAt(job: Job): number {
  const lastUser = [...job.messages].reverse().find((message) => message.speaker === "user");
  return Date.parse(lastUser?.created_at ?? job.created_at);
}

function upsert(jobs: Job[], next: Job): Job[] {
  return [next, ...jobs.filter((item) => item.id !== next.id)].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );
}
