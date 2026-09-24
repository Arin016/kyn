import { useEffect, useState } from "react";
import type { RunPhase } from "../../types";
import { BotAvatar } from "../BotAvatar";
import { ThinkingDots } from "./ThinkingDots";

interface Props {
  phase: RunPhase;
  botName: string;
  /** Current run activity, such as a tool or stage name. */
  detail: string;
  startedAt: number | null;
  queued: number;
  hasOutput: boolean;
}

type Stage = "starting" | "thinking" | "approval" | "winding";

function stageFor(phase: RunPhase): Stage {
  if (phase === "waiting") return "approval";
  if (phase === "stopping" || phase === "error") return "winding";
  return "starting";
}

/** A compact, avatar-led live state that matches group chat's typing cue. */
export function ThinkingGhost({
  phase,
  botName,
  detail,
  startedAt,
  queued,
  hasOutput,
}: Props) {
  const initialStage = stageFor(phase);
  const active = hasOutput || detail.trim().length > 0;
  const stage = initialStage === "starting" && active && phase === "running"
    ? "thinking"
    : initialStage;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (startedAt === null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  const elapsed = startedAt === null ? null : Math.max(0, Math.floor((now - startedAt) / 1000));
  const label = stage === "approval"
    ? "Waiting for approval"
    : stage === "winding"
      ? phase === "error" ? "Run ended with an error" : "Wrapping up"
      : stage === "starting"
        ? `${botName || "Bot"} is starting`
        : detail.trim() || `${botName || "Bot"} is thinking`;
  const meta = [elapsed !== null && elapsed >= 10 ? `${elapsed}s` : "", queued > 0 ? `+${queued} queued` : ""]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      className="msg-part assistant-row think-ghost"
      data-stage={stage}
      role="status"
      aria-live="polite"
      aria-label={`${label}${meta ? `, ${meta}` : ""}`}
    >
      <BotAvatar name={botName || "ari"} size={30} className="msg-avatar thinking-avatar" />
      <div className="think-line">
        <div className="group-bubble is-typing think-bubble" aria-hidden>
          <ThinkingDots />
        </div>
        <span className="think-label" title={label}>{label}</span>
        {meta && <span className="think-meta">{meta}</span>}
      </div>
    </div>
  );
}
