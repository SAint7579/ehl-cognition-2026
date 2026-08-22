import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
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
  const [tables, setTables] = useState<TableArtifact[]>([]);
  const [focusResidue, setFocusResidue] = useState<number | null>(null);
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
    const signature = `${job.id}:${job.artifacts.map((item) => `${item.filename}:${item.bytes}`).join(",")}`;
    if (artifactSig.current === signature) return;
    artifactSig.current = signature;
    const has = (name: string) => job.artifacts.some((item) => item.filename === name);
    if (has("homolog_search.json")) loadHomologs(job.id).then(setHomologs).catch(() => undefined);
    if (has("conservation.json")) loadConservation(job.id).then(setColumns).catch(() => undefined);
    if (has("structure_summary.json")) loadStructure(job.id).then(setStructure).catch(() => undefined);
    if (has("residue_annotations.json")) loadResidues(job.id).then(setResidues).catch(() => undefined);
    if (has("final_result.json")) loadFinalResult(job.id).then(setResult).catch(() => undefined);
    const pdbName =
      job.artifacts.find((item) => item.filename === "structure.pdb")?.filename ??
      job.artifacts.find((item) => /\.pdb$/i.test(item.filename))?.filename;
    if (pdbName || has("structure_summary.json") || has("final_result.json")) {
      loadStructurePdb(job.id, pdbName ?? "structure.pdb").then(setPdbText).catch(() => undefined);
    }
    const tableFiles = job.artifacts.filter((item) => /\.(csv|tsv)$/i.test(item.filename));
    if (tableFiles.length) {
      Promise.all(
        tableFiles.map((item) =>
          loadText(job.id, item.filename).then((text) =>
            text ? { filename: item.filename, rows: parseDelimited(text, item.filename) } : null,
          ),
        ),
      ).then((rows) => setTables(rows.filter((item): item is TableArtifact => item !== null)));
    } else {
      setTables([]);
    }
  }, [job]);

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
          <InvestigationFlow key={job.id} job={job} working={working} />
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
          <h2>Evidence</h2>
          <p>Calculated from the sandbox run. Not experimental.</p>
        </header>
        <div className="results">
          {job.error && !working ? <div className="card warn-card">{friendlyError(job.error)}</div> : null}
          {!homologs.length && !columns.length && !structure && !figures(job).length && !tables.length && !working ? (
            <p className="empty">Results will land here as the investigation finishes.</p>
          ) : null}
          {working && !homologs.length && !figures(job).length ? <p className="empty">Waiting for the first artifacts…</p> : null}
          <FigureCard jobId={job.id} images={figures(job)} />
          <StructureViewCard
            pdbText={pdbText}
            structure={structure}
            triad={triad}
            result={result}
            focus={focusResidue}
            onFocus={setFocusResidue}
          />
          <TableCard tables={tables} />
          <HomologCard hits={homologs} />
          <ConservationCard columns={columns} />
          <CandidatesCard result={result} onFocus={setFocusResidue} />
          <FileListCard jobId={job.id} artifacts={job.artifacts} />
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

function figures(job: Job): ArtifactInfo[] {
  return job.artifacts.filter((item) => /\.(png|jpe?g|webp|gif|svg)$/i.test(item.filename));
}

function prettyName(filename: string): string {
  return filename.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
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

function FigureCard({ jobId, images }: { jobId: string; images: ArtifactInfo[] }) {
  if (!images.length) return null;
  return (
    <div className="card figure-card">
      <h3>Figures</h3>
      <p className="card-meta">Attached images from the sandbox. Not experimental photos.</p>
      <div className="figure-grid">
        {images.map((item) => (
          <figure key={item.filename}>
            <img src={artifactUrl(jobId, item.filename)} alt={prettyName(item.filename)} />
            <figcaption>{prettyName(item.filename)}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}

function TableCard({ tables }: { tables: TableArtifact[] }) {
  if (!tables.length) return null;
  return (
    <>
      {tables.map((table) => (
        <div className="card" key={table.filename}>
          <h3>{prettyName(table.filename)}</h3>
          <p className="card-meta">{table.filename}</p>
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
      ))}
    </>
  );
}

function FileListCard({ jobId, artifacts }: { jobId: string; artifacts: ArtifactInfo[] }) {
  const extras = artifacts.filter(
    (item) =>
      !["homolog_search.json", "conservation.json", "structure_summary.json", "residue_annotations.json", "final_result.json", "candidate_sites.json", "structure.pdb"].includes(
        item.filename,
      ) && !/\.(png|jpe?g|webp|gif|svg|csv|tsv)$/i.test(item.filename),
  );
  if (!extras.length) return null;
  return (
    <div className="card">
      <h3>Other files</h3>
      <p className="card-meta">Also attached to this investigation</p>
      <ul className="file-list">
        {extras.map((item) => (
          <li key={item.filename}>
            <a href={artifactUrl(jobId, item.filename)} target="_blank" rel="noreferrer">
              {item.filename}
            </a>
            <small>{Math.max(1, Math.round(item.bytes / 1024))} KB</small>
          </li>
        ))}
      </ul>
    </div>
  );
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
