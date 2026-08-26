/** Timeline helpers for the ProductDemo (30 fps). */

export const FPS = 30;
export const DURATION_SEC = 75;
export const DURATION = FPS * DURATION_SEC;
export const WIDTH = 1920;
export const HEIGHT = 1080;

export function sec(s: number): number {
  return Math.round(s * FPS);
}

export function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

/** Progress of [start, end] at frame. */
export function progress(frame: number, start: number, end: number): number {
  if (end <= start) return frame >= end ? 1 : 0;
  return clamp01((frame - start) / (end - start));
}

export function typeChars(full: string, amount: number): string {
  const n = Math.floor(clamp01(amount) * full.length);
  return full.slice(0, n);
}

/** Scene windows (inclusive start, exclusive end). */
export const scenes = {
  brand: { start: sec(0), end: sec(4.5) },
  enter: { start: sec(4), end: sec(6.5) },
  selectBot: { start: sec(6), end: sec(10) },
  type: { start: sec(10), end: sec(15) },
  stream: { start: sec(15), end: sec(23) },
  workflow: { start: sec(22.5), end: sec(42) },
  telegram: { start: sec(41.5), end: sec(52) },
  approve: { start: sec(51.5), end: sec(63) },
  close: { start: sec(62), end: sec(75) },
} as const;

export const PROMPT = "Summarize what this repo does and list the riskiest TODOs.";
export const ASSISTANT_FULL =
  "This is a local control plane for durable Kiro agents. It owns sessions, channels, approvals, and verified coding handoffs around `kiro-cli acp`.\n\nRiskiest TODOs:\n1. Harden remote deployment auth\n2. Expand Telegram group mention UX\n3. Document workspace lease recovery";
export const TELEGRAM_IN = "Hey kiro — anything blocked on the launch checklist?";
export const TELEGRAM_OUT = "Nothing blocking. Checklist is green; I'll watch the Slack deploy thread.";

export const WORKFLOW_NAME = "Ship the release safely";
export const REVIEWER_OUTPUT =
  "Independent review complete. Patch is bounded, checks pass, no new permission bypasses. Ready for human handoff — nothing merged automatically.";
