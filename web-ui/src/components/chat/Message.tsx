import { memo, useEffect, useState } from "react";
import { BotAvatar } from "../BotAvatar";
import { StableProse } from "./markdown";
import { splitMentions } from "../../lib/slash";

export type Part =
  | { type: "user"; text: string; mentions?: string[] }
  | { type: "channel"; text: string; label: string }
  | { type: "assistant-text"; text: string; streaming?: boolean }
  | { type: "reasoning"; id: string; text: string; running: boolean }
  | { type: "tool"; id: string; title: string; status: "running" | "done" | "error"; detail?: string; repeat?: number }
  | { type: "approval"; id: string; title: string }
  | { type: "usage"; id: string; tokens: number; cost: number }
  | { type: "note"; text: string }
  | { type: "error"; text: string };

interface PartProps {
  part: Part;
  onApproval?: (id: string, decision: "once" | "reject") => void;
  /** Which bot is speaking — drives the avatar on the left of the bubble. */
  botName?: string;
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

export type ToolPart = Extract<Part, { type: "tool" }>;

interface ToolClass {
  key: string;
  label: string;
}

/**
 * Tool titles arrive as free text (`filesystem.read · README.md`). Classify the
 * leading segment so a collapsed run can be summarised by what it actually did
 * instead of listing every call.
 */
export function toolClassOf(title: string): ToolClass {
  const head = (title.split("·")[0] || title).trim();
  const name = head.toLowerCase();
  if (/read|view|cat|open|list|glob|ls\b|notebook/.test(name)) return { key: "read", label: "read" };
  if (/write|edit|patch|create|replace|apply|rename|delete|move/.test(name)) return { key: "edit", label: "edit" };
  if (/exec|shell|bash|run|command|terminal|test|build/.test(name)) return { key: "run", label: "run" };
  if (/search|grep|find|query|index|memory|recall/.test(name)) return { key: "search", label: "search" };
  if (/http|fetch|curl|api|web|browser|url/.test(name)) return { key: "net", label: "network" };
  if (/plan|task|todo|think|goal|spec/.test(name)) return { key: "plan", label: "plan" };
  return { key: "other", label: name || "tool" };
}

function countByClass(parts: ToolPart[]): { key: string; label: string; count: number }[] {
  const tally = new Map<string, { key: string; label: string; count: number }>();
  for (const part of parts) {
    const cls = toolClassOf(part.title);
    const entry = tally.get(cls.key) || { ...cls, count: 0 };
    entry.count += 1;
    tally.set(cls.key, entry);
  }
  return [...tally.values()].sort((left, right) => right.count - left.count);
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`tool-run-chevron${open ? " open" : ""}`}
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
  );
}

/**
 * One collapsed row for a whole batch of tool calls — the agent's prose stays
 * the only thing that reads as output, and the calls expand into the full list
 * with each tool's class, arguments and status.
 */
