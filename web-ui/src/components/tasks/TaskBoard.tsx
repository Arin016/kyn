import { useCallback, useEffect, useState } from "react";
import api from "../../api";
import type { Task, TaskDiff } from "../../types";

interface Props {
  demoMode?: boolean;
  initialTaskId?: string | null;
  onNewTask: () => void;
  showToast: (message: string, isError?: boolean) => void;
}

const POLL_MS = 2500;

function statusTone(task: Task): string {
  if (task.task_status === "merged") return "merged";
  if (task.task_status === "abandoned") return "abandoned";
  if (task.status === "failed" || task.status === "cancelled") return "failed";
  if (task.status === "awaiting_handoff" || task.status === "ready")
    return "review";
  return "open";
}

function statusLabel(task: Task): string {
  if (task.task_status === "merged") return "Merged";
  if (task.task_status === "abandoned") return "Abandoned";
  const exec = (task.status || "queued").replaceAll("_", " ");
  return task.task_status === "open" ? `Open · ${exec}` : exec;
}

function shortTask(task: Task): string {
  const text = (task.task || "Untitled task").trim().split("\n")[0];
  return text.length > 80 ? `${text.slice(0, 80)}…` : text;
}

/**
 * Reviewable tasks: every coding task runs on its own branch in an isolated
 * worktree. Review the diff here, merge it into the base branch, or abandon
 * it. Merging requires reviewed work (approved handoff).
 */
