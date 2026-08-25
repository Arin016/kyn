import { MessagePart } from "./Message";
import type { Part } from "./Message";

interface ThreadProps {
  parts: Part[];
  emptyGreeting: string;
  suggestions: string[];
  onSuggestion: (text: string) => void;
  onApproval: (id: string, decision: "once" | "reject") => void;
}

export function Thread({ parts, emptyGreeting, suggestions, onSuggestion, onApproval }: ThreadProps) {
  if (parts.length === 0) {
    return (
      <div className="empty-state-wrap">
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

  return (
    <div className="thread-column" role="log" aria-live="polite" aria-relevant="additions text">
      {parts.map((part, index) => (
        <MessagePart key={`${index}-${part.type}`} part={part} onApproval={onApproval} />
      ))}
    </div>
  );
}
