import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  createJob,
  getJob,
  loadConservation,
  loadHomologs,
  loadResidues,
  loadStructure,
  sendMessage,
} from "./api";
import type {
  ConservationColumn,
  HomologHit,
  Job,
  ResidueAnnotation,
  StructureSummary,
} from "./types";

const DEFAULT_OBJECTIVE =
  "Make IsPETase about 30% more resistant to heat. Preserve catalytic function.";

export function App() {
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [job, setJob] = useState<Job | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [homologs, setHomologs] = useState<HomologHit[]>([]);
  const [columns, setColumns] = useState<ConservationColumn[]>([]);
  const [structure, setStructure] = useState<StructureSummary | null>(null);
  const [residues, setResidues] = useState<ResidueAnnotation[]>([]);

  useEffect(() => {
    if (!job || job.status === "complete" || job.status === "failed") return;
    const timer = window.setInterval(() => {
      getJob(job.id).then(setJob).catch((err: Error) => setError(err.message));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status]);

  useEffect(() => {
    if (!job) return;
    const has = (name: string) => job.artifacts.some((item) => item.filename === name);
    if (has("homolog_search.json")) {
      loadHomologs(job.id).then(setHomologs).catch(() => undefined);
    }
    if (has("conservation.json")) {
      loadConservation(job.id).then(setColumns).catch(() => undefined);
    }
    if (has("structure_summary.json")) {
      loadStructure(job.id).then(setStructure).catch(() => undefined);
    }
    if (has("residue_annotations.json")) {
      loadResidues(job.id).then(setResidues).catch(() => undefined);
    }
  }, [job]);

  const triad = useMemo(
    () => residues.filter((row) => [160, 206, 237].includes(row.author_residue)),
    [residues],
  );

  async function onStart(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const created = await createJob(objective);
    setJob(created);
  }

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!job || !draft.trim()) return;
    const updated = await sendMessage(job.id, draft.trim());
    setJob(updated);
    setDraft("");
  }

  if (!job) {
    return (
      <form className="start" onSubmit={onStart}>
        <h1>Protein investigation</h1>
        <p className="hint">
          One job, one conversation. The backend runs bioctl on the committed
          IsPETase fixtures (MMseqs2, MAFFT, conservation, PDB 6EQE). Results
          are calculated, not experimental.
        </p>
        <textarea value={objective} onChange={(e) => setObjective(e.target.value)} />
        <button type="submit">Start job</button>
        {error ? <p className="limit">{error}</p> : null}
      </form>
    );
  }

  return (
    <div className="app">
      <header className="top">
        <h1>{job.title}</h1>
        <div className="meta">
          {job.playbook} · job {job.id}
        </div>
        <div className="pills">
          <span className="pill active">{job.status}</span>
          {job.active_agent ? <span className="pill">{job.active_agent}</span> : null}
          {job.active_stage ? <span className="pill">{job.active_stage}</span> : null}
        </div>
      </header>
      <div className="workspace">
        <section className="pane">
          <h2>Conversation</h2>
          <div className="thread">
            {job.messages.map((turn) => (
              <div className="turn" key={turn.id}>
                <div className={`speaker ${turn.speaker}`}>{turn.speaker}</div>
                <div>{turn.body}</div>
                {turn.artifact_ids.length ? (
                  <div className="cite">Cites {turn.artifact_ids.join(", ")}</div>
                ) : null}
              </div>
            ))}
          </div>
          <form className="composer" onSubmit={onSend}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask why a residue was protected, or add a constraint"
            />
            <button type="submit">Send</button>
          </form>
        </section>
        <section className="pane">
          <h2>Results</h2>
          <div className="results">
            {job.error ? <div className="card">{job.error}</div> : null}
            <HomologCard hits={homologs} />
            <ConservationCard columns={columns} />
            <StructureCard structure={structure} triad={triad} />
            {job.limitations.length ? (
              <div className="card">
                <h3>Limitations</h3>
                {job.limitations.map((item) => (
                  <p className="limit" key={item}>
                    {item}
                  </p>
                ))}
              </div>
            ) : (
              <p className="hint">Artifacts appear here as bioctl finishes each stage.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function HomologCard({ hits }: { hits: HomologHit[] }) {
  if (!hits.length) return null;
  return (
    <div className="card">
      <h3>Homologs ({hits.length})</h3>
      <table>
        <thead>
          <tr>
            <th>Accession</th>
            <th>Identity %</th>
            <th>E-value</th>
          </tr>
        </thead>
        <tbody>
          {hits.slice(0, 8).map((hit) => (
            <tr key={hit.accession}>
              <td>{hit.accession}</td>
              <td>{hit.percent_identity.toFixed(1)}</td>
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
      <h3>Conservation (target positions)</h3>
      <div className="heatmap" aria-label="conservation heatmap">
        {columns.map((col) => {
          const value = col.conservation ?? 0;
          const tone = Math.round(255 - value * 160);
          return (
            <div
              key={col.target_position}
              className="cell"
              title={`${col.target_residue}${col.target_position}: ${value.toFixed(2)}`}
              style={{ background: `rgb(${tone}, ${Math.round(tone * 0.92)}, ${Math.round(70 + value * 80)})` }}
            />
          );
        })}
      </div>
    </div>
  );
}

function StructureCard({
  structure,
  triad,
}: {
  structure: StructureSummary | null;
  triad: ResidueAnnotation[];
}) {
  if (!structure) return null;
  const top = structure.foldseek_hits?.[0];
  return (
    <div className="card">
      <h3>
        Structure {structure.deposition?.pdb_id ?? structure.structure_id} / {structure.chain}
      </h3>
      <p className="hint">
        Retrieved coordinates · {structure.modelled_residue_count} modelled residues
        {top ? ` · top Foldseek ${top.target}` : ""}
      </p>
      {triad.length ? (
        <table>
          <thead>
            <tr>
              <th>Author</th>
              <th>Target</th>
              <th>Conservation</th>
              <th>RSA</th>
            </tr>
          </thead>
          <tbody>
            {triad.map((row) => (
              <tr key={row.author_residue}>
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
