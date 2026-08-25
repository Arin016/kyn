import { memo, useEffect, useState } from "react";
import { StableProse } from "./markdown";

export type Part =
  | { type: "user"; text: string }
  | { type: "channel"; text: string; label: string }
  | { type: "assistant-text"; text: string; streaming?: boolean }
  | { type: "reasoning"; id: string; text: string; running: boolean }
  | { type: "tool"; id: string; title: string; status: "running" | "done" | "error"; detail?: string }
  | { type: "approval"; id: string; title: string }
  | { type: "error"; text: string };

interface PartProps {
  part: Part;
  onApproval?: (id: string, decision: "once" | "reject") => void;
}

function CopyButton({ getText }: { getText: () => string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="msg-action-btn"
      aria-label={copied ? "Copied" : "Copy message"}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(getText());
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1600);
        } catch {
          /* clipboard unavailable */
        }
      }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        {copied ? (
          <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
        ) : (
          <>
            <rect x="9" y="9" width="11" height="11" rx="2.5" />
            <path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15" strokeLinecap="round" />
          </>
        )}
      </svg>
    </button>
  );
}

function ReasoningBlock({ part }: { part: Extract<Part, { type: "reasoning" }> }) {
  const [open, setOpen] = useState(part.running);

  // Auto-collapse when reasoning completes.
  useEffect(() => {
    if (part.running) setOpen(true);
    else setOpen(false);
  }, [part.running]);

  return (
    <div className="reasoning">
      <button
        type="button"
        className="reasoning-summary"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {part.running && <span className="reasoning-live-dot" aria-hidden />}
        {part.running ? "Thinking…" : "Thought process"}
        <svg
          className={`reasoning-chevron${open ? " open" : ""}`}
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
      {open && <div className="reasoning-body">{part.text}</div>}
    </div>
  );
}

function ToolCard({ part }: { part: Extract<Part, { type: "tool" }> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="tool-card">
      <button
        type="button"
        className="tool-card-head"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
          <path d="M14.5 5.5a4 4 0 0 1-5.6 5L4 15.4V20h4.6l4.9-4.9a4 4 0 0 1 5-5.6l-3-3z" strokeLinejoin="round" />
        </svg>
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {part.title}
        </span>
        <span className={`tool-status ${part.status}`}>{part.status}</span>
      </button>
      {open && part.detail && <div className="tool-detail">{part.detail}</div>}
    </div>
  );
}

const MessagePartInner = ({ part, onApproval }: PartProps) => {
  switch (part.type) {
    case "user":
      return (
        <div className="user-row">
          <div className="user-bubble">{part.text}</div>
        </div>
      );

    case "channel":
      return (
        <div>
          <div className="channel-tag">{part.label}</div>
          <div className="user-row">
            <div className="user-bubble">{part.text}</div>
          </div>
        </div>
      );

    case "assistant-text":
      return (
        <div className="msg-part">
          <div className="assistant-part">
            <StableProse text={part.text} streaming={part.streaming} />
          </div>
          {!part.streaming && part.text.trim().length > 0 && (
            <div className="msg-actions">
              <CopyButton getText={() => part.text} />
            </div>
          )}
        </div>
      );

    case "reasoning":
      return (
        <div className="msg-part">
          <ReasoningBlock part={part} />
        </div>
      );

    case "tool":
      return (
        <div className="msg-part">
          <ToolCard part={part} />
        </div>
      );

    case "approval":
      return (
        <div className="msg-part approval-card">
          <p className="approval-title">{part.title || "Kiro needs permission to continue."}</p>
          <div className="approval-buttons">
            <button type="button" className="btn-approve" onClick={() => onApproval?.(part.id, "once")}>
              Allow once
            </button>
            <button type="button" className="btn-deny" onClick={() => onApproval?.(part.id, "reject")}>
              Deny
            </button>
          </div>
        </div>
      );

    case "error":
      return (
        <div className="msg-part error-part">
          <span>
            <strong>Run failed.</strong> {part.text || "Something went wrong."}
          </span>
        </div>
      );
  }
};

export const MessagePart = memo(MessagePartInner);