export function TaskBoard({
  demoMode = false,
  initialTaskId,
  onNewTask,
  showToast,
}: Props) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Task | null>(null);
  const [diff, setDiff] = useState<TaskDiff | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const [confirm, setConfirm] = useState<"merge" | "abandon" | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!initialTaskId) return;
    setSelectedId(initialTaskId);
    setDetail(null);
    setDiff(null);
    setDiffOpen(true);
    setConfirm(null);
  }, [initialTaskId]);

  const refreshList = useCallback(async () => {
    if (demoMode) return;
    try {
      setTasks(await api.tasks());
    } catch {
      /* quiet poll — sidebar owns connection state */
    }
  }, [demoMode]);

  useEffect(() => {
    void refreshList();
    if (demoMode) return;
    const timer = window.setInterval(() => void refreshList(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refreshList, demoMode]);

  useEffect(() => {
    if (selectedId || tasks.length === 0) return;
    const first =
      tasks.find(
        (task) =>
          task.task_status === "open" && task.status === "awaiting_handoff",
      ) ||
      tasks.find(
        (task) => task.task_status === "open" && task.status === "ready",
      ) ||
      [...tasks].reverse()[0];
    if (first) {
      setSelectedId(first.id);
      setDiffOpen(true);
    }
  }, [selectedId, tasks]);

  useEffect(() => {
    if (!selectedId || demoMode) {
      if (!selectedId) {
        setDetail(null);
        setDiff(null);
        setDiffOpen(false);
        setConfirm(null);
      }
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const task = await api.task(selectedId);
        if (cancelled) return;
        setDetail(task);
        setError("");
        if (task.task_status === "open") {
          try {
            const payload = await api.taskDiff(selectedId);
            if (!cancelled) setDiff(payload);
          } catch {
            if (!cancelled) setDiff(null);
          }
        } else if (!cancelled) {
          setDiff(null);
        }
      } catch (exc) {
        if (!cancelled)
          setError((exc as Error).message || "Could not load this task.");
      }
    };
    void load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedId, demoMode]);

  const runAction = async (
    kind: string,
    fn: () => Promise<unknown>,
    done: string,
  ) => {
    setBusy(kind);
    setError("");
    try {
      await fn();
      await refreshList();
      if (selectedId) {
        try {
          setDetail(await api.task(selectedId));
          setDiff(await api.taskDiff(selectedId).catch(() => null));
        } catch {
          /* detail refresh is best-effort; list already updated */
        }
      }
      setConfirm(null);
      showToast(done, false);
    } catch (exc) {
      setError((exc as Error).message || "That did not work.");
    } finally {
      setBusy("");
    }
  };

  const approve = () =>
    detail &&
    runAction(
      "approve",
      () => api.approveCodingExecution(detail.id, detail.version),
      "Handoff approved — ready to merge.",
    );
  const merge = (message?: string) =>
    detail &&
    runAction(
      "merge",
      () => api.mergeTask(detail.id, message),
      "Merged into base.",
    );
  const abandon = () =>
    detail &&
    runAction("abandon", () => api.abandonTask(detail.id), "Task abandoned.");

  const selected =
    detail || tasks.find((task) => task.id === selectedId) || null;
  const reviewable =
    !!selected &&
    selected.task_status === "open" &&
    ["awaiting_handoff", "ready"].includes(selected.status);
  const needsApproval =
    !!selected &&
    selected.task_status === "open" &&
    selected.status === "awaiting_handoff";
  const canMerge =
    !!selected &&
    selected.task_status === "open" &&
    selected.status === "ready";
  const reviewCount = tasks.filter(
    (task) => task.task_status === "open" && task.status === "awaiting_handoff",
  ).length;
  const orderedTasks = [...tasks].sort((left, right) => {
    const priority = (task: Task) =>
      task.task_status !== "open"
        ? 3
        : task.status === "awaiting_handoff"
          ? 0
          : task.status === "ready"
            ? 1
            : 2;
    return (
      priority(left) - priority(right) ||
      tasks.indexOf(right) - tasks.indexOf(left)
    );
  });

  return (
    <section className="workflow-page" aria-label="Reviewable tasks">
      <aside
        className={`workflow-rail${tasks.length === 0 ? " workflow-rail--empty" : ""}`}
        aria-label="Tasks"
      >
        <div className="workflow-rail-header">
          <div>
            <p className="eyebrow">Control room</p>
            <h2>Tasks</h2>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-secondary workflow-new"
            onClick={onNewTask}
          >
            ＋ New task
          </button>
        </div>
        <p className="workflow-rail-copy">
          {tasks.length === 0
            ? "Each task gets its own branch. Review before merging."
            : `${tasks.length} ${tasks.length === 1 ? "task" : "tasks"} · ${reviewCount} ${reviewCount === 1 ? "needs" : "need"} review`}
        </p>
        <div className="workflow-list" role="list">
          {orderedTasks.map((task) => (
            <button
              key={task.id}
              type="button"
              className={`workflow-list-item${selectedId === task.id ? " selected" : ""}`}
              onClick={() => {
                setSelectedId(task.id);
                setDetail(null);
                setDiff(null);
                setDiffOpen(true);
                setConfirm(null);
                setError("");
              }}
            >
              <span
                className={`workflow-plan-dot task-${statusTone(task)}`}
                aria-hidden
              />
              <span>
                <strong>{shortTask(task)}</strong>
                <small>
                  {task.branch || task.id} · {statusLabel(task)}
                </small>
              </span>
            </button>
          ))}
        </div>
      </aside>
      <div className="workflow-stage">
        <div className="workflow-stage-body">
          {!selected ? (
            <>
              <header className="workflow-stage-header">
                <div>
                  <p className="eyebrow">Review queue</p>
                  <h1>
                    {tasks.length === 0
                      ? "Start a reviewable task"
                      : "Choose a task to review"}
                  </h1>
                </div>
              </header>
              <div className="task-empty-stage">
                <p className="workflow-terminal-note">
                  {tasks.length === 0
                    ? "Give a builder bot a task, then review its changes here before approving or merging."
                    : "Choose a task from the list to inspect its branch, changed files, and review status."}
                </p>
                {tasks.length === 0 && (
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    onClick={onNewTask}
                  >
                    Start a task
                  </button>
                )}
              </div>
            </>
          ) : (
            <>
              <header className="workflow-stage-header">
                <div>
                  <p className="eyebrow">
                    {selected.branch || selected.id} → {selected.base || "base"}
                  </p>
                  <h1>{shortTask(selected)}</h1>
                </div>
                <div className="workflow-stage-state">
                  <span
                    className={`task-status task-status--${statusTone(selected)}`}
                  >
                    {statusLabel(selected)}
                  </span>
                </div>
              </header>
              {error && (
                <div className="workflow-load-error" role="alert">
                  {error}
                </div>
              )}
              <dl className="task-meta">
                <div>
                  <dt>Builder</dt>
                  <dd>{selected.builder_bot || "—"}</dd>
                </div>
                <div>
                  <dt>Reviewer</dt>
                  <dd>{selected.reviewer_bot || "—"}</dd>
                </div>
                <div>
                  <dt>Repo</dt>
                  <dd className="mono">{selected.repo_path || "—"}</dd>
                </div>
                <div>
                  <dt>Branch</dt>
                  <dd className="mono">{selected.branch || "—"}</dd>
                </div>
                {selected.error && (
                  <div>
                    <dt>Error</dt>
                    <dd>{selected.error}</dd>
                  </div>
                )}
              </dl>
              {selected.checks && selected.checks.length > 0 && (
                <section
                  className="task-evidence"
                  aria-label="Automated checks"
                >
                  <div className="task-evidence-heading">
                    <strong>Automated checks</strong>
                    <span>
                      {
                        selected.checks.filter(
                          (check) => check.status === "passed",
                        ).length
                      }
                      /{selected.checks.length} passed
                    </span>
                  </div>
                  <ul className="task-check-list">
                    {selected.checks.map((check, index) => (
                      <li key={`${check.name}-${index}`}>
                        <span
                          className={`task-check-mark task-check-mark--${check.status}`}
                          aria-hidden
                        />
                        <span>{check.name}</span>
                        <small>
                          {check.status}
                          {typeof check.duration_seconds === "number"
                            ? ` · ${check.duration_seconds.toFixed(1)}s`
                            : ""}
                        </small>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {selected.review && (
                <section
                  className="task-review-evidence"
                  aria-label="Reviewer feedback"
                >
                  <div className="task-evidence-heading">
                    <strong>Reviewer · {selected.reviewer_bot || "Bot"}</strong>
                    <span>
                      {selected.review.approved
                        ? "Approved"
                        : "Changes requested"}
                    </span>
                  </div>
                  {selected.review.summary && <p>{selected.review.summary}</p>}
                  {(selected.review.blocking_findings || []).length > 0 && (
                    <ul>
                      {selected.review.blocking_findings?.map(
                        (finding, index) => (
                          <li key={`blocking-${index}`}>{finding}</li>
                        ),
                      )}
                    </ul>
                  )}
                  {(selected.review.findings || []).length > 0 && (
                    <ul>
                      {selected.review.findings?.map((finding, index) => (
                        <li key={`finding-${index}`}>{finding}</li>
                      ))}
                    </ul>
                  )}
                </section>
              )}
              <div className="task-diff-head">
                <strong>Diff vs {selected.base || "base"}</strong>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  disabled={!diff}
                  onClick={() => setDiffOpen((value) => !value)}
                >
                  {diffOpen ? "Hide" : "Show"} diff
                  {diff && diff.files.length > 0
                    ? ` (${diff.files.length} files)`
                    : ""}
                </button>
              </div>
              {diff && diff.files.length > 0 ? (
                <ul className="task-files">
                  {diff.files.map((file) => (
                    <li key={file.path}>
                      <code>{file.path}</code>
                      <span>{file.status}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="workflow-terminal-note">
                  {diff
                    ? "No changes yet — the worktree is clean."
                    : "Diff unavailable (worktree gone or task not started)."}
                </p>
              )}
              {diffOpen && diff && (
                <pre className="task-diff" aria-label="Task diff">
                  {diff.diff || "(empty diff)"}
                  {diff.truncated ? "\n…truncated…" : ""}
                </pre>
              )}
              {reviewable && (
                <p className="task-review-prompt">
                  {!diff
                    ? "The diff is unavailable, so review actions are disabled."
                    : diffOpen
                      ? needsApproval
                        ? "Review the changes above, then approve the handoff. Merge unlocks after approval."
                        : "Review the changes above, then merge when you’re ready."
                      : "Open the diff to review changes before approving or merging."}
                </p>
              )}
              <div
                className="task-actions"
                role="group"
                aria-label="Task review actions"
              >
                {needsApproval && (
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={busy !== "" || !diff || !diffOpen}
                    onClick={() => void approve()}
                  >
                    {busy === "approve" ? "Approving…" : "Approve handoff"}
                  </button>
                )}
                {canMerge && confirm !== "merge" && (
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={busy !== "" || !diff || !diffOpen}
                    onClick={() => setConfirm("merge")}
                  >
                    Merge into {selected.base || "base"}
                  </button>
                )}
                {canMerge && confirm === "merge" && (
                  <>
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      disabled={busy !== "" || !diff || !diffOpen}
                      onClick={() => void merge()}
                    >
                      {busy === "merge" ? "Merging…" : "Confirm merge"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary"
                      disabled={busy !== ""}
                      onClick={() => setConfirm(null)}
                    >
                      Cancel
                    </button>
                  </>
                )}
                {selected.task_status === "open" && confirm !== "abandon" && (
                  <button
                    type="button"
                    className="btn btn-sm btn-secondary task-abandon"
                    disabled={busy !== ""}
                    onClick={() => setConfirm("abandon")}
                  >
                    Abandon
                  </button>
                )}
                {selected.task_status === "open" && confirm === "abandon" && (
                  <>
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary task-abandon"
                      disabled={busy !== ""}
                      onClick={() => void abandon()}
                    >
                      {busy === "abandon" ? "Abandoning…" : "Confirm abandon"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary"
                      disabled={busy !== ""}
                      onClick={() => setConfirm(null)}
                    >
                      Cancel
                    </button>
                  </>
                )}
              </div>
              {!reviewable && selected.task_status === "open" && (
                <p className="workflow-terminal-note">
                  Merging unlocks once the reviewer approves the handoff
                  {selected.status === "awaiting_handoff"
                    ? " — approve it below."
                    : " — the task is still working."}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
