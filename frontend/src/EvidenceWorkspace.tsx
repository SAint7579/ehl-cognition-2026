import { useLayoutEffect, useRef, useState } from "react";
import { ArtifactImage, ArtifactLink } from "./Artifact";
import {
  EVIDENCE_TASKS,
  labelCapability,
  outputPresentation,
  visibleEvidenceTasks,
} from "./evidence";
import type {
  EvidenceTask,
  EvidenceTaskDefinition,
  EvidenceTaskId,
} from "./evidence";
import { StructureViewer } from "./StructureViewer";
import type {
  ArtifactInfo,
  CandidateSite,
  ConservationColumn,
  FinalResult,
  HomologHit,
  JsonValue,
  Job,
  ResidueAnnotation,
  ResearchPlan,
  ResearchSynthesis,
  ResearchWorkspace,
  SimulationResults,
  StructuredArtifact,
  StructureSummary,
} from "./types";

export type TableArtifact = {
  artifact: ArtifactInfo;
  filename: string;
  rows: string[][];
};

export function EvidenceWorkspace({
  job,
  tasks,
  selected,
  onSelect,
  tables,
  homologs,
  columns,
  structure,
  pdbText,
  triad,
  result,
  research,
  structuredArtifacts,
  focus,
  onFocus,
  working,
}: {
  job: Job;
  tasks: EvidenceTask[];
  selected: EvidenceTaskId;
  onSelect: (task: EvidenceTaskId) => void;
  tables: TableArtifact[];
  homologs: HomologHit[];
  columns: ConservationColumn[];
  structure: StructureSummary | null;
  pdbText: string | null;
  triad: ResidueAnnotation[];
  result: FinalResult | null;
  research: ResearchWorkspace | null;
  structuredArtifacts: StructuredArtifact[];
  focus: number | null;
  onFocus: (residue: number) => void;
  working: boolean;
}) {
  const task = tasks.find((item) => item.id === selected) ?? null;
  const objectiveRef = useRef<HTMLParagraphElement>(null);
  const [objectiveExpanded, setObjectiveExpanded] = useState(false);
  const [objectiveOverflows, setObjectiveOverflows] = useState(false);

  useLayoutEffect(() => {
    setObjectiveExpanded(false);
  }, [job.id, job.objective]);

  useLayoutEffect(() => {
    if (objectiveExpanded) return;
    const element = objectiveRef.current;
    if (element) setObjectiveOverflows(element.scrollHeight > element.clientHeight + 1);
  }, [job.objective, objectiveExpanded]);

  return (
    <section className="evidence">
      <header className="evidence-top">
        <div className="evidence-title-row">
          <div>
            <p className="eyebrow">Research brief</p>
            <h2>{job.title}</h2>
          </div>
          <StatusBadge job={job} working={working} />
        </div>
        <div className="evidence-objective-wrap">
          <p
            ref={objectiveRef}
            className={`evidence-objective ${objectiveExpanded ? "is-expanded" : ""}`}
          >
            {job.objective}
          </p>
          {objectiveOverflows ? (
            <button
              type="button"
              className="evidence-objective-toggle"
              onClick={() => setObjectiveExpanded((expanded) => !expanded)}
              aria-expanded={objectiveExpanded}
            >
              {objectiveExpanded ? "Show less" : "Show more"}
            </button>
          ) : null}
        </div>
        <div className="evidence-stats">
          <span>{visibleEvidenceTasks(tasks, research).length} tasks</span>
          <span>{job.artifacts.length} saved outputs</span>
          <span>Updated {formatDateTime(job.updated_at)}</span>
        </div>
        {job.capabilities.length ? (
          <div className="capability-list" aria-label="Research capabilities">
            {job.capabilities.map((capability) => (
              <span key={capability}>{labelCapability(capability)}</span>
            ))}
          </div>
        ) : null}
      </header>
      <div className="results">
        {job.error && !working ? <div className="card warn-card">{friendlyError(job.error)}</div> : null}
        {selected === "overview" || !task ? (
          <TaskOverview
            job={job}
            research={research}
            structuredArtifacts={structuredArtifacts}
            onSelect={onSelect}
          />
        ) : (
          <TaskEvidence
            job={job}
            task={task}
            tables={tables}
            homologs={homologs}
            columns={columns}
            structure={structure}
            pdbText={pdbText}
            triad={triad}
            result={result}
            research={research}
            structuredArtifacts={structuredArtifacts}
            focus={focus}
            onFocus={onFocus}
            working={working}
          />
        )}
        {job.limitations.length ? (
          <details className="notes">
            <summary>Scientific limitations</summary>
            {job.limitations.map((item) => (
              <p key={item}>{item}</p>
            ))}
          </details>
        ) : null}
      </div>
    </section>
  );
}

