import { useEffect, useState } from "react";
import { AriHelper, ARI_HELPER_VIEWBOX } from "../AriHelper";
import type { RunPhase } from "../../types";

interface Props {
  phase: RunPhase;
  botName: string;
  /** Live activity line from the run (tool title, stage, …). */
  detail: string;
  /** When the current run started (ms epoch) — drives the elapsed ticker. */
  startedAt: number | null;
  /** Runs waiting behind the active one. */
  queued: number;
  /** Whether the run has streamed any visible output yet. */
  hasOutput: boolean;
}

type Stage = "waking" | "working" | "approval" | "winding";

const WAKING_QUIPS = [
  "Waking up…",
  "Rolling out of bed…",
  "Knocking on the engine room door…",
  "Putting the kettle on…",
  "Dusting off the workspace…",
  "Stretching its context window…",
];

const WORKING_QUIPS = [
  "Turning it over…",
  "Reading the room…",
  "Following the thread…",
  "Checking the corners…",
  "Connecting the dots…",
  "Asking the tools nicely…",
  "Measuring twice…",
  "Leaving no stone unturned…",
  "Consulting the fleet…",
  "Thinking in parallel…",
];

const STAGE_LABEL: Record<Stage, string> = {
  waking: "Waking",
  working: "Thinking",
  approval: "Approval",
  winding: "Winding down",
};

function stageFor(phase: RunPhase): Stage {
  if (phase === "waiting") return "approval";
  if (phase === "stopping" || phase === "error") return "winding";
  return "waking"; // refined to "working" below once there is evidence of life
}

/**
 * The run is alive indicator. An Ari helper bobs inside its disc with three
 * orbiting sparks while the copy narrates the run's stage: waking quips until
 * the first streamed output or tool activity, then the live activity line up
 * top with working quips underneath, plus an elapsed ticker so a long run
 * reads as "still going" rather than "stuck".
 */
export function ThinkingGhost({ phase, botName, detail, startedAt, queued, hasOutput }: Props) {
  const base = stageFor(phase);
  const alive = hasOutput || detail.trim().length > 0;
  const stage: Stage = base === "waking" && alive && phase === "running" ? "working" : base;

  const [quipIndex, setQuipIndex] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setQuipIndex(0);
  }, [stage, botName]);

  useEffect(() => {
    if (stage === "approval") return;
    const timer = window.setInterval(() => {
      setQuipIndex((index) => index + 1);
    }, 3200);
    return () => window.clearInterval(timer);
  }, [stage]);

  useEffect(() => {
    if (startedAt === null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  const elapsed = startedAt === null ? null : Math.max(0, Math.floor((now - startedAt) / 1000));
  const quips = stage === "waking" ? WAKING_QUIPS : WORKING_QUIPS;

  let headline: string;
  let subline: string;
  if (stage === "approval") {
    headline = "Needs your approval to continue";
    subline = detail.trim() || "The run is holding — nothing moves until you decide.";
  } else if (stage === "winding") {
    headline = phase === "error" ? "That run stumbled" : "Winding down…";
    subline = "Tying up loose ends.";
  } else if (detail.trim() && stage === "working") {
    headline = detail.trim();
    subline = quips[quipIndex % quips.length];
  } else {
    const who = botName ? `${botName} is ` : "";
    headline = `${who}${quips[quipIndex % quips.length]}`;
    subline =
      stage === "waking"
        ? "First reply is on its way — the engine is still spinning up."
        : "Still going — long thoughts mean thorough thoughts.";
  }

  return (
    <div className="think-ghost" data-stage={stage} role="status" aria-live="polite">
      <div className="think-orb" aria-hidden>
        <span className="think-orbit think-orbit--a" />
        <span className="think-orbit think-orbit--b" />
        <span className="think-orbit think-orbit--c" />
        <svg viewBox={ARI_HELPER_VIEWBOX} className="think-mark">
          <g className="think-bob">
            <AriHelper tone="outline" edge="currentColor" eye="currentColor" weight={3} gloss={false} />
          </g>
        </svg>
      </div>
      <div className="think-copy">
        <p className="think-eyebrow">
          <span className="think-stage">{STAGE_LABEL[stage]}</span>
          {elapsed !== null && <span className="think-elapsed">{elapsed}s in</span>}
          {queued > 0 && <span className="think-queued">+{queued} queued</span>}
        </p>
        <p className="think-headline" key={`${stage}-${stage === "working" && detail.trim() ? "live" : quipIndex}`}>
          {headline}
        </p>
        <p className="think-subline" key={`${stage}-sub-${stage === "approval" || stage === "winding" ? "static" : quipIndex}`}>
          {subline}
        </p>
        <div className="think-bar" aria-hidden>
          <span className="think-bar-fill" />
        </div>
      </div>
    </div>
  );
}
