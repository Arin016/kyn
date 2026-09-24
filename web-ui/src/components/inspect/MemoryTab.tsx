import { useMemo, useState } from "react";
import type { MemoryFact, MemoryRecord } from "../../types";
import { fullTime, truncate } from "../../lib/format";
import { EmptyState, Badge } from "../ui/Basics";
import { SegmentedControl } from "../ui/Pickers";
import api from "../../api";

interface Props {
  botName: string;
  records: MemoryRecord[];
  facts: MemoryFact[];
  onFactsChanged: () => void;
  showToast: (message: string, isError?: boolean) => void;
}

function scopeLabel(scope?: string): string {
  if (!scope) return "local";
  if (scope.startsWith("channel:")) return scope.replace("channel:", "");
  return scope;
}

export function MemoryTab({ botName, records, facts, onFactsChanged, showToast }: Props) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [open, setOpen] = useState<number[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState("");
  const [dreaming, setDreaming] = useState(false);
  const [showInvalid, setShowInvalid] = useState(false);
  const [invalidFacts, setInvalidFacts] = useState<MemoryFact[]>([]);

  const scopes = useMemo(() => {
    const found = new Set(records.map((record) => scopeLabel(record.scope)));
    return ["all", ...[...found].sort()];
  }, [records]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return records
      .filter((record) => scope === "all" || scopeLabel(record.scope) === scope)
      .filter(
        (record) =>
          !needle ||
          (record.request_text || "").toLowerCase().includes(needle) ||
          (record.response_text || "").toLowerCase().includes(needle),
      )
      .slice(0, 40);
  }, [records, scope, query]);

  const toggleInvalid = async () => {
    if (showInvalid) {
      setShowInvalid(false);
      return;
    }
    setBusy("invalid");
    try {
      const data = await api.memoryFacts(botName, true);
      setInvalidFacts((data.facts || []).filter((fact) => fact.invalid_at));
      setShowInvalid(true);
    } catch (exc) {
      showToast((exc as Error).message || "Could not load retired facts.", true);
    } finally {
      setBusy("");
    }
  };

  const visibleFacts = showInvalid
    ? [...facts, ...invalidFacts.filter((item) => !facts.some((live) => live.id === item.id))]
    : facts;

  const runFactAction = async (kind: string, fn: () => Promise<unknown>, done: string) => {    setBusy(kind);
    try {
      await fn();
      onFactsChanged();
      if (done) showToast(done, false);
    } catch (exc) {
      showToast((exc as Error).message || "Memory update failed.", true);
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <div className="panel-section">
        <div className="panel-section-head">
          <div>
            <p className="section-label">Durable facts</p>
            <p className="section-hint">
              Distilled lessons the bot recalls first. Pinned facts always lead; retired ones stay inspectable.
            </p>
          </div>
          {facts.length > 0 ? <Badge tone="muted">{facts.length} facts</Badge> : null}
        </div>
        <div className="place-secret-form">
          <input
            aria-label="New fact"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Teach this bot a lasting fact…"
          />
          <button
            type="button"
            className="mini-primary"
            disabled={busy !== "" || !draft.trim()}
            onClick={() => {
              const text = draft.trim();
              setDraft("");
              void runFactAction("add", () => api.rememberFact(botName, text), "Fact recorded.");
            }}
          >
            {busy === "add" ? "…" : "Remember"}
          </button>
          <button
            type="button"
            className="mini-ghost"
            disabled={busy !== ""}
            title="Schedule a nightly turn where the bot distills facts and forgets trivia on its own"
            onClick={() => {
              setDreaming(true);
              void runFactAction("dream", () => api.enableDreaming(botName), "Nightly dreaming enabled — the bot will consolidate while you sleep.").finally(
                () => setDreaming(false),
              );
            }}
          >
            {dreaming ? "…" : "Dream nightly"}
          </button>
          <button type="button" className="mini-ghost" onClick={() => void toggleInvalid()}>
            {showInvalid ? "Hide retired" : "Show retired"}
          </button>
        </div>
        {visibleFacts.length === 0 ? (
          <EmptyState>No facts yet — the bot records them with memory_remember, or teach one above.</EmptyState>
        ) : (
          <ul className="task-files">
            {visibleFacts.map((fact) => (
              <li key={fact.id}>
                <span>
                  {fact.pinned && <Badge tone="accent">pinned</Badge>}{" "}
                  {fact.invalid_at && <s>{fact.fact}</s>}
                  {!fact.invalid_at && fact.fact}
                  {fact.entities.length > 0 && (
                    <span className="field-hint"> [{fact.entities.join(", ")}]</span>
                  )}
                </span>
                <span className="task-file-actions">
                  {!fact.invalid_at && (
                    <button
                      type="button"
                      className="mini-ghost"
                      disabled={busy !== ""}
                      title={fact.pinned ? "Unpin" : "Pin — always recall first"}
                      onClick={() =>
                        void runFactAction(`pin:${fact.id}`, () => api.pinFact(botName, fact.id, !fact.pinned), "")
                      }
                    >
                      {fact.pinned ? "Unpin" : "Pin"}
                    </button>
                  )}
                  {!fact.invalid_at && (
                    <button
                      type="button"
                      className="mini-ghost"
                      disabled={busy !== ""}
                      title="Retire this fact (history is kept, recall stops)"
                      onClick={() =>
                        void runFactAction(`forget:${fact.id}`, () => api.forgetFact(botName, fact.id), "")
                      }
                    >
                      Forget
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel-section">
        <div className="panel-section-head">
          <div>
            <p className="section-label">Shared memory</p>
            <p className="section-hint">
              Durable evidence this bot keeps across the local chat and authenticated external threads.
            </p>
          </div>
          {records.length > 0 ? <Badge tone="muted">{records.length} records</Badge> : null}
        </div>
        {scopes.length > 2 && (
          <SegmentedControl value={scope} options={scopes.map((item) => ({ value: item, label: item }))} onChange={setScope} label="Memory scope" size="sm" />
        )}
        <input
          className="perm-search"
          value={query}
          placeholder="Search memory…"
          aria-label="Search memory"
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <div className="memory-list">
        {filtered.length === 0 && (
          <EmptyState>{records.length === 0 ? "No shared memories yet." : "No record matches that search."}</EmptyState>
        )}
        {filtered.map((record, index) => {
          const expanded = open.includes(index);
          return (
            <article key={`${record.created_at}-${index}`} className="memory-card">
              <button
                type="button"
                className="memory-head"
                aria-expanded={expanded}
                onClick={() =>
                  setOpen((current) =>
                    current.includes(index) ? current.filter((item) => item !== index) : [...current, index],
                  )
                }
              >
                <span className="memory-copy">
                  <span className="memory-request">{truncate(record.request_text || "Recorded exchange", 74)}</span>
                  <span className="memory-meta">
                    <span className="work-chip">{scopeLabel(record.scope)}</span>
                    <span>{fullTime(record.created_at)}</span>
                  </span>
                </span>
                <svg
                  className={`tool-run-chevron${expanded ? " open" : ""}`}
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  aria-hidden
                >
                  <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {expanded && (
                <p className="memory-response">
                  {record.response_text || "No textual response was stored for this exchange."}
                </p>
              )}
            </article>
          );
        })}
      </div>
    </>
  );
}
