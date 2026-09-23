import { useMemo, useState } from "react";
import type { MemoryRecord } from "../../types";
import { fullTime, truncate } from "../../lib/format";
import { EmptyState, Badge } from "../ui/Basics";
import { SegmentedControl } from "../ui/Pickers";

interface Props {
  records: MemoryRecord[];
}

function scopeLabel(scope?: string): string {
  if (!scope) return "local";
  if (scope.startsWith("channel:")) return scope.replace("channel:", "");
  return scope;
}

export function MemoryTab({ records }: Props) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [open, setOpen] = useState<number[]>([]);

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

  return (
    <>
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
