import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArtifactImage } from "./Artifact";
import type { EvidenceTask, EvidenceTaskId } from "./evidence";
import {
  buildEvidenceTasks,
  EVIDENCE_TASK_CAPABILITIES,
  evidenceTaskForStage,
  labelCapability,
  matchingResearchTask,
  visibleEvidenceTasks,
} from "./evidence";
import type {
  ArtifactInfo,
  ConservationColumn,
  FinalResult,
  Job,
  ResearchTask,
  ResearchWorkspace,
  ResidueAnnotation,
} from "./types";
import "./investigation-graph.css";

type GraphStatus = "RUNNING" | "COMPLETED" | "FAILED" | "PLANNED";

type GraphNode = {
  id: EvidenceTaskId;
  title: string;
  shortTitle: string;
  capability: string;
  summary: string | null;
  methods: string[];
  outputs: number;
  artifacts: ArtifactInfo[];
  updatedAt: string | null;
  status: GraphStatus;
  column: number;
  lane: number;
};

type GraphEdge = {
  from: EvidenceTaskId;
  to: EvidenceTaskId;
};

type PointerPoint = {
  x: number;
  y: number;
};

const NODE_WIDTH = 226;
const NODE_HEIGHT = 150;
const COLUMN_WIDTH = 264;
const ROW_HEIGHT = 178;
const PAD_X = 34;
const PAD_Y = 30;
const ZOOM_MIN = 0.45;
const ZOOM_MAX = 1.65;

const COLUMN_LABELS = ["Question", "Plan", "Gather", "Derive", "Rank", "Synthesis", "Follow-up"];

const DEPENDENCIES: Record<EvidenceTaskId, { column: number; parents: EvidenceTaskId[] }> = {
  overview: { column: 0, parents: [] },
  plan: { column: 1, parents: ["overview"] },
  literature: { column: 2, parents: ["plan"] },
  "homolog-search": { column: 2, parents: ["plan"] },
  conservation: { column: 3, parents: ["homolog-search"] },
  structure: { column: 3, parents: ["plan"] },
  analysis: { column: 3, parents: ["plan"] },
  simulation: { column: 3, parents: ["structure", "plan"] },
  rank: { column: 4, parents: ["conservation", "structure", "analysis", "simulation"] },
  synthesis: {
    column: 5,
    parents: ["rank", "literature", "homolog-search", "conservation", "structure", "analysis", "simulation"],
  },
  "follow-up": { column: 6, parents: ["synthesis"] },
  other: { column: 6, parents: ["plan"] },
};

const STATUS_LABEL: Record<GraphStatus, string> = {
  RUNNING: "Running",
  COMPLETED: "Completed",
  FAILED: "Failed",
  PLANNED: "Planned",
};

