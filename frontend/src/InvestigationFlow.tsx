import { useEffect, useMemo, useRef, useState } from "react";
import { ArtifactLink } from "./Artifact";
import { visibleMessages } from "./chat";
import { Markdown } from "./Markdown";
import type { ArtifactInfo, Job, JobEvent, Message } from "./types";

type FlowStep = {
  id: string;
  stage: string;
  title: string;
  createdAt: string;
  messages: Message[];
  updates: string[];
  artifacts: ArtifactInfo[];
};

export type InvestigationSelection = {
  id: string;
  stage: string;
  title: string;
  artifactIds: string[];
};

type TimelineEntry =
  | { kind: "message"; createdAt: string; message: Message }
  | { kind: "event"; createdAt: string; event: JobEvent };

const STAGE_META: Record<string, { title: string; short: string }> = {
  request: { title: "Investigation request", short: "Request" },
  sandbox: { title: "Open Devin sandbox", short: "Sandbox" },
  plan: { title: "Plan the investigation", short: "Plan" },
  working: { title: "Run the investigation", short: "Working" },
  running: { title: "Run the investigation", short: "Working" },
  "homolog-search": { title: "Search homologs", short: "Homologs" },
  conservation: { title: "Compute conservation", short: "Conservation" },
  structure: { title: "Inspect structure", short: "Structure" },
  literature: { title: "Search literature and databases", short: "Literature" },
  analysis: { title: "Analyze scientific data", short: "Analysis" },
  simulation: { title: "Run molecular simulation", short: "Simulation" },
  synthesis: { title: "Synthesize scientific findings", short: "Synthesis" },
  rank: { title: "Rank candidate sites", short: "Candidates" },
  review: { title: "Review findings", short: "Review" },
  "follow-up": { title: "Handle follow-up", short: "Follow-up" },
  answer: { title: "Answer the follow-up", short: "Answer" },
  import: { title: "Import outputs", short: "Import" },
  waiting_for_user: { title: "Wait for input", short: "Input" },
  waiting_for_approval: { title: "Wait for approval", short: "Approval" },
  complete: { title: "Investigation complete", short: "Complete" },
  error: { title: "Investigation stopped", short: "Stopped" },
};

export function InvestigationFlow({
  job,
  working,
  onSelectionChange,
}: {
  job: Job;
  working: boolean;
  onSelectionChange?: (selection: InvestigationSelection) => void;
}) {
  const steps = useMemo(() => buildFlow(job), [job]);
  const [selectedId, setSelectedId] = useState(steps.at(-1)?.id ?? "request");
  const [followLive, setFollowLive] = useState(true);
  const trackRef = useRef<HTMLDivElement>(null);
  const latestId = steps.at(-1)?.id;

  useEffect(() => {
    if (followLive && latestId) {
      setSelectedId(latestId);
      trackRef.current?.scrollTo({ left: trackRef.current.scrollWidth, behavior: "smooth" });
    }
  }, [followLive, latestId]);

  useEffect(() => {
    if (!steps.some((step) => step.id === selectedId) && latestId) {
      setSelectedId(latestId);
    }
  }, [latestId, selectedId, steps]);

  const selected = steps.find((step) => step.id === selectedId) ?? steps.at(-1);

  useEffect(() => {
    if (!selected) return;
    onSelectionChange?.({
      id: selected.id,
      stage: selected.stage,
      title: selected.title,
      artifactIds: selected.artifacts.map((artifact) => artifact.id),
    });
  }, [onSelectionChange, selected]);

  return (
    <section className="flow-panel" aria-label="Investigation flow">
      <div className="flow-heading">
        <div>
          <p className="eyebrow">Research tasks</p>
          <h2>Select a task to inspect its evidence</h2>
        </div>
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
      </div>
      <div className="flow-track" role="list" ref={trackRef}>
        {steps.map((step, index) => {
          const active = working && index === steps.length - 1;
          const failed = job.status === "failed" && index === steps.length - 1;
          return (
            <button
              type="button"
              role="listitem"
              className={`flow-node ${selected?.id === step.id ? "selected" : ""} ${active ? "active" : ""} ${failed ? "failed" : ""}`}
              key={step.id}
              onClick={() => {
                setSelectedId(step.id);
                setFollowLive(index === steps.length - 1);
              }}
              aria-current={selected?.id === step.id ? "step" : undefined}
            >
              <span className="node-index">{index + 1}</span>
              <span className="node-copy">
                <strong>{stageMeta(step.stage).short}</strong>
                <small>{nodeSummary(step)}</small>
              </span>
              <span className="node-status">{active ? "Live" : failed ? "Error" : "Done"}</span>
            </button>
          );
        })}
      </div>
      {selected ? <StepDetail jobId={job.id} step={selected} /> : null}
    </section>
  );
}

