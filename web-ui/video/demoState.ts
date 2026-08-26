import type { Part } from "../src/components/chat/Message";
import type { Channel, ChannelEvent, PermissionRequest, TimelineEntry } from "../src/types";
import type { ConsoleSnapshot } from "./components/StagedConsole";
import {
  ASSISTANT_FULL,
  PROMPT,
  TELEGRAM_IN,
  TELEGRAM_OUT,
  progress,
  scenes,
  sec,
  typeChars,
} from "./timeline";
import { workflowCursorPlan } from "./workflowState";

const CHANNEL: Channel = {
  id: "iphone-telegram",
  name: "Phone Telegram",
  kind: "telegram",
  enabled: true,
  outbound_delivery_configured: true,
};

function channelEventsFor(frame: number): ChannelEvent[] {
  const live = frame >= scenes.telegram.start + sec(2) && frame < scenes.approve.start + sec(4);
  const responded = frame >= scenes.telegram.start + sec(6);
  return [
    {
      id: "evt-1",
      binding_id: CHANNEL.id,
      thread_key: "8961333191",
      text: TELEGRAM_IN,
      status: responded ? "responded" : live ? "running" : "queued",
      sender: "8961333191",
      source: "telegram",
      created_at: "2026-08-26T12:04:00Z",
      response_text: responded ? TELEGRAM_OUT : undefined,
      run_id: "run-telegram-1",
    },
  ];
}

function streamParts(frame: number): Part[] {
  const parts: Part[] = [{ type: "user", text: PROMPT }];
  const streamP = progress(frame, scenes.stream.start, scenes.stream.start + sec(7));
  const text = typeChars(ASSISTANT_FULL, streamP);

  if (frame >= scenes.stream.start + sec(0.6) && frame < scenes.stream.start + sec(2.4)) {
    parts.push({
      type: "reasoning",
      id: "r1",
      text: "Scanning README, architecture docs, and open TODOs…",
      running: frame < scenes.stream.start + sec(2.2),
    });
  } else if (frame >= scenes.stream.start + sec(2.4) && frame < scenes.stream.start + sec(4)) {
    parts.push({
      type: "tool",
      id: "t1",
      title: "filesystem.read · README.md",
      status: frame < scenes.stream.start + sec(3.5) ? "running" : "done",
    });
  }

  if (text) {
    parts.push({
      type: "assistant-text",
      text,
      streaming: streamP < 1 && frame < scenes.telegram.start,
    });
  }

  if (frame >= scenes.approve.start + sec(1)) {
    parts.push({
      type: "approval",
      id: "perm-1",
      title: "Allow bash? ls /Users/arin.mallanna/personal",
    });
  }

  return parts;
}

function telegramParts(frame: number): Part[] {
  const parts: Part[] = [{ type: "channel", text: TELEGRAM_IN, label: "Telegram" }];
  const replyP = progress(frame, scenes.telegram.start + sec(5), scenes.telegram.start + sec(8));
  if (replyP > 0) {
    parts.push({
      type: "assistant-text",
      text: typeChars(TELEGRAM_OUT, replyP),
      streaming: replyP < 1,
    });
  } else if (frame >= scenes.telegram.start + sec(2.5)) {
    parts.push({ type: "assistant-text", text: "", streaming: true });
  }
  return parts;
}

function timelineFor(frame: number): TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  if (frame >= scenes.stream.start + sec(1)) {
    entries.push({ id: 1, kind: "tool", detail: "filesystem.read · README.md", at: "12:02" });
  }
  if (frame >= scenes.telegram.start + sec(2)) {
    entries.unshift({ id: 2, kind: "tool", detail: "inbound Telegram", at: "12:04" });
  }
  if (frame >= scenes.approve.start) {
    entries.unshift({ id: 3, kind: "permission", detail: "Allow bash?", at: "12:05" });
  }
  if (frame >= scenes.approve.start + sec(8)) {
    entries.unshift({ id: 4, kind: "complete", detail: "Run completed", at: "12:06" });
  }
  return entries;
}

export function buildSnapshot(frame: number): ConsoleSnapshot {
  const onTelegram = frame >= scenes.telegram.start + sec(3) && frame < scenes.close.start;
  const typing = frame >= scenes.type.start && frame < scenes.stream.start;
  const typed = typeChars(PROMPT, progress(frame, scenes.type.start, scenes.type.start + sec(5.5)));
  const sent = frame >= scenes.stream.start;
  const waiting = frame >= scenes.approve.start && frame < scenes.approve.start + sec(9);
  const running =
    (frame >= scenes.stream.start && frame < scenes.telegram.start + sec(8)) ||
    (frame >= scenes.approve.start + sec(9) && frame < scenes.close.start);

  const permissions: PermissionRequest[] =
    waiting || (frame >= scenes.approve.start && frame < scenes.approve.start + sec(9.5))
      ? [
          {
            id: "perm-1",
            title: "Allow bash? ls /Users/arin.mallanna/personal",
            toolName: "bash",
            source: "channel:iphone-telegram",
          },
        ]
      : [];

  const unreadKey = `channel:${CHANNEL.id}:8961333191`;
  const unread =
    frame >= scenes.telegram.start && frame < scenes.telegram.start + sec(3)
      ? { [unreadKey]: 1 }
      : {};

  let phase: ConsoleSnapshot["phase"] = "idle";
  let runDetail = "";
  if (frame >= scenes.type.start + sec(5.8) && frame < scenes.stream.start) {
    phase = "starting";
    runDetail = "Creating a persistent Kiro run…";
  } else if (waiting) {
    phase = "waiting";
    runDetail = "Kiro needs permission to continue.";
  } else if (running || (frame >= scenes.stream.start && frame < scenes.approve.start)) {
    phase = "running";
    runDetail = onTelegram ? "Live from your phone…" : "Kiro is working in this bot's persistent session.";
  }

  const inspectOpen =
    frame >= scenes.stream.start + sec(3) ||
    waiting ||
    (frame >= scenes.approve.start && frame < scenes.close.start);

  const inspectOpenedAt =
    frame >= scenes.approve.start
      ? scenes.approve.start
      : frame >= scenes.stream.start + sec(3)
        ? scenes.stream.start + sec(3)
        : 0;

  return {
    surface: onTelegram
      ? { kind: "channel", id: CHANNEL.id, threadKey: "8961333191" }
      : { kind: "local" },
    phase,
    runDetail,
    parts: onTelegram ? telegramParts(frame) : sent ? streamParts(frame) : [],
    permissions,
    timeline: timelineFor(frame),
    unread,
    channels: [CHANNEL],
    channelEvents: channelEventsFor(frame),
    localLive: phase === "running" || phase === "waiting" || phase === "starting",
    inspectOpen,
    inspectOpenedAt,
    composerValue: typing ? typed : "",
    composerBusy: phase === "running" || phase === "waiting" || phase === "starting",
    composerDisabled: onTelegram || phase === "running" || phase === "waiting",
    mirrorNote: onTelegram,
    sendHot: typing && typed.length === PROMPT.length && frame < scenes.stream.start,
    approveHot: waiting && frame >= scenes.approve.start + sec(4) && frame < scenes.approve.start + sec(8),
    emptyGreeting: "What should builder do?",
  };
}