export function InvestigationGraph({
  job,
  working,
  research,
  columns,
  pdbText,
  triad,
  result,
  selected,
  onSelect,
}: {
  job: Job;
  working: boolean;
  research: ResearchWorkspace | null;
  columns: ConservationColumn[];
  pdbText: string | null;
  triad: ResidueAnnotation[];
  result: FinalResult | null;
  selected: EvidenceTaskId;
  onSelect: (task: EvidenceTaskId) => void;
}) {
  const tasks = useMemo(() => buildEvidenceTasks(job), [job]);
  const nodes = useMemo(() => buildNodes(job, tasks, research, working), [job, research, tasks, working]);
  const edges = useMemo(() => buildEdges(nodes), [nodes]);
  const survivingIds = useMemo(() => new Set(nodes.map((node) => node.id)), [nodes]);
  const selectedId = survivingIds.has(selected) ? selected : "overview";
  const activeId = working && job.active_stage
    ? evidenceTaskForStage(job.active_stage)
    : working
      ? "overview"
      : null;
  const lineage = useMemo(
    () => getLineage(selectedId, edges),
    [edges, selectedId],
  );
  const maxLane = Math.max(0, ...nodes.map((node) => node.lane));
  const maxColumn = Math.max(0, ...nodes.map((node) => node.column));
  const width = PAD_X * 2 + maxColumn * COLUMN_WIDTH + NODE_WIDTH;
  const height = PAD_Y * 2 + maxLane * ROW_HEIGHT + NODE_HEIGHT + 24;
  const nodeSetKey = nodes.map((node) => node.id).join("|");
  const columnLabelTops = new Map<number, number>();
  for (const node of nodes) {
    const top = columnLabelTops.get(node.column);
    const nodeTop = nodeY(node);
    if (top == null || nodeTop < top) columnLabelTops.set(node.column, nodeTop);
  }

  const [zoom, setZoom] = useState(1);
  const [followLive, setFollowLive] = useState(true);
  const [panning, setPanning] = useState(false);
  const autoFitRef = useRef(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef(1);
  const anchorRef = useRef<{ cx: number; cy: number; ax: number; ay: number } | null>(null);
  const panRef = useRef<{ x: number; y: number; sl: number; st: number } | null>(null);
  const pointersRef = useRef(new Map<number, PointerPoint>());
  const pinchRef = useRef<{ distance: number; zoom: number } | null>(null);
  const nodeRefs = useRef(new Map<EvidenceTaskId, HTMLButtonElement>());

  const applyZoom = useCallback((next: number, clientX?: number, clientY?: number) => {
    autoFitRef.current = false;
    const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
    const element = scrollRef.current;
    if (element) {
      const rect = element.getBoundingClientRect();
      const ax = clientX == null ? element.clientWidth / 2 : clientX - rect.left;
      const ay = clientY == null ? element.clientHeight / 2 : clientY - rect.top;
      anchorRef.current = {
        cx: (element.scrollLeft + ax) / zoomRef.current,
        cy: (element.scrollTop + ay) / zoomRef.current,
        ax,
        ay,
      };
    }
    setZoom(clamped);
  }, []);

  useLayoutEffect(() => {
    zoomRef.current = zoom;
    const element = scrollRef.current;
    const anchor = anchorRef.current;
    if (!element || !anchor) return;
    element.scrollLeft = anchor.cx * zoom - anchor.ax;
    element.scrollTop = anchor.cy * zoom - anchor.ay;
    anchorRef.current = null;
  }, [zoom]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      applyZoom(zoomRef.current * (1 - event.deltaY * 0.0018), event.clientX, event.clientY);
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [applyZoom]);

  const scrollToNode = useCallback((id: EvidenceTaskId) => {
    const element = scrollRef.current;
    const node = nodeRefs.current.get(id);
    if (!element || !node) return;
    element.scrollTo({
      left: Math.max(0, node.offsetLeft * zoom - (element.clientWidth - NODE_WIDTH * zoom) / 2),
      top: Math.max(0, node.offsetTop * zoom - (element.clientHeight - NODE_HEIGHT * zoom) / 2),
      behavior: "smooth",
    });
  }, [zoom]);

  const fitToView = useCallback(() => {
    autoFitRef.current = true;
    const element = scrollRef.current;
    if (!element) return;
    const scale = Math.min(
      (element.clientWidth - 24) / width,
      (element.clientHeight - 24) / height,
      1,
    );
    anchorRef.current = null;
    element.scrollLeft = 0;
    element.scrollTop = 0;
    setZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, scale)));
  }, [height, width]);

  useLayoutEffect(() => {
    if (autoFitRef.current) fitToView();
  }, [fitToView, nodeSetKey]);

  useEffect(() => {
    if (!followLive || !activeId || !survivingIds.has(activeId)) return;
    onSelect(activeId);
    scrollToNode(activeId);
  }, [activeId, followLive, onSelect, scrollToNode, survivingIds]);

  useEffect(() => {
    if (!survivingIds.has(selected)) onSelect("overview");
  }, [onSelect, selected, survivingIds]);

  function selectNode(id: EvidenceTaskId) {
    setFollowLive(false);
    onSelect(id);
  }

  return (
    <section className="investigation-graph" aria-label="Investigation graph">
      <header className="investigation-graph-heading">
        <div>
          <p className="eyebrow">Investigation graph</p>
          <h2>Question to evidence, task by task</h2>
          <p className="investigation-graph-meta">
            {nodes.length - 1} evidence tasks · {job.artifacts.length} saved outputs
          </p>
        </div>
        <div className="investigation-graph-actions">
          {!followLive ? (
            <button type="button" className="follow-live" onClick={() => setFollowLive(true)}>
              Follow live
            </button>
          ) : (
            <span className={`live-state ${working ? "is-live" : ""}`}>
              <span />
              {working ? "Live" : "Latest"}
            </span>
          )}
          <div className="investigation-graph-zoom" aria-label="Graph zoom controls">
            <button
              type="button"
              onClick={() => applyZoom(zoom - 0.15)}
              aria-label="Zoom out"
              disabled={zoom <= ZOOM_MIN}
            >
              −
            </button>
            <button
              type="button"
              className="zoom-level"
              onClick={() => applyZoom(1)}
              title="Reset to 100%"
            >
              {Math.round(zoom * 100)}%
            </button>
            <button
              type="button"
              onClick={() => applyZoom(zoom + 0.15)}
              aria-label="Zoom in"
              disabled={zoom >= ZOOM_MAX}
            >
              +
            </button>
            <button type="button" className="zoom-fit" onClick={fitToView}>
              Fit
            </button>
          </div>
        </div>
      </header>
      <div
        className={`investigation-graph-scroll ${panning ? "is-panning" : ""}`}
        ref={scrollRef}
        onPointerDown={(event) => {
          const target = event.target;
          if (target instanceof Element && target.closest(".investigation-graph-node")) return;
          autoFitRef.current = false;
          pointersRef.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
          if (pointersRef.current.size === 2) {
            pinchRef.current = {
              distance: pointerDistance(pointersRef.current),
              zoom: zoomRef.current,
            };
            panRef.current = null;
            setPanning(false);
          } else {
            panRef.current = {
              x: event.clientX,
              y: event.clientY,
              sl: event.currentTarget.scrollLeft,
              st: event.currentTarget.scrollTop,
            };
            setPanning(true);
          }
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const element = scrollRef.current;
          if (!element) return;
          pointersRef.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
          const pinch = pinchRef.current;
          if (pinch && pointersRef.current.size >= 2) {
            const points = [...pointersRef.current.values()];
            const center = {
              x: (points[0].x + points[1].x) / 2,
              y: (points[0].y + points[1].y) / 2,
            };
            applyZoom(
              pinch.zoom * (pointerDistance(pointersRef.current) / pinch.distance),
              center.x,
              center.y,
            );
            return;
          }
          const pan = panRef.current;
          if (!pan) return;
          element.scrollLeft = pan.sl - (event.clientX - pan.x);
          element.scrollTop = pan.st - (event.clientY - pan.y);
        }}
        onPointerUp={(event) => {
          pointersRef.current.delete(event.pointerId);
          pinchRef.current = pointersRef.current.size < 2 ? null : pinchRef.current;
          panRef.current = null;
          setPanning(false);
          if (scrollRef.current?.hasPointerCapture(event.pointerId)) {
            scrollRef.current.releasePointerCapture(event.pointerId);
          }
        }}
        onPointerCancel={() => {
          pointersRef.current.clear();
          pinchRef.current = null;
          panRef.current = null;
          setPanning(false);
        }}
      >
        <div
          className="investigation-graph-stage"
          style={{ width: width * zoom, height: height * zoom }}
        >
          <div
            className="investigation-graph-canvas"
            style={{ width, height, transform: `scale(${zoom})` }}
          >
            <div className="investigation-graph-columns" aria-hidden>
              {COLUMN_LABELS.map((label, column) => (
                <span
                  key={label}
                  style={{
                    left: PAD_X + column * COLUMN_WIDTH,
                    top: Math.max(8, (columnLabelTops.get(column) ?? PAD_Y) - 20),
                    width: NODE_WIDTH,
                  }}
                >
                  {label}
                </span>
              ))}
            </div>
            <svg
              className="investigation-graph-edges"
              width={width}
              height={height}
              aria-hidden="true"
            >
              {edges.map((edge) => {
                const from = nodes.find((node) => node.id === edge.from);
                const to = nodes.find((node) => node.id === edge.to);
                if (!from || !to) return null;
                const x1 = nodeX(from) + NODE_WIDTH;
                const y1 = nodeY(from) + NODE_HEIGHT / 2;
                const x2 = nodeX(to);
                const y2 = nodeY(to) + NODE_HEIGHT / 2;
                const bend = Math.max(32, (x2 - x1) * 0.5);
                const lit = lineage.has(edge.from) && lineage.has(edge.to);
                return (
                  <path
                    key={`${edge.from}-${edge.to}`}
                    d={`M${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`}
                    className={`investigation-graph-edge ${lit ? "is-lit" : ""}`}
                  />
                );
              })}
            </svg>
            {nodes.map((node) => {
              const dimmed = lineage.size > 0 && !lineage.has(node.id);
              const selectedNode = node.id === selectedId;
              return (
                <button
                  type="button"
                  key={node.id}
                  ref={(element) => {
                    if (element) nodeRefs.current.set(node.id, element);
                    else nodeRefs.current.delete(node.id);
                  }}
                  className={`investigation-graph-node status-${node.status.toLowerCase()} ${selectedNode ? "is-selected" : ""} ${dimmed ? "is-dimmed" : ""}`}
                  style={{ left: nodeX(node), top: nodeY(node) }}
                  onClick={() => selectNode(node.id)}
                  aria-pressed={selectedNode}
                  aria-current={selectedNode ? "step" : undefined}
                >
                  <span className="investigation-graph-node-top">
                    <span className="investigation-graph-capability">{node.capability}</span>
                    <span className="investigation-graph-status">
                      {node.status === "RUNNING" ? <span className="investigation-graph-pulse" /> : null}
                      {STATUS_LABEL[node.status]}
                    </span>
                  </span>
                  <strong>{node.title}</strong>
                  <span className="investigation-graph-body">
                    <NodeBody
                      jobId={job.id}
                      node={node}
                      columns={columns}
                      research={research}
                      pdbText={pdbText}
                      triad={triad}
                      result={result}
                    />
                  </span>
                  <span className="investigation-graph-footer">
                    {node.outputs > 0 ? (
                      <span>
                        ◆ {node.outputs} output{node.outputs === 1 ? "" : "s"}
                      </span>
                    ) : null}
                    <time dateTime={node.updatedAt ?? undefined}>
                      {node.updatedAt ? formatTime(node.updatedAt) : "—"}
                    </time>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

function buildNodes(
  job: Job,
  tasks: EvidenceTask[],
  research: ResearchWorkspace | null,
  working: boolean,
): GraphNode[] {
  const planMatches = new Map<EvidenceTaskId, ResearchTask>();
  for (const task of tasks) {
    const planTask = matchingResearchTask(task, research);
    if (planTask) planMatches.set(task.id, planTask);
  }

  const activeId = job.active_stage ? evidenceTaskForStage(job.active_stage) : null;
  const failedIds = new Set<EvidenceTaskId>();
  for (const event of job.events) {
    if (event.type === "agent.error" && event.stage) {
      failedIds.add(evidenceTaskForStage(event.stage));
    }
  }
  if (job.status === "failed" && activeId) failedIds.add(activeId);

  const objective: GraphNode = {
    id: "overview",
    title: "Investigation objective",
    shortTitle: "Objective",
    capability: labelCapability("request"),
    summary: job.objective,
    methods: [],
    outputs: 0,
    artifacts: [],
    updatedAt: job.updated_at,
    status: job.status === "failed" ? "FAILED" : working ? "RUNNING" : "COMPLETED",
    column: 0,
    lane: 0,
  };
  const contentTasks = visibleEvidenceTasks(tasks, research);
  const nodes = [
    objective,
    ...contentTasks.map((task): GraphNode => {
      const planTask = planMatches.get(task.id);
      const status = deriveStatus(task, planTask, activeId, failedIds, working);
      return {
        id: task.id,
        title: task.title,
        shortTitle: task.shortTitle,
        capability: labelCapability(EVIDENCE_TASK_CAPABILITIES[task.id]),
        summary: task.summary,
        methods: planTask?.methods ?? [],
        outputs: task.artifacts.length,
        artifacts: task.artifacts,
        updatedAt: task.updatedAt ?? (task.artifacts.length || planTask ? job.updated_at : null),
        status,
        column: DEPENDENCIES[task.id].column,
        lane: 0,
      };
    }),
  ];
  const counts = new Map<number, number>();
  for (const node of nodes) counts.set(node.column, (counts.get(node.column) ?? 0) + 1);
  const maxCount = Math.max(1, ...counts.values());
  const lanes = new Map<number, number>();
  for (const node of nodes) {
    const lane = lanes.get(node.column) ?? 0;
    node.lane = lane + (maxCount - (counts.get(node.column) ?? 1)) / 2;
    lanes.set(node.column, lane + 1);
  }
  return nodes;
}

function deriveStatus(
  task: EvidenceTask,
  planTask: ResearchTask | undefined,
  activeId: EvidenceTaskId | null,
  failedIds: Set<EvidenceTaskId>,
  working: boolean,
): GraphStatus {
  if (working && activeId === task.id) return "RUNNING";
  if (failedIds.has(task.id) || planTask?.status === "FAILED") return "FAILED";
  if (task.artifacts.length || task.summary) return "COMPLETED";
  if (planTask?.status === "PLANNED" || planTask?.status === "BLOCKED") return "PLANNED";
  if (planTask?.status === "RUNNING") return "RUNNING";
  return "PLANNED";
}

function buildEdges(nodes: GraphNode[]): GraphEdge[] {
  const surviving = new Set(nodes.map((node) => node.id));
  const edges: GraphEdge[] = [];
  const seen = new Set<string>();
  for (const child of nodes) {
    if (child.id === "overview") continue;
    for (const parent of survivingParents(child.id, surviving, new Set())) {
      const key = `${parent}-${child.id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      edges.push({ from: parent, to: child.id });
    }
  }
  return edges;
}

function survivingParents(
  childId: EvidenceTaskId,
  surviving: Set<EvidenceTaskId>,
  visited: Set<EvidenceTaskId>,
): EvidenceTaskId[] {
  return DEPENDENCIES[childId].parents.flatMap((parent) => {
    if (surviving.has(parent)) return [parent];
    if (visited.has(parent)) return [];
    visited.add(parent);
    return survivingParents(parent, surviving, visited);
  });
}

function getLineage(selected: EvidenceTaskId, edges: GraphEdge[]): Set<EvidenceTaskId> {
  const lineage = new Set<EvidenceTaskId>([selected]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of edges) {
      if (lineage.has(edge.to) && !lineage.has(edge.from)) {
        lineage.add(edge.from);
        changed = true;
      }
      if (lineage.has(edge.from) && !lineage.has(edge.to)) {
        lineage.add(edge.to);
        changed = true;
      }
    }
  }
  return lineage;
}

function nodeX(node: GraphNode): number {
  return PAD_X + node.column * COLUMN_WIDTH;
}

function nodeY(node: GraphNode): number {
  return PAD_Y + node.lane * ROW_HEIGHT;
}

function NodeBody({
  jobId,
  node,
  columns,
  research,
  pdbText,
  triad,
  result,
}: {
  jobId: string;
  node: GraphNode;
  columns: ConservationColumn[];
  research: ResearchWorkspace | null;
  result: FinalResult | null;
  pdbText: string | null;
  triad: ResidueAnnotation[];
}) {
  const image = node.artifacts.find((artifact) => /\.(png|jpe?g|webp|svg)$/i.test(artifact.filename));
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [image?.filename]);

  if (image && !imageFailed) {
    return (
      <span className="investigation-graph-thumb">
        <ArtifactImage
          jobId={jobId}
          filename={image.filename}
          alt=""
          onError={() => setImageFailed(true)}
        />
      </span>
    );
  }

  if (node.id === "structure") {
    const trace = parseBackboneTrace(pdbText, triad);
    if (trace) {
      return (
        <span className="investigation-graph-thumb">
          <StructureTrace trace={trace} />
        </span>
      );
    }
  }

  const values = sparklineValues(node, columns, research, result);
  if (values.length >= 2) {
    return (
      <span className="investigation-graph-thumb">
        <Sparkline values={values} />
      </span>
    );
  }

  if (node.summary) return node.summary;
  if (node.methods.length) {
    return (
      <span className="investigation-graph-methods">
        {node.methods.slice(0, 3).map((method) => (
          <em key={method}>{method}</em>
        ))}
      </span>
    );
  }
  return "No output recorded yet";
}

type BackbonePoint = {
  x: number;
  y: number;
  residue: number;
};

type CoordinatePoint = {
  x: number;
  y: number;
  z: number;
  residue: number;
};

type BackboneTrace = {
  points: BackbonePoint[];
  marks: BackbonePoint[];
};

const MAX_TRACE_POINTS = 80;
const TRACE_SEGMENTS = 10;

function parseBackboneTrace(pdbText: string | null, triad: ResidueAnnotation[]): BackboneTrace | null {
  if (!pdbText) return null;
  const points: CoordinatePoint[] = [];
  const seenResidues = new Set<string>();
  let chain: string | null = null;
  for (const line of pdbText.split(/\r?\n/)) {
    const record = line.slice(0, 6).trim();
    if (record !== "ATOM" && record !== "HETATM") continue;
    if (line.slice(12, 16).trim() !== "CA") continue;
    const pointChain = line.slice(21, 22);
    if (chain === null) chain = pointChain;
    if (pointChain !== chain) continue;
    const residue = Number.parseInt(line.slice(22, 26).trim(), 10);
    const x = Number.parseFloat(line.slice(30, 38).trim());
    const y = Number.parseFloat(line.slice(38, 46).trim());
    const z = Number.parseFloat(line.slice(46, 54).trim());
    if (
      !Number.isFinite(residue) ||
      !Number.isFinite(x) ||
      !Number.isFinite(y) ||
      !Number.isFinite(z)
    ) continue;
    const residueKey = `${pointChain}:${residue}`;
    if (seenResidues.has(residueKey)) continue;
    seenResidues.add(residueKey);
    points.push({ x, y, z, residue });
  }
  if (points.length < 2) return null;

  const centred = centrePoints(points);
  const firstAxis = principalAxis(covarianceMatrix(centred));
  const secondAxis = principalAxis(
    subtractOuterProduct(covarianceMatrix(centred), firstAxis),
  );
  const projected = points.map((point, index) => ({
    x: centred[index][0] * firstAxis[0] + centred[index][1] * firstAxis[1] + centred[index][2] * firstAxis[2],
    y: centred[index][0] * secondAxis[0] + centred[index][1] * secondAxis[1] + centred[index][2] * secondAxis[2],
    residue: point.residue,
  }));
  const sampled = downsamplePoints(projected, MAX_TRACE_POINTS);
  const minX = Math.min(...projected.map((point) => point.x));
  const maxX = Math.max(...projected.map((point) => point.x));
  const minY = Math.min(...projected.map((point) => point.y));
  const maxY = Math.max(...projected.map((point) => point.y));
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const scale = Math.min(184 / spanX, 40 / spanY);
  const offsetX = (200 - spanX * scale) / 2;
  const offsetY = (48 - spanY * scale) / 2;
  const normalise = (point: BackbonePoint): BackbonePoint => ({
    x: offsetX + (point.x - minX) * scale,
    y: offsetY + (maxY - point.y) * scale,
    residue: point.residue,
  });
  const normalised = sampled.map(normalise);
  const triadResidues = new Set(triad.map((row) => row.author_residue));
  const marks = projected.filter((point) => triadResidues.has(point.residue)).map(normalise);
  return { points: normalised, marks };
}

type Vector3 = [number, number, number];
type Matrix3 = [Vector3, Vector3, Vector3];

function centrePoints(points: CoordinatePoint[]): Vector3[] {
  const mean: Vector3 = [
    points.reduce((sum, point) => sum + point.x, 0) / points.length,
    points.reduce((sum, point) => sum + point.y, 0) / points.length,
    points.reduce((sum, point) => sum + point.z, 0) / points.length,
  ];
  return points.map((point) => [point.x - mean[0], point.y - mean[1], point.z - mean[2]]);
}

function covarianceMatrix(points: Vector3[]): Matrix3 {
  const matrix: Matrix3 = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (const point of points) {
    for (let row = 0; row < 3; row += 1) {
      for (let column = 0; column < 3; column += 1) {
        matrix[row][column] += point[row] * point[column];
      }
    }
  }
  const divisor = Math.max(1, points.length - 1);
  return matrix.map((row) => row.map((value) => value / divisor)) as Matrix3;
}

function principalAxis(matrix: Matrix3): Vector3 {
  let axis: Vector3 = [1, 1, 1];
  for (let iteration = 0; iteration < 24; iteration += 1) {
    const next: Vector3 = [
      matrix[0][0] * axis[0] + matrix[0][1] * axis[1] + matrix[0][2] * axis[2],
      matrix[1][0] * axis[0] + matrix[1][1] * axis[1] + matrix[1][2] * axis[2],
      matrix[2][0] * axis[0] + matrix[2][1] * axis[1] + matrix[2][2] * axis[2],
    ];
    const length = Math.hypot(...next);
    if (!length) return axis;
    axis = next.map((value) => value / length) as Vector3;
  }
  return axis;
}

function subtractOuterProduct(matrix: Matrix3, axis: Vector3): Matrix3 {
  const eigenvalue =
    axis[0] * (matrix[0][0] * axis[0] + matrix[0][1] * axis[1] + matrix[0][2] * axis[2]) +
    axis[1] * (matrix[1][0] * axis[0] + matrix[1][1] * axis[1] + matrix[1][2] * axis[2]) +
    axis[2] * (matrix[2][0] * axis[0] + matrix[2][1] * axis[1] + matrix[2][2] * axis[2]);
  return matrix.map((row, rowIndex) =>
    row.map((value, columnIndex) => value - eigenvalue * axis[rowIndex] * axis[columnIndex]),
  ) as Matrix3;
}

function downsamplePoints(points: BackbonePoint[], limit: number): BackbonePoint[] {
  if (points.length <= limit) return points;
  return Array.from({ length: limit }, (_, index) => {
    const sourceIndex = Math.round((index * (points.length - 1)) / (limit - 1));
    return points[sourceIndex];
  });
}

function StructureTrace({ trace }: { trace: BackboneTrace }) {
  const segmentCount = Math.min(TRACE_SEGMENTS, trace.points.length - 1);
  return (
    <svg
      className="investigation-graph-structure-trace"
      viewBox="0 0 200 48"
      aria-hidden="true"
    >
      {Array.from({ length: segmentCount }, (_, index) => {
        const start = Math.floor((index * (trace.points.length - 1)) / segmentCount);
        const end = Math.floor(((index + 1) * (trace.points.length - 1)) / segmentCount);
        const points = trace.points
          .slice(start, end + 1)
          .map((point) => `${point.x},${point.y}`)
          .join(" ");
        const hue = 215 - (index / Math.max(1, segmentCount - 1)) * 185;
        return <polyline key={`${start}-${end}`} points={points} style={{ stroke: `hsl(${hue} 72% 48%)` }} />;
      })}
      {trace.marks.map((point) => (
        <circle key={`${point.x}-${point.y}`} cx={point.x} cy={point.y} r="2.5" />
      ))}
    </svg>
  );
}

function sparklineValues(
  node: GraphNode,
  columns: ConservationColumn[],
  research: ResearchWorkspace | null,
  result: FinalResult | null,
): number[] {
  if (node.id === "conservation") {
    return columns.flatMap((column) =>
      typeof column.conservation === "number" && Number.isFinite(column.conservation)
        ? [column.conservation]
        : [],
    );
  }
  if (node.id === "simulation") return simulationValues(research);
  if (node.id === "rank") return rankingValues(result);
  return [];
}

function simulationValues(research: ResearchWorkspace | null): number[] {
  return (research?.simulations?.runs ?? []).flatMap((run) =>
    run.metrics.flatMap((metric) => {
      if (typeof metric.value === "number" && Number.isFinite(metric.value)) return [metric.value];
      if (typeof metric.value !== "string" || !metric.value.trim()) return [];
      const value = Number(metric.value);
      return Number.isFinite(value) ? [value] : [];
    }),
  );
}

function rankingValues(result: FinalResult | null): number[] {
  return [
    ...(result?.shortlists?.activity?.sites ?? []),
    ...(result?.shortlists?.stability?.sites ?? []),
  ].flatMap((site) => (Number.isFinite(site.score) ? [site.score] : []));
}

function Sparkline({ values }: { values: number[] }) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = values.length === 1 ? 100 : (index / (values.length - 1)) * 192 + 4;
      const y = 44 - ((value - min) / spread) * 36;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg className="investigation-graph-sparkline" viewBox="0 0 200 48" aria-hidden="true">
      <polyline points={points} />
    </svg>
  );
}

function pointerDistance(pointers: Map<number, PointerPoint>): number {
  const points = [...pointers.values()];
  if (points.length < 2) return 1;
  return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) || 1;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
