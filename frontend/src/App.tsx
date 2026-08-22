import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  createJob,
  getHealth,
  getJob,
  harvestJob,
  listJobs,
  loadConservation,
  loadFinalResult,
  loadHomologs,
  loadResidues,
  loadStructure,
  loadStructurePdb,
  sendMessage,
} from "./api";
import { isStatusLine, visibleMessages } from "./chat";
import { Markdown } from "./Markdown";
import { StructureViewer } from "./StructureViewer";
import type {
  CandidateSite,
  ConservationColumn,
  FinalResult,
  Health,
  HomologHit,
  Job,
  ResidueAnnotation,
  StructureSummary,
} from "./types";

const DEFAULT_OBJECTIVE = "";

const PETASE_TRIAD = new Set([160, 206, 237]);
const PETASE_STRUCTURES = new Set(["6EQE", "5XJH"]);

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
  const [focusResidue, setFocusResidue] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);
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
    const timer = window.setInterval(() => {
      getJob(job.id)
        .then((next) => {
          setJob(next);
          setJobs((current) => upsert(current, next));
        })
        .catch((err: Error) => setError(err.message));
    }, 1000);
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
      setFocusResidue(null);
      return;
    }
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
          setJob(next);
          setJobs((current) => upsert(current, next));
        })
        .catch(() => undefined);
    }
    const signature = `${job.id}:${job.artifacts.map((item) => item.filename).join(",")}`;
    if (artifactSig.current === signature) return;
    artifactSig.current = signature;
    const has = (name: string) => job.artifacts.some((item) => item.filename === name);
    if (has("homolog_search.json")) loadHomologs(job.id).then(setHomologs).catch(() => undefined);
    if (has("conservation.json")) loadConservation(job.id).then(setColumns).catch(() => undefined);
    if (has("structure_summary.json")) loadStructure(job.id).then(setStructure).catch(() => undefined);
    if (has("residue_annotations.json")) loadResidues(job.id).then(setResidues).catch(() => undefined);
    if (has("final_result.json")) loadFinalResult(job.id).then(setResult).catch(() => undefined);
    if (has("structure.pdb") || has("structure_summary.json") || has("final_result.json")) {
      loadStructurePdb(job.id).then(setPdbText).catch(() => undefined);
    }
  }, [job]);

  useEffect(() => {
    const node = threadRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [job?.messages.length, job?.status]);

  const triad = useMemo(() => {
    const pdb = (structure?.deposition?.pdb_id ?? structure?.structure_id ?? "").toUpperCase();
    if (!PETASE_STRUCTURES.has(pdb)) return [];
    return residues.filter((row) => PETASE_TRIAD.has(row.author_residue));
  }, [residues, structure]);
  const turns = useMemo(() => (job ? visibleMessages(job.messages) : []), [job]);
  const awaitingConfirm = job?.active_stage === "waiting_for_approval";
  const awaitingUser = job?.active_stage === "waiting_for_user";
  const working =
    job?.status === "queued" ||
    (job?.status === "running" && !awaitingConfirm && !awaitingUser);

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
                  ? STAGE_LABEL[job.active_stage ?? ""] ?? "Working in the sandbox…"
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
        <div className="thread" ref={threadRef}>
          <div className="bubble you">
            <div className="who">You</div>
            <Markdown>{job.objective}</Markdown>
          </div>
          {turns.map((turn) => {
            const status = turn.speaker !== "user" && isStatusLine(turn.body);
            return (
              <div
                className={`bubble ${turn.speaker === "user" ? "you" : "devin"}${status ? " status-line" : ""}`}
                key={turn.id}
              >
                <div className="who">{status ? "Working" : turn.speaker === "user" ? "You" : "Devin"}</div>
                <Markdown>{turn.body}</Markdown>
              </div>
            );
          })}
          {awaitingConfirm ? (
            <div className="bubble devin confirm">
              <div className="who">Devin</div>
              <p>Confirm the next step to continue. This prompt is only in the Devin app unless you answer here.</p>
              <button type="button" className="confirm-go" onClick={() => void onSendText("Yes, proceed with the next step.")}>
                Yes, proceed
              </button>
            </div>
          ) : null}
          {working ? (
            <div className="bubble devin progress">
              <div className="who">Working</div>
              <p className="progress-now">Searching, fetching, thinking…</p>
              <div className="typing">
                <span />
                <span />
                <span />
              </div>
            </div>
          ) : null}
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
          <h2>Evidence</h2>
          <p>Calculated from the sandbox run. Not experimental.</p>
        </header>
        <div className="results">
          {job.error && !working ? <div className="card warn-card">{friendlyError(job.error)}</div> : null}
          {!homologs.length && !columns.length && !structure && !working ? (
            <p className="empty">Results will land here as the investigation finishes.</p>
          ) : null}
          {working && !homologs.length ? <p className="empty">Waiting for the first artifacts…</p> : null}
          <StructureViewCard
            pdbText={pdbText}
            structure={structure}
            triad={triad}
            result={result}
            focus={focusResidue}
            onFocus={setFocusResidue}
          />
          <HomologCard hits={homologs} />
          <ConservationCard columns={columns} />
          <CandidatesCard result={result} onFocus={setFocusResidue} />
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
            <small>{item.status === "running" || item.status === "queued" ? "Working" : ""}</small>
          </button>
        ))}
      </div>
    </aside>
  );
}

function upsert(jobs: Job[], next: Job): Job[] {
  return [next, ...jobs.filter((item) => item.id !== next.id)].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  );
}

function friendlyError(error: string): string {
  if (error.toLowerCase().includes("attachment")) {
    return "The sandbox finished. Restoring the result files now.";
  }
  if (error.toLowerCase().includes("not on this mac") || error.toLowerCase().includes("devin")) {
    return "The sandbox is not available. Check the Devin key in .env.";
  }
  return "Something went wrong in the sandbox. Try a follow-up, or start a new investigation.";
}

function HomologCard({ hits }: { hits: HomologHit[] }) {
  if (!hits.length) return null;
  return (
    <div className="card">
      <h3>Homologs</h3>
      <p className="card-meta">{hits.length} sequences from the local fixture database</p>
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
      <h3>Conservation</h3>
      <p className="card-meta">Darker cells are more conserved along the target</p>
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
  return (
    <div className="card viewer-card">
      <h3>{structure?.deposition?.pdb_id ?? structure?.structure_id ?? "Structure"}</h3>
      <p className="card-meta">
        Deposited crystal structure, not a computed fold
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
      <h3>Candidate sites</h3>
      <p className="card-meta">Heuristic rankings. Click a residue to focus it in 3D.</p>
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