export function parseDelimited(text: string, filename: string): string[][] {
  const delimiter = filename.toLowerCase().endsWith(".tsv") ? "\t" : ",";
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 12)
    .map((line) => line.split(delimiter).slice(0, 8));
}

function StatusBadge({ job, working }: { job: Job; working: boolean }) {
  const state = job.error
    ? "Needs attention"
    : job.active_stage === "waiting_for_approval"
      ? "Approval needed"
      : job.active_stage === "waiting_for_user"
        ? "Your input"
        : working
          ? "Running"
          : "Ready";
  return <span className={`status-badge status-${job.error ? "error" : working ? "live" : "ready"}`}>{state}</span>;
}

function TaskOverview({
  job,
  research,
  structuredArtifacts,
  onSelect,
}: {
  job: Job;
  research: ResearchWorkspace | null;
  structuredArtifacts: StructuredArtifact[];
  onSelect: (task: EvidenceTaskId) => void;
}) {
  const fallback = finalResultArtifact(structuredArtifacts);
  return (
    <section className="task-overview" aria-label="Investigation task outputs">
      {research?.synthesis ? (
        <section className="final-result-view" aria-label="Final scientific result">
          <div className="final-result-heading">
            <div>
              <p className="eyebrow">Final result</p>
              <h3>What this investigation found</h3>
            </div>
            <button type="button" onClick={() => onSelect("synthesis")}>
              Open synthesis task →
            </button>
          </div>
          <SynthesisCard
            jobId={job.id}
            synthesis={research.synthesis}
            heading="Scientific conclusion"
          />
        </section>
      ) : fallback ? (
        <FinalResultFallback artifact={fallback} onOpen={() => onSelect("synthesis")} />
      ) : null}
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
  research,
  structuredArtifacts,
  focus,
  onFocus,
  working,
}: {
  job: Job;
  task: EvidenceTask;
  tables: TableArtifact[];
  homologs: HomologHit[];
  columns: ConservationColumn[];
  structure: StructureSummary | null;
  pdbText: string | null;
  triad: ResidueAnnotation[];
  result: FinalResult | null;
  research: ResearchWorkspace | null;
  structuredArtifacts: StructuredArtifact[];
  focus: number | null;
  onFocus: (residue: number) => void;
  working: boolean;
}) {
  const taskIndex = EVIDENCE_TASKS.findIndex((definition) => definition.id === task.id) + 1;
  const tableNames = new Set(task.artifacts.map((artifact) => artifact.filename));
  const taskTables = tables.filter((table) => tableNames.has(table.filename));
  const taskStructured = structuredArtifacts.filter((item) =>
    tableNames.has(item.artifact.filename),
  );
  const taskFigures = figures(task.artifacts);
  return (
    <section className="task-evidence" aria-label={`${task.title} evidence`}>
      <header className="task-context">
        <p className="eyebrow">Task {String(taskIndex).padStart(2, "0")}</p>
        <h3>{task.title}</h3>
        <p>{task.purpose}</p>
        {task.summary ? (
          <div className="task-recap">
            <span>Latest interpretation</span>
            <p>{task.summary}</p>
          </div>
        ) : null}
      </header>
      {task.id === "plan" && research?.plan ? <ResearchPlanCard plan={research.plan} /> : null}
      {task.id === "synthesis" && research?.synthesis ? (
        <SynthesisCard jobId={job.id} synthesis={research.synthesis} />
      ) : null}
      {task.id === "simulation" && research?.simulations ? (
        <SimulationCard simulations={research.simulations} />
      ) : null}
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
      <StructuredDataCards
        artifacts={taskStructured}
        task={task}
        exclude={specializedJson(task.id, research)}
      />
      {!task.artifacts.length ? (
        <div className="card task-empty">
          <div className="empty-icon" aria-hidden="true">○</div>
          <h3>{working ? "Output is still being generated" : "No separate file for this task"}</h3>
          <p className="card-meta">
            {working
              ? "Saved outputs will appear here as soon as Devin attaches them."
              : "The context is preserved in the task summary and execution log."}
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
      <p className="card-meta">Every file remains attached to the stage that produced it.</p>
      <ul>
        {task.artifacts.map((artifact) => {
          const presentation = outputPresentation(artifact, task);
          return (
            <li key={artifact.id}>
              <span className="file-type">{fileType(artifact.filename)}</span>
              <div>
                <strong>{presentation.title}</strong>
                <p>{presentation.purpose}</p>
                <small>
                  {artifact.filename} · {formatBytes(artifact.bytes)}
                </small>
              </div>
              <ArtifactLink jobId={jobId} filename={artifact.filename}>
                Open
              </ArtifactLink>
            </li>
          );
        })}
      </ul>
    </div>
  );
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
              <ArtifactImage jobId={jobId} filename={item.filename} alt={presentation.title} />
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
        const presentation = outputPresentation(table.artifact, task);
        return (
          <div className="card table-card" key={table.filename}>
            <p className="card-kicker">Generated table</p>
            <h3>{presentation.title}</h3>
            <p className="card-meta">{presentation.purpose}</p>
            <div className="table-scroll">
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
          </div>
        );
      })}
    </>
  );
}

