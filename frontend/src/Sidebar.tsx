import type { Job } from "./types";

export function Sidebar({
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
      <div className="brand-lockup">
        <span className="brand-mark">E</span>
        <div>
          <strong>ehl cognition</strong>
          <small>Research control room</small>
        </div>
      </div>
      <button type="button" className="new-investigation" onClick={onNew}>
        <span aria-hidden="true">＋</span>
        New investigation
      </button>
      <div className="history-heading">
        <span>Investigations</span>
        <small>{jobs.length}</small>
      </div>
      <div className="history">
        {jobs.map((item) => {
          const live = item.status === "running" || item.status === "queued";
          return (
            <button
              type="button"
              key={item.id}
              className={`history-item ${item.id === activeId ? "current" : ""}`}
              onClick={() => onSelect(item)}
            >
              <span className={`history-state ${live ? "live" : item.error ? "error" : ""}`} />
              <span className="history-copy">
                <strong>{item.title}</strong>
                <small>
                  {live
                    ? "Working now"
                    : `${formatShortDate(item.updated_at)} · ${item.artifacts.length} outputs`}
                </small>
              </span>
            </button>
          );
        })}
        {!jobs.length ? (
          <p className="history-empty">Your saved investigations will appear here.</p>
        ) : null}
      </div>
      <footer className="sidebar-footer">
        <span className="sandbox-dot" />
        Devin Cloud sandbox
      </footer>
    </aside>
  );
}

function formatShortDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? ""
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}