function StepDetail({ jobId, step }: { jobId: string; step: FlowStep }) {
  return (
    <article className="step-detail">
      <header>
        <div>
          <p className="eyebrow">{stageMeta(step.stage).short}</p>
          <h3>{step.title}</h3>
        </div>
        <time dateTime={step.createdAt}>{formatTime(step.createdAt)}</time>
      </header>
      <div className="step-output">
        {step.messages.map((message) => (
          <div className="step-message" key={message.id}>
            <span>{message.speaker === "user" ? "You" : "Devin"}</span>
            <Markdown>{message.body}</Markdown>
          </div>
        ))}
        {step.updates.length ? (
          <ul className="step-updates">
            {step.updates.map((update, index) => (
              <li key={`${step.id}-update-${index}`}>{update}</li>
            ))}
          </ul>
        ) : null}
        {step.artifacts.length ? (
          <div className="step-artifacts">
            <span>Outputs</span>
            <div>
              {step.artifacts.map((artifact) => (
                <ArtifactLink jobId={jobId} filename={artifact.filename} key={artifact.id}>
                  {artifact.filename}
                </ArtifactLink>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function buildFlow(job: Job): FlowStep[] {
  const root: FlowStep = {
    id: "request",
    stage: "request",
    title: STAGE_META.request.title,
    createdAt: job.created_at,
    messages: [
      {
        id: "objective",
        speaker: "user",
        body: job.objective,
        stage: "request",
        artifact_ids: [],
        created_at: job.created_at,
      },
    ],
    updates: [],
    artifacts: [],
  };
  const entries: TimelineEntry[] = [
    ...visibleMessages(job.messages).map(
      (message): TimelineEntry => ({ kind: "message", createdAt: message.created_at, message }),
    ),
    ...job.events
      .filter((event) =>
        ["job.started", "stage.started", "artifact.ready", "agent.error", "job.complete", "job.failed"].includes(
          event.type,
        ),
      )
      .map((event): TimelineEntry => ({ kind: "event", createdAt: event.created_at, event })),
  ].sort((left, right) => {
    const time = left.createdAt.localeCompare(right.createdAt);
    if (time !== 0) return time;
    return left.kind === "event" ? -1 : 1;
  });

  const artifacts = new Map(job.artifacts.map((artifact) => [artifact.id, artifact]));
  const steps = [root];
  let current: FlowStep | null = null;
  let sequence = 0;
  let handlingFollowUp = false;

  for (const entry of entries) {
    if (entry.kind === "message" && entry.message.speaker === "user") {
      handlingFollowUp = true;
      sequence += 1;
      current = {
        id: `request-${sequence}-${entry.message.id}`,
        stage: "follow-up",
        title: "Follow-up request",
        createdAt: entry.createdAt,
        messages: [entry.message],
        updates: [],
        artifacts: [],
      };
      steps.push(current);
      continue;
    }

    const stage = entry.kind === "message"
      ? handlingFollowUp
        ? "answer"
        : entry.message.stage ?? stageForSpeaker(entry.message.speaker)
      : eventStage(entry.event);
    const resultEvent =
      entry.kind === "event" &&
      ["artifact.ready", "job.complete", "job.failed", "agent.error"].includes(entry.event.type);
    if (!current || current.stage !== stage || (resultEvent && entry.event.type !== "artifact.ready")) {
      sequence += 1;
      current = {
        id: `${stage}-${sequence}`,
        stage,
        title: stageMeta(stage).title,
        createdAt: entry.createdAt,
        messages: [],
        updates: [],
        artifacts: [],
      };
      steps.push(current);
    }

    if (entry.kind === "message") {
      current.messages.push(entry.message);
      continue;
    }
    if (entry.event.type === "artifact.ready" && entry.event.artifact_id) {
      const artifact = artifacts.get(entry.event.artifact_id);
      if (artifact && !current.artifacts.some((item) => item.id === artifact.id)) {
        current.artifacts.push(artifact);
      }
    }
    if (!current.updates.includes(entry.event.message)) current.updates.push(entry.event.message);
  }

  return steps;
}

function eventStage(event: JobEvent): string {
  if (event.type === "job.complete") return "complete";
  if (event.type === "job.failed" || event.type === "agent.error") return "error";
  return event.stage ?? "working";
}

function stageForSpeaker(speaker: Message["speaker"]): string {
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

function stageMeta(stage: string) {
  return STAGE_META[stage] ?? {
    title: titleCase(stage || "working"),
    short: titleCase(stage || "working"),
  };
}

function nodeSummary(step: FlowStep): string {
  if (step.artifacts.length) {
    return `${step.artifacts.length} output${step.artifacts.length === 1 ? "" : "s"}`;
  }
  if (step.messages.length) {
    const text = step.messages.at(-1)?.body.replace(/[#*_`]/g, "").trim() ?? "";
    return text.length > 52 ? `${text.slice(0, 52)}…` : text;
  }
  return step.updates.at(-1) ?? "Step recorded";
}

function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