function ResearchPlanCard({ plan }: { plan: ResearchPlan }) {
  const complete = plan.tasks.filter((task) => task.status === "COMPLETED").length;
  return (
    <div className="card plan-card">
      <div className="card-heading-row">
        <div>
          <p className="card-kicker">Interactive research plan</p>
          <h3>How Devin is answering the question</h3>
        </div>
        <span className="plan-progress">{complete}/{plan.tasks.length} complete</span>
      </div>
      <p className="card-meta plan-strategy">{plan.strategy}</p>
      <div className="plan-steps">
        {plan.tasks.map((task, index) => (
          <article className={`plan-step plan-${task.status.toLowerCase()}`} key={task.id}>
            <span className="plan-step-index">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <div className="plan-step-title">
                <strong>{task.title}</strong>
                <span>{labelStatus(task.status)}</span>
              </div>
              <p>{task.purpose}</p>
              {task.methods.length ? (
                <div className="method-list">
                  {task.methods.map((method) => <span key={method}>{method}</span>)}
                </div>
              ) : null}
              {task.output_files.length ? (
                <small>Outputs: {task.output_files.join(", ")}</small>
              ) : null}
            </div>
          </article>
        ))}
      </div>
      {plan.required_inputs.length || plan.assumptions.length ? (
        <div className="plan-notes-grid">
          <TextList title="Required inputs" items={plan.required_inputs} />
          <TextList title="Assumptions" items={plan.assumptions} />
        </div>
      ) : null}
    </div>
  );
}

