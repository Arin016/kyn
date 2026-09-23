import { MessagePart, ToolRun } from "./Message";
import type { Part, ToolPart } from "./Message";
import { KiroGlyph } from "../KiroGlyph";

interface ThreadProps {
  parts: Part[];
  emptyGreeting: string;
  suggestions: string[];
  onSuggestion: (text: string) => void;
  onApproval: (id: string, decision: "once" | "reject") => void;
  /** Name of the bot in this thread — drives the message avatars. */
  botName?: string;
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

export function Thread({
  parts,
  emptyGreeting,
  suggestions,
  onSuggestion,
  onApproval,
  botName,
}: ThreadProps) {
  if (parts.length === 0) {
    return (
      <div className="empty-state-wrap">
        <div className="empty-orb" aria-hidden>
          <KiroGlyph size={40} />
        </div>
        <p className="empty-eyebrow">Control room</p>
        <h1 className="empty-greeting">{emptyGreeting}</h1>
        <div className="chip-row">
          {suggestions.map((suggestion) => (
            <button key={suggestion} type="button" className="chip" onClick={() => onSuggestion(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      </div>
    );
  }

  const items = groupParts(parts);

  return (
    <div className="thread-column" role="log" aria-live="polite" aria-relevant="additions text">
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
    </div>
  );
}
