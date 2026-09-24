import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { MessagePart, ToolRun } from "./Message";
import type { Part, ToolPart } from "./Message";
import { AriGlyph } from "../AriGlyph";

export interface TurnSection {
  id: string;
  turnId?: number;
  prompt: string;
  parts: Part[];
}

export interface Suggestion {
  title: string;
  detail: string;
  prompt: string;
}

interface ThreadProps {
  /** Sectioned turns (control room). Mutually exclusive with `parts`. */
  sections?: TurnSection[];
  /** Legacy flat parts (product demo). Rendered as one section. */
  parts?: Part[];
  /** Append-only live buffer (optimistic echoes + streamed events). */
  liveParts?: Part[];
  emptyGreeting: string;
  emptyEyebrow: string;
  emptyDescription: string;
  suggestions: Suggestion[];
  onSuggestion: (text: string) => void;
  onApproval: (id: string, decision: "once" | "reject") => void;
  /** Name of the bot in this thread — drives the message avatars. */
  botName?: string;
  /** Trailing live indicator (thinking ghost) while a run is in flight. */
  thinking?: ReactNode;
  onRetry?: (turnId: number) => void;
  onEdit?: (prompt: string) => void;
  onFork?: (turnId: number, toBot: string) => void;
  /** Other bots a turn can be forked to. */
  forkBots?: string[];
}

type Item =
  | { kind: "part"; part: Part }
  /** A consecutive batch of tool calls, rendered as one collapsed row. */
  | { kind: "tools"; parts: ToolPart[] };

/**
 * Tool calls between two prose blocks belong to one step, so they collapse into
 * a single row. Prose, reasoning and approvals stay their own blocks and break
 * the batch.
 */
function groupParts(parts: Part[]): Item[] {
  const items: Item[] = [];
  let batch: ToolPart[] = [];

  const flush = () => {
    if (batch.length > 0) {
      items.push({ kind: "tools", parts: batch });
      batch = [];
    }
  };

  for (const part of parts) {
    if (part.type === "tool") {
      batch.push(part);
      continue;
    }
    flush();
    items.push({ kind: "part", part });
  }
  flush();
  return items;
}

function TurnActions({
  turnId,
  prompt,
  forkBots,
  onRetry,
  onEdit,
  onFork,
}: {
  turnId: number;
  prompt: string;
  forkBots: string[];
  onRetry?: (turnId: number) => void;
  onEdit?: (prompt: string) => void;
  onFork?: (turnId: number, toBot: string) => void;
}) {
  const [forkOpen, setForkOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!forkOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setForkOpen(false);
    };
    const onClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setForkOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [forkOpen]);

  if (!onRetry && !onEdit && !onFork) return null;
  return (
    <div className="turn-actions" ref={rootRef}>
      {onRetry && (
        <button
          type="button"
          className="turn-action"
          title="Re-run this turn verbatim"
          onClick={() => onRetry(turnId)}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
            <path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Retry
        </button>
      )}
      {onEdit && prompt && (
        <button
          type="button"
          className="turn-action"
          title="Load this prompt into the composer to edit and rerun"
          onClick={() => onEdit(prompt)}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
            <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Edit
        </button>
      )}
      {onFork && forkBots.length > 0 && (
        <div className="turn-fork">
          <button
            type="button"
            className="turn-action"
            aria-haspopup="menu"
            aria-expanded={forkOpen}
            title="Continue this turn on another bot with full context"
            onClick={() => setForkOpen((value) => !value)}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
              <circle cx="6" cy="6" r="2.5" />
              <circle cx="6" cy="18" r="2.5" />
              <circle cx="18" cy="8" r="2.5" />
              <path d="M6 8.5v7M18 10.5c0 4-5 3.5-8.5 5" strokeLinecap="round" />
            </svg>
            Fork
          </button>
          {forkOpen && (
            <div className="turn-fork-menu" role="menu" aria-label="Fork to bot">
              {forkBots.map((name) => (
                <button
                  key={name}
                  type="button"
                  role="menuitem"
                  className="turn-fork-item"
                  onClick={() => {
                    setForkOpen(false);
                    onFork(turnId, name);
                  }}
                >
                  @{name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SectionItems({ items, onApproval, botName }: { items: Item[]; onApproval: ThreadProps["onApproval"]; botName?: string }) {
  return (
    <>
      {items.map((item, index) =>
        item.kind === "tools" ? (
          <div className="msg-part msg-gutter" key={`tools-${item.parts[0]?.id || index}`}>
            <ToolRun parts={item.parts} />
          </div>
        ) : (
          <MessagePart
            key={`${index}-${item.part.type}`}
            part={item.part}
            onApproval={onApproval}
            botName={botName}
          />
        ),
      )}
    </>
  );
}

export function Thread({
  sections,
  parts,
  liveParts = [],
  emptyGreeting,
  emptyEyebrow,
  emptyDescription,
  suggestions,
  onSuggestion,
  onApproval,
  botName,
  thinking,
  onRetry,
  onEdit,
  onFork,
  forkBots = [],
}: ThreadProps) {
  const resolved: TurnSection[] =
    sections ?? (parts ? [{ id: "flat", prompt: "", parts }] : []);
  const hasContent =
    resolved.some((section) => section.parts.length > 0) || liveParts.length > 0 || thinking;
  if (!hasContent) {
    return (
      <div className="empty-state-wrap">
        <div className="empty-content">
          <div className="empty-orb" aria-hidden>
            <AriGlyph size={40} />
          </div>
          <p className="empty-eyebrow">{emptyEyebrow}</p>
          <h1 className="empty-greeting">{emptyGreeting}</h1>
          <p className="empty-description">{emptyDescription}</p>
          {suggestions.length > 0 && (
            <div className="empty-starters">
              <p className="empty-starters-label">A few ways to begin</p>
              <div className="chip-row">
                {suggestions.map((suggestion) => (
                  <button
                    key={suggestion.prompt}
                    type="button"
                    className="chip starter-card"
                    title={suggestion.detail}
                    onClick={() => onSuggestion(suggestion.prompt)}
                  >
                    <span className="starter-copy">
                      <span className="starter-title">{suggestion.title}</span>
                      <span className="starter-detail">{suggestion.detail}</span>
                    </span>
                    <svg className="starter-arrow" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
                      <path d="M7 17 17 7M8 7h9v9" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="thread-column" role="log" aria-live="polite" aria-relevant="additions text">
      {resolved.map((section) => (
        <section key={section.id} className="turn-section" aria-label={section.prompt ? `Turn: ${section.prompt.slice(0, 80)}` : "Conversation"}>
          {section.turnId !== undefined && (
            <TurnActions
              turnId={section.turnId}
              prompt={section.prompt}
              forkBots={forkBots}
              onRetry={onRetry}
              onEdit={onEdit}
              onFork={onFork}
            />
          )}
          <SectionItems items={groupParts(section.parts)} onApproval={onApproval} botName={botName} />
        </section>
      ))}
      {(liveParts.length > 0 || thinking) && (
        <section key="live" className="turn-section turn-section--live" aria-label="Current turn">
          <SectionItems items={groupParts(liveParts)} onApproval={onApproval} botName={botName} />
          {thinking}
        </section>
      )}
    </div>
  );
}