export function ToolRun({ parts }: { parts: ToolPart[] }) {
  const [open, setOpen] = useState(false);
  const [openDetails, setOpenDetails] = useState<string[]>([]);

  const running = parts.find((part) => part.status === "running");
  const failed = parts.filter((part) => part.status === "error");
  const pending = running ?? failed[failed.length - 1];
  const single = parts.length === 1 ? parts[0] : null;
  const classes = countByClass(parts);

  const summaryLabel = single
    ? single.title
    : `${parts.length} tool call${parts.length === 1 ? "" : "s"}`;

  const toggleDetail = (id: string) =>
    setOpenDetails((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );

  return (
    <div className={`tool-run${pending ? " is-live" : ""}${failed.length > 0 ? " has-error" : ""}`}>
      <button
        type="button"
        className="tool-run-head"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={`tool-run-glyph${running ? " is-running" : ""}`} aria-hidden>
          {running ? (
            <span className="tool-run-spinner" />
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M5 8l4 4-4 4M12 17h7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </span>
        <span className="tool-run-label">
          <span className="tool-run-summary">{summaryLabel}</span>
          {!open && pending && <span className="tool-run-live-label">{pending.title}</span>}
        </span>
        {!open && classes.length > 1 && (
          <span className="tool-run-classes">
            {classes.slice(0, 4).map((item) => (
              <span key={item.key} className="tool-chip" data-class={item.key}>
                {item.count} {item.label}
              </span>
            ))}
          </span>
        )}
        {!open && single && (
          <span className="tool-chip" data-class={toolClassOf(single.title).key}>
            {toolClassOf(single.title).label}
          </span>
        )}
        <span className={`tool-status ${running ? "running" : failed.length > 0 ? "error" : "done"}`}>
          {running ? "running" : failed.length > 0 ? "failed" : "done"}
        </span>
        <Chevron open={open} />
      </button>

      {open && (
        <ul className="tool-run-list" aria-label="Tool calls in this step">
          {parts.map((part, index) => {
            const cls = toolClassOf(part.title);
            const detailOpen = openDetails.includes(part.id);
            return (
              <li key={part.id || `${part.title}-${index}`}>
                <button
                  type="button"
                  className="tool-call"
                  aria-expanded={Boolean(part.detail) && detailOpen}
                  disabled={!part.detail}
                  onClick={() => toggleDetail(part.id)}
                >
                  <span className="tool-call-index" aria-hidden>
                    {index + 1}
                  </span>
                  <span className="tool-chip" data-class={cls.key}>
                    {cls.label}
                  </span>
                  <span className="tool-call-title" title={part.title}>
                    {part.title}
                    {part.repeat && part.repeat > 1 ? ` ×${part.repeat}` : ""}
                  </span>
                  <span className={`tool-status ${part.status}`}>{part.status}</span>
                  {part.detail ? <Chevron open={detailOpen} /> : <span className="tool-call-spacer" aria-hidden />}
                </button>
                {detailOpen && part.detail && <pre className="tool-call-detail">{part.detail}</pre>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

const MessagePartInner = ({ part, onApproval, botName }: PartProps) => {
  switch (part.type) {
    case "user":
      return (
        <div className="user-row">
          <div className="user-bubble">
            {part.mentions && part.mentions.length > 0 ? (
              splitMentions(part.text, part.mentions).map((segment, index) =>
                segment.kind === "mention" ? (
                  <span key={index} className="mention-chip">@{segment.value}</span>
                ) : (
                  <span key={index}>{segment.value}</span>
                ),
              )
            ) : (
              part.text
            )}
          </div>
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
        <div className="msg-part assistant-row">
          <BotAvatar name={botName || "ari"} size={30} className="msg-avatar" />
          <div className="assistant-body">
            <div className={`assistant-part${part.streaming ? " streaming" : ""}`}>
              <StableProse text={part.text} streaming={part.streaming} />
            </div>
            {!part.streaming && part.text.trim().length > 0 && (
              <div className="msg-actions">
                <CopyButton getText={() => part.text} />
              </div>
            )}
          </div>
        </div>
      );

    case "reasoning":
      return (
        <div className="msg-part msg-gutter">
          <ReasoningBlock part={part} />
        </div>
      );

    case "tool":
      return (
        <div className="msg-part msg-gutter">
          <ToolRun parts={[part]} />
        </div>
      );

    case "approval":
      return (
        <div className="msg-part msg-gutter approval-card">
          <p className="approval-title">{part.title || "This bot needs permission to continue."}</p>
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

    case "usage":
      // Belt and braces: a zero/zero snapshot must never paint a pill.
      if (part.tokens === 0 && part.cost === 0) return null;
      return (
        <div className="msg-part msg-usage" aria-label="Session usage">
          <span className="msg-usage-tok">{part.tokens.toLocaleString()} tok in context</span>
          <span className="msg-usage-sep" aria-hidden>·</span>
          <span className="msg-usage-cost">${part.cost.toFixed(4)}</span>
        </div>
      );

    case "note":
      return (
        <div className="msg-part msg-usage" role="status">
          <span>{part.text}</span>
        </div>
      );

    case "error":
      return (
        <div className="msg-part msg-gutter error-part">
          <span>
            <strong>Run failed.</strong> {part.text || "Something went wrong."}
          </span>
        </div>
      );
  }
};

export const MessagePart = memo(MessagePartInner);
