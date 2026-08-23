import { isStatusLine } from "./chat";
import { Markdown } from "./Markdown";
import type { Job, Message } from "./types";

const STAGE_LABEL: Record<string, string> = {
  working: "Working in the sandbox…",
  waiting_for_user: "Waiting for you",
  waiting_for_approval: "Waiting for approval…",
  finished: "Finished this turn",
  new: "Starting the sandbox…",
  claimed: "Claiming the sandbox…",
  resuming: "Resuming the sandbox…",
  running: "Working in the sandbox…",
  "homolog-search": "Searching homologs…",
  conservation: "Computing conservation…",
  structure: "Reading the deposited structure…",
  literature: "Searching literature and databases…",
  analysis: "Analyzing scientific data…",
  simulation: "Running a sandbox simulation…",
  synthesis: "Synthesizing findings…",
  rank: "Ranking candidate sites…",
  "follow-up": "Answering…",
  import: "Importing result files…",
  sandbox: "Working in the sandbox…",
  plan: "Planning the investigation…",
};

export function Worklog({
  job,
  turns,
  working,
  awaitingConfirm,
  elapsed,
  onProceed,
}: {
  job: Job;
  turns: Message[];
  working: boolean;
  awaitingConfirm: boolean;
  elapsed: number;
  onProceed: () => void;
}) {
  return (
    <section className="worklog-panel" aria-label="Live Devin worklog">
      <header className="worklog-heading">
        <div>
          <p className="eyebrow">Execution log</p>
          <h2>What Devin is doing</h2>
        </div>
        {working ? (
          <span className="streaming-label">
            <span />
            Live
          </span>
        ) : (
          <span className="log-count">{turns.length} updates</span>
        )}
      </header>
      <div className="worklog-stream" aria-live="polite" aria-relevant="additions text">
        <article className="worklog-entry user-entry">
          <div className="worklog-meta">
            <span>Research question</span>
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
                      ? "Follow-up"
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
            <p>Review the proposed next step before the sandbox continues.</p>
            <button type="button" className="confirm-go" onClick={onProceed}>
              Approve next step
            </button>
          </article>
        ) : null}
        {working && !turns.length ? (
          <article className="worklog-entry status-entry">
            <div className="worklog-meta">
              <span>{stageName(job.active_stage)}</span>
              <time>{formatElapsed(elapsed)}</time>
            </div>
            <p>The first update will appear as Devin generates it.</p>
            <span className="stream-caret" aria-label="Waiting for streamed content" />
          </article>
        ) : null}
      </div>
    </section>
  );
}

export function stageStatus(stage: string | null): string {
  return STAGE_LABEL[stage ?? ""] ?? "Working in the sandbox…";
}

export function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

function stageName(stage: string | null): string {
  return stageStatus(stage).replace(/…$/, "");
}

function formatClock(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
