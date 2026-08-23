import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { EvidenceTask, EvidenceTaskId } from "./evidence";
import { buildEvidenceTasks, evidenceTaskForStage } from "./evidence";
import type { Job, ResearchTask, ResearchWorkspace } from "./types";
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
const PAD_Y = 46;
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

const PLAN_CAPABILITY_MATCHES: Record<Exclude<EvidenceTaskId, "overview">, string[]> = {
  plan: ["plan", "setup"],
  literature: ["literature", "database", "retrieval"],
  "homolog-search": ["homolog", "sequence", "alignment"],
  conservation: ["conservation", "evolution"],
  structure: ["structure", "spatial"],
  analysis: ["analysis", "data"],
  simulation: ["simulation", "docking", "molecular"],
  rank: ["rank", "candidate", "shortlist"],
  synthesis: ["synthesis", "report"],
  "follow-up": ["follow", "answer"],
  other: ["other", "sandbox"],
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
  selected,
  onSelect,
}: {
  job: Job;
  working: boolean;
  research: ResearchWorkspace | null;
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

  const [zoom, setZoom] = useState(1);
  const [followLive, setFollowLive] = useState(true);
  const [panning, setPanning] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef(1);
  const anchorRef = useRef<{ cx: number; cy: number; ax: number; ay: number } | null>(null);
  const panRef = useRef<{ x: number; y: number; sl: number; st: number } | null>(null);
  const pointersRef = useRef(new Map<number, PointerPoint>());
  const pinchRef = useRef<{ distance: number; zoom: number } | null>(null);
  const nodeRefs = useRef(new Map<EvidenceTaskId, HTMLButtonElement>());

  const applyZoom = useCallback((next: number, clientX?: number, clientY?: number) => {
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

  useEffect(() => {
    if (!followLive || !activeId || !survivingIds.has(activeId)) return;
    onSelect(activeId);
    scrollToNode(activeId);
  }, [activeId, followLive, onSelect, scrollToNode, survivingIds]);

  useEffect(() => {
    if (!survivingIds.has(selected)) onSelect("overview");
  }, [onSelect, selected, survivingIds]);

  const fitToView = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    const scale = Math.min(
      (element.clientWidth - 24) / width,
      (element.clientHeight - 24) / height,
      1,
    );
    anchorRef.current = { cx: 0, cy: 0, ax: 0, ay: 0 };
    setZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, scale)));
  }, [height, width]);

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
                  style={{ left: PAD_X + column * COLUMN_WIDTH, width: NODE_WIDTH }}
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
                    {node.summary ? (
                      node.summary
                    ) : node.methods.length ? (
                      <span className="investigation-graph-methods">
                        {node.methods.slice(0, 3).map((method) => (
                          <em key={method}>{method}</em>
                        ))}
                      </span>
                    ) : (
                      "No output recorded yet"
                    )}
                  </span>
                  <span className="investigation-graph-footer">
                    <span>◆ {node.outputs} outputs</span>
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
    const planTask = (research?.plan?.tasks ?? []).find((candidate) => matchesPlanTask(task, candidate));
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
    capability: "Request",
    summary: job.objective,
    methods: [],
    outputs: 0,
    updatedAt: job.updated_at,
    status: job.status === "failed" ? "FAILED" : working ? "RUNNING" : "COMPLETED",
    column: 0,
    lane: 0,
  };
  const contentTasks = tasks.filter((task) => task.artifacts.length > 0 || Boolean(task.summary) || planMatches.has(task.id));
  const nodes = [
    objective,
    ...contentTasks.map((task): GraphNode => {
      const planTask = planMatches.get(task.id);
      const status = deriveStatus(task, planTask, activeId, failedIds, working);
      return {
        id: task.id,
        title: task.title,
        shortTitle: task.shortTitle,
        capability: planTask?.capability ?? task.shortTitle,
        summary: task.summary,
        methods: planTask?.methods ?? [],
        outputs: task.artifacts.length,
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

function matchesPlanTask(task: EvidenceTask, planTask: ResearchTask): boolean {
  if (planTask.output_files.some((file) => task.artifacts.some((artifact) => artifact.filename === file))) {
    return true;
  }
  const capability = planTask.capability.toLowerCase();
  return PLAN_CAPABILITY_MATCHES[task.id].some((term) => capability.includes(term));
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