function SynthesisCard({
  jobId,
  synthesis,
  heading = "Evidence convergence and confidence",
}: {
  jobId: string;
  synthesis: ResearchSynthesis;
  heading?: string;
}) {
  const counts = ["HIGH", "MEDIUM", "LOW", "NOT_ASSESSED"].map((confidence) => ({
    confidence,
    count: synthesis.findings.filter((finding) => finding.confidence === confidence).length,
  }));
  const max = Math.max(1, ...counts.map((item) => item.count));
  return (
    <div className="card synthesis-card">
      <p className="card-kicker">Scientific synthesis</p>
      <h3>{heading}</h3>
      <p className="synthesis-summary">{synthesis.summary}</p>
      {synthesis.findings.length ? (
        <>
          <div className="confidence-chart" aria-label="Finding confidence distribution">
            {counts.map((item) => (
              <div className="confidence-column" key={item.confidence}>
                <span>{item.count}</span>
                <div>
                  <i
                    className={`confidence-fill confidence-${item.confidence.toLowerCase()}`}
                    style={{ height: `${Math.max(item.count ? 12 : 2, (item.count / max) * 100)}%` }}
                  />
                </div>
                <small>{labelStatus(item.confidence)}</small>
              </div>
            ))}
          </div>
          <div className="finding-list">
            {synthesis.findings.map((finding) => (
              <article className="finding" key={`${finding.title}-${finding.statement}`}>
                <div className="finding-heading">
                  <strong>{finding.title}</strong>
                  <span className={`confidence-pill confidence-${finding.confidence.toLowerCase()}`}>
                    {labelStatus(finding.confidence)}
                  </span>
                </div>
                <p>{finding.statement}</p>
                {finding.implications.length ? (
                  <div className="finding-implication">
                    <span>Why it matters</span>
                    {finding.implications.map((item) => <p key={item}>{item}</p>)}
                  </div>
                ) : null}
                {finding.evidence_files.length ? (
                  <div className="evidence-file-list">
                    {finding.evidence_files.map((filename) => (
                      <ArtifactLink jobId={jobId} filename={filename} key={filename}>
                        {filename}
                      </ArtifactLink>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </>
      ) : null}
      <div className="synthesis-grid">
        <TextList title="Evidence agrees" items={synthesis.agreements} tone="positive" />
        <TextList title="Evidence conflicts" items={synthesis.disagreements} tone="warning" />
        <TextList title="Knowledge gaps" items={synthesis.knowledge_gaps} />
        <TextList title="Recommended next steps" items={synthesis.recommended_next_steps} />
      </div>
      <TextList title="Limitations" items={synthesis.limitations} tone="muted" />
    </div>
  );
}

function FinalResultFallback({
  artifact,
  onOpen,
}: {
  artifact: StructuredArtifact;
  onOpen: () => void;
}) {
  return (
    <section className="final-result-view" aria-label="Final structured result">
      <div className="final-result-heading">
        <div>
          <p className="eyebrow">Final result</p>
          <h3>{artifact.artifact.title}</h3>
          <p>{artifact.artifact.purpose}</p>
        </div>
        <button type="button" onClick={onOpen}>
          Open synthesis task →
        </button>
      </div>
      <div className="card structured-card final-result-fallback">
        <div className="structured-content">
          <JsonValueView value={artifact.value} />
        </div>
      </div>
    </section>
  );
}

function SimulationCard({ simulations }: { simulations: SimulationResults }) {
  return (
    <div className="card simulation-card">
      <p className="card-kicker">Calculated results</p>
      <h3>Simulation and docking readout</h3>
      <p className="synthesis-summary">{simulations.summary}</p>
      <div className="simulation-runs">
        {simulations.runs.map((run) => (
          <article className="simulation-run" key={run.id}>
            <div className="simulation-run-heading">
              <div>
                <strong>{run.question}</strong>
                <small>{run.engine} · {run.method}</small>
              </div>
              <span className={`run-status run-${run.status.toLowerCase()}`}>
                {labelStatus(run.status)}
              </span>
            </div>
            {run.metrics.length ? (
              <div className="metric-grid">
                {run.metrics.map((metric) => (
                  <div className="metric" key={`${run.id}-${metric.name}`}>
                    <span>{labelKey(metric.name)}</span>
                    <strong>
                      {formatScalar(metric.value)}
                      {metric.unit ? <small> {metric.unit}</small> : null}
                    </strong>
                    <p>{metric.interpretation}</p>
                  </div>
                ))}
              </div>
            ) : null}
            <p className="run-interpretation">{run.interpretation}</p>
            {Object.keys(run.parameters).length ? (
              <details className="run-parameters">
                <summary>Parameters</summary>
                <dl>
                  {Object.entries(run.parameters).map(([key, value]) => (
                    <div key={key}>
                      <dt>{labelKey(key)}</dt>
                      <dd>{formatScalar(value)}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            ) : null}
            <TextList title="Calculation limitations" items={run.limitations} tone="muted" />
          </article>
        ))}
      </div>
      <TextList title="Recommended next steps" items={simulations.recommended_next_steps} />
    </div>
  );
}

function StructuredDataCards({
  artifacts,
  task,
  exclude,
}: {
  artifacts: StructuredArtifact[];
  task: EvidenceTaskDefinition;
  exclude: Set<string>;
}) {
  const visible = artifacts.filter((item) => !exclude.has(item.artifact.filename));
  if (!visible.length) return null;
  return (
    <>
      {visible.map(({ artifact, value }) => {
        const presentation = outputPresentation(artifact, task);
        return (
          <details className="card structured-card" key={artifact.id}>
            <summary>
              <span className="structured-icon">{"{ }"}</span>
              <span>
                <small>Structured data · view inline</small>
                <strong>{presentation.title}</strong>
                <em>{presentation.purpose}</em>
              </span>
              <i aria-hidden="true">⌄</i>
            </summary>
            <div className="structured-content">
              <JsonValueView value={value} />
            </div>
          </details>
        );
      })}
    </>
  );
}

function JsonValueView({ value, label }: { value: JsonValue; label?: string }) {
  if (value === null || typeof value !== "object") {
    return (
      <div className="json-leaf">
        {label ? <dt>{labelKey(label)}</dt> : null}
        <dd>{formatScalar(value)}</dd>
      </div>
    );
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return (
        <div className="json-leaf">
          {label ? <dt>{labelKey(label)}</dt> : null}
          <dd>None</dd>
        </div>
      );
    }
    return (
      <div className="json-group">
        {label ? <h4>{labelKey(label)}</h4> : null}
        <div className="json-array">
          {value.map((item, index) => (
            <div className="json-array-item" key={index}>
              <span>{index + 1}</span>
              <JsonValueView value={item} />
            </div>
          ))}
        </div>
      </div>
    );
  }
  return (
    <dl className="json-object">
      {Object.entries(value).map(([key, item]) => (
        <JsonValueView value={item} label={key} key={key} />
      ))}
    </dl>
  );
}

function TextList({
  title,
  items,
  tone = "default",
}: {
  title: string;
  items: string[];
  tone?: "default" | "positive" | "warning" | "muted";
}) {
  if (!items.length) return null;
  return (
    <section className={`text-list text-list-${tone}`}>
      <h4>{title}</h4>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  );
}

function HomologCard({ hits }: { hits: HomologHit[] }) {
  if (!hits.length) return null;
  return (
    <div className="card table-card">
      <p className="card-kicker">Interpreted result</p>
      <h3>Homolog search results</h3>
      <p className="card-meta">
        {hits.length} related sequences define the evolutionary comparison set.
      </p>
      <div className="table-scroll">
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
      <div className="heatmap" aria-label="Conservation heatmap">
        {columns.map((column) => {
          const value = column.conservation ?? 0;
          return (
            <div
              key={column.target_position}
              className="cell"
              title={`${column.target_residue}${column.target_position}: ${value.toFixed(2)}`}
              style={{ opacity: 0.2 + value * 0.8 }}
            />
          );
        })}
      </div>
      <div className="heatmap-legend">
        <span>Variable</span>
        <span>Conserved</span>
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
      <h3>{structureId ? `${structureId} · structure context` : "Target structure context"}</h3>
      <p className="card-meta">
        Deposited coordinates with catalytic and ranked residues highlighted
        {structure ? ` · ${structure.modelled_residue_count} modelled residues` : ""}
        {top ? ` · closest Foldseek ${top.target}` : ""}.
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
        <span><i className="swatch triad" />Catalytic triad</span>
        <span><i className="swatch activity" />Activity sites</span>
        <span><i className="swatch stability" />Stability sites</span>
      </div>
      {triad.length ? (
        <div className="table-scroll">
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
                  <td>{row.one_letter}{row.author_residue}</td>
                  <td>{row.target_position ?? "—"}</td>
                  <td>{row.conservation?.toFixed(2) ?? "—"}</td>
                  <td>{row.rsa?.toFixed(2) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
    <div className="card table-card">
      <p className="card-kicker">Decision support</p>
      <h3>Ranked engineering candidates</h3>
      <p className="card-meta">
        Heuristic hypotheses for activity and stability. Select a residue to inspect it in 3D.
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
      <div className="table-scroll">
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
                <td>{site.one_letter}{site.author_residue}</td>
                <td>{site.score.toFixed(2)}</td>
                <td>{site.conservation.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function figures(artifacts: ArtifactInfo[]): ArtifactInfo[] {
  return artifacts.filter((item) => /\.(png|jpe?g|webp|gif|svg)$/i.test(item.filename));
}

function specializedJson(
  task: EvidenceTaskId,
  research: ResearchWorkspace | null,
): Set<string> {
  const names: Partial<Record<EvidenceTaskId, string | null>> = {
    plan: research?.plan ? research.plan_filename : null,
    synthesis: research?.synthesis ? research.synthesis_filename : null,
    simulation: research?.simulations ? research.simulations_filename : null,
  };
  const filename = names[task];
  return new Set(filename ? [filename] : []);
}

function finalResultArtifact(artifacts: StructuredArtifact[]): StructuredArtifact | null {
  const candidates = artifacts.filter((item) => item.artifact.stage === "synthesis");
  const rank = (filename: string) => {
    const name = filename.toLowerCase();
    if (name === "synthesis.json") return 0;
    if (name.includes("synthesis")) return 1;
    if (name.includes("summary") || name.includes("conclusion")) return 2;
    if (name === "final_result.json") return 3;
    return 4;
  };
  return candidates.sort(
    (left, right) => rank(left.artifact.filename) - rank(right.artifact.filename),
  )[0] ?? null;
}

function labelKey(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function labelStatus(value: string): string {
  return labelKey(value.toLowerCase());
}

function formatScalar(value: string | number | boolean | null): string {
  if (value === null) return "Not specified";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toPrecision(4);
  return value || "Not specified";
}

function fileType(filename: string): string {
  const extension = filename.split(".").at(-1);
  return (extension ?? "file").slice(0, 4).toUpperCase();
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : date.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function friendlyError(error: string): string {
  const text = error.toLowerCase();
  if (text.includes("no route") || text.includes("errno 65") || text.includes("timed out") || text.includes("connection")) {
    return "The sandbox connection was interrupted. Earlier outputs are safe; retry the last follow-up.";
  }
  if (text.includes("attachment")) return "The sandbox finished and result files are still being restored.";
  if (text.includes("not on this mac") || text.includes("devin")) {
    return "The Devin sandbox is unavailable. Check the backend environment configuration.";
  }
  return "The sandbox could not finish this turn. Retry the follow-up or start a new investigation.";
}