export type CursorPlan = {
  x: number;
  y: number;
  clicking: boolean;
  visible: boolean;
  clickFrame: number;
};

export function cursorPlan(frame: number): CursorPlan {
  if (frame >= scenes.workflow.start && frame < scenes.workflow.end) {
    return workflowCursorPlan(frame);
  }

  // Coordinates assume 1920×1080 console layout (sidebar ~260px).
  if (frame < scenes.selectBot.start) {
    return { x: 960, y: 540, clicking: false, visible: false, clickFrame: 0 };
  }

  const bot = { x: 150, y: 268 };
  const composer = { x: 980, y: 980 };
  const send = { x: 1488, y: 990 };
  const telegram = { x: 160, y: 430 };
  const allow = { x: 1680, y: 300 };

  if (frame < scenes.type.start) {
    const t = progress(frame, scenes.selectBot.start, scenes.selectBot.start + sec(2.5));
    const clickStart = scenes.selectBot.start + sec(2.5);
    return {
      x: 420 + (bot.x - 420) * t,
      y: 200 + (bot.y - 200) * t,
      clicking: frame >= clickStart && frame < clickStart + sec(0.6),
      visible: true,
      clickFrame: clickStart,
    };
  }

  if (frame < scenes.stream.start) {
    const toComposer = progress(frame, scenes.type.start, scenes.type.start + sec(1));
    if (toComposer < 1) {
      return {
        x: bot.x + (composer.x - bot.x) * toComposer,
        y: bot.y + (composer.y - bot.y) * toComposer,
        clicking: false,
        visible: true,
        clickFrame: 0,
      };
    }
    const toSend = progress(frame, scenes.type.start + sec(5.2), scenes.type.start + sec(6));
    const clickStart = scenes.type.start + sec(5.8);
    return {
      x: composer.x + (send.x - composer.x) * toSend,
      y: composer.y + (send.y - composer.y) * toSend,
      clicking: frame >= clickStart && frame < scenes.stream.start,
      visible: true,
      clickFrame: clickStart,
    };
  }

  if (frame < scenes.stream.start + sec(2)) {
    return {
      x: send.x,
      y: send.y,
      clicking: false,
      visible: frame < scenes.stream.start + sec(1),
      clickFrame: 0,
    };
  }

  if (frame < scenes.workflow.start) {
    const t = progress(frame, scenes.stream.start + sec(5), scenes.workflow.start - sec(1));
    const workflowsBtn = { x: 1580, y: 48 };
    const clickStart = scenes.workflow.start - sec(1.2);
    return {
      x: send.x + (workflowsBtn.x - send.x) * t,
      y: send.y + (workflowsBtn.y - send.y) * t,
      clicking: frame >= clickStart && frame < scenes.workflow.start,
      visible: true,
      clickFrame: clickStart,
    };
  }

  if (frame < scenes.telegram.start + sec(3)) {
    return { x: 1580, y: 48, clicking: false, visible: false, clickFrame: 0 };
  }

  if (frame < scenes.approve.start) {
    const t = progress(frame, scenes.telegram.start + sec(1), scenes.telegram.start + sec(2.8));
    const clickStart = scenes.telegram.start + sec(2.6);
    return {
      x: send.x + (telegram.x - send.x) * t,
      y: send.y + (telegram.y - send.y) * t,
      clicking: frame >= clickStart && frame < scenes.telegram.start + sec(3.2),
      visible: true,
      clickFrame: clickStart,
    };
  }

  if (frame < scenes.approve.start + sec(9)) {
    const t = progress(frame, scenes.approve.start + sec(2), scenes.approve.start + sec(5));
    const clickStart = scenes.approve.start + sec(4.8);
    return {
      x: telegram.x + (allow.x - telegram.x) * t,
      y: telegram.y + (allow.y - telegram.y) * t,
      clicking: frame >= clickStart && frame < scenes.approve.start + sec(7.5),
      visible: true,
      clickFrame: clickStart,
    };
  }

  return { x: allow.x, y: allow.y, clicking: false, visible: false, clickFrame: 0 };
}
