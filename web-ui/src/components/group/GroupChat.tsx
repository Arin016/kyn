import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../api";
import { DEMO_GROUP_DETAIL, demoGroupReply } from "../../lib/demoConsole";
import {
  buildGroupCommands,
  parseMentions,
  splitMentions,
} from "../../lib/slash";
import type { Bot, GroupDetail, GroupMessage } from "../../types";
import { BotAvatar } from "../BotAvatar";
import { Composer } from "../chat/Composer";
import { ThinkingDots } from "../chat/ThinkingDots";
import { useToast } from "../../hooks/useToast";

const POLL_MS = 1500;

const STATUS_LABEL: Record<string, string> = {
  idle: "Paused",
  running: "Working",
  stopped: "Stopped",
  done: "Aim met",
  error: "Error",
};

function mergeMessages(
  current: GroupMessage[],
  incoming: GroupMessage[],
): GroupMessage[] {
  if (incoming.length === 0) return current;
  const seen = new Set(current.map((message) => message.id));
  const merged = [...current];
  for (const message of incoming) {
    if (seen.has(message.id)) continue;
    merged.push(message);
    seen.add(message.id);
  }
  merged.sort((left, right) => left.id - right.id);
  return merged;
}

function timeLabel(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Message body with @mentions highlighted (no HTML injection involved). */
function MessageBody({ text, members }: { text: string; members: string[] }) {
  const segments = useMemo(() => splitMentions(text, members), [text, members]);
  return (
    <>
      {segments.map((segment, index) =>
        segment.kind === "mention" ? (
          <span className="group-mention" key={index}>
            @{segment.value}
          </span>
        ) : (
          <span key={index}>{segment.value}</span>
        ),
      )}
    </>
  );
}

interface Props {
  groupId: string;
  bots: Bot[];
  marketing: boolean;
  onBack: () => void;
  onChanged: () => void;
  onDeleted: () => void;
}

export function GroupChat({
  groupId,
  bots,
  marketing,
  onBack,
  onChanged,
  onDeleted,
}: Props) {
  const { showToast } = useToast();
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [error, setError] = useState("");
  const [contextNote, setContextNote] = useState("");
  const [briefOpen, setBriefOpen] = useState(false);
  const contextDraftDirtyRef = useRef(false);
  const lastIdRef = useRef(0);
  const refreshGenRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(
    async (full = true) => {
      if (marketing) return;
      // Generation guard: a slow poll for the previous group must never
      // write into the newly opened one.
      const generation = ++refreshGenRef.current;
      try {
        const data = await api.group(groupId, full ? 0 : lastIdRef.current);
        if (refreshGenRef.current !== generation) return;
        setDetail(data);
        if (!contextDraftDirtyRef.current)
          setContextNote(data.context_note || "");
        setMessages((current) =>
          full
            ? mergeMessages([], data.messages)
            : mergeMessages(current, data.messages),
        );
        lastIdRef.current = Math.max(
          lastIdRef.current,
          ...data.messages.map((message) => message.id),
        );
        setError("");
      } catch (exc) {
        if (refreshGenRef.current !== generation) return;
        setError((exc as Error).message || "Could not load this group");
      }
    },
    [groupId, marketing],
  );

  useEffect(() => {
    contextDraftDirtyRef.current = false;
    setBriefOpen(false);
    setContextNote("");
    if (marketing) {
      const demo = {
        ...DEMO_GROUP_DETAIL,
        group: { ...DEMO_GROUP_DETAIL.group, id: groupId },
      };
      setDetail(demo);
      setContextNote(demo.context_note || "");
      setMessages(demo.messages);
      lastIdRef.current = demo.messages.length;
      return;
    }
    void refresh(true);
  }, [groupId, marketing, refresh]);

  useEffect(() => {
    if (marketing) return;
    const timer = window.setInterval(() => void refresh(false), POLL_MS);
    return () => window.clearInterval(timer);
  }, [marketing, refresh]);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, detail?.speaking?.bot]);

  const group = detail?.group;
  const running = Boolean(detail?.running);
  const speaking = detail?.speaking?.bot || "";
  const memberNames = useMemo(() => group?.members || [], [group?.members]);

  const roster = useMemo(() => {
    const names = group?.members || [];
    const known = bots.filter((bot) => names.includes(bot.name));
    return known.length === names.length
      ? known
      : names.map((name) => known.find((bot) => bot.name === name) || { name });
  }, [group?.members, bots]);

  const commands = useMemo(
    () =>
      buildGroupCommands({
        running,
        onStart: () => void start(),
        onStop: () => void stop(),
      }),
    // start/stop are stable enough for menu construction; running is the input.
    [running, groupId], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const post = useCallback(
    async (text: string) => {
      const mentioned = parseMentions(text, memberNames);
      if (marketing) {
        const base = Date.now();
        const human: GroupMessage = {
          id: base,
          group_id: groupId,
          author: "You",
          role: "human",
          text,
        };
        setMessages((current) => [...current, human]);
        window.setTimeout(() => {
          const author = mentioned[0] || group?.members?.[0] || "scout";
          setMessages((current) => [
            ...current,
            {
              id: base + 1,
              group_id: groupId,
              author,
              role: "bot",
              text: demoGroupReply(text, author),
            },
          ]);
        }, 1300);
        return;
      }
      try {
        const data = await api.postGroupMessage(groupId, text, true, mentioned);
        setMessages((current) =>
          mergeMessages(current, [data.message, ...data.group.messages]),
        );
        lastIdRef.current = Math.max(
          lastIdRef.current,
          data.message.id,
          ...data.group.messages.map((message) => message.id),
        );
        setDetail(data.group);
        if (mentioned.length > 0) {
          showToast(
            `Asked ${mentioned.join(", ")} to reply — the rest will hold.`,
          );
        }
        onChanged();
      } catch (exc) {
        showToast(
          (exc as Error).message || "Could not send that message",
          true,
        );
      }
    },
    [groupId, group?.members, memberNames, marketing, onChanged, showToast],
  );

  const saveContext = useCallback(
    async (note: string) => {
      if (marketing) {
        showToast("Demo preview — pinned context needs a local daemon.", false);
        return;
      }
      try {
        const data = await api.setGroupContext(groupId, note);
        setDetail(data);
        setContextNote(data.context_note || "");
        contextDraftDirtyRef.current = false;
        showToast(
          note.trim()
            ? "Shared context pinned for this group."
            : "Shared context cleared.",
        );
      } catch (exc) {
        showToast((exc as Error).message || "Could not pin the brief", true);
      }
    },
    [groupId, marketing, showToast],
  );

  const start = useCallback(async () => {
    if (marketing) {
      showToast("Demo preview — group rounds need a local daemon.", false);
      return;
    }
    try {
      setDetail(await api.startGroup(groupId));
      onChanged();
      window.setTimeout(() => void refresh(false), 800);
    } catch (exc) {
      showToast((exc as Error).message || "Could not start the group", true);
    }
  }, [groupId, marketing, onChanged, refresh, showToast]);

  const stop = useCallback(async () => {
    if (marketing) return;
    try {
      setDetail(await api.stopGroup(groupId));
      onChanged();
    } catch (exc) {
      showToast((exc as Error).message || "Could not stop the group", true);
    }
  }, [groupId, marketing, onChanged, showToast]);

  const remove = useCallback(async () => {
    if (marketing) {
      onDeleted();
      return;
    }
    try {
      await api.deleteGroup(groupId);
      onDeleted();
    } catch (exc) {
      showToast((exc as Error).message || "Could not delete the group", true);
    }
  }, [groupId, marketing, onDeleted, showToast]);

  const status = group?.status || "idle";
  const savedContext = (detail?.context_note || "").trim();
  const hasPinnedContext = Boolean(savedContext);
  const contextDirty = contextNote.trim() !== savedContext;
  const contextId = `group-context-${groupId}`;

  return (
    <div className="group-surface">
      <header className="group-header">
        <button
          type="button"
          className="group-back"
          onClick={onBack}
          aria-label="Back to bots"
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden
          >
            <path
              d="M15 6l-6 6 6 6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          All chats
        </button>

        <div className="group-stack" aria-hidden>
          {roster.slice(0, 4).map((bot, index) => (
            <span
              key={bot.name}
              className="group-stack-item"
              style={{ zIndex: 4 - index }}
            >
              <BotAvatar name={bot.name} size={34} />
            </span>
          ))}
        </div>

        <div className="group-heading">
          <strong>{group?.name || "Group chat"}</strong>
          <span className="group-heading-line">
            <span
              className={`status-pill${running ? "" : " quiet"}`}
              data-state={running ? "running" : "idle"}
            >
              <span className="status-dot" aria-hidden />
              {speaking
                ? `${speaking} is replying`
                : !running && group?.speaker
                  ? `${group.speaker} was asked to reply`
                  : STATUS_LABEL[status] || status}
            </span>
            <span className="group-count">
              {roster.length} bot{roster.length === 1 ? "" : "s"}
            </span>
          </span>
        </div>

        <div className="group-actions">
          <button
            type="button"
            className={`mini-ghost group-context-toggle${hasPinnedContext ? " is-pinned" : ""}`}
            aria-label={hasPinnedContext ? "Edit shared context" : "Add shared context"}
            aria-expanded={briefOpen}
            aria-controls={contextId}
            onClick={() => setBriefOpen((open) => !open)}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
              <path d="M7 4.75h10a2 2 0 0 1 2 2v12.5H5V6.75a2 2 0 0 1 2-2Z" strokeLinejoin="round" />
              <path d="M8.5 9h7M8.5 12.5h7M8.5 16h4" strokeLinecap="round" />
            </svg>
            <span>Brief</span>
            {hasPinnedContext && <span className="group-context-pinned">Pinned</span>}
          </button>
          {running ? (
            <button
              type="button"
              className="mini-danger"
              onClick={() => void stop()}
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              className="mini-primary"
              onClick={() => void start()}
            >
              {status === "idle" && messages.length === 0
                ? "Start round"
                : "Next round"}
            </button>
          )}
          <button
            type="button"
            className="mini-ghost"
            onClick={() => void remove()}
          >
            Delete
          </button>
        </div>
      </header>

      {briefOpen && (
        <section className="group-context" id={contextId} aria-label="Shared group context">
          <div className="group-context-head">
            <div className="group-context-heading">
              <span className="group-context-title">Shared context</span>
              <span className="group-context-hint">Visible to every bot in this chat.</span>
            </div>
            <button
              type="button"
              className="group-context-close"
              aria-label="Close shared context"
              onClick={() => setBriefOpen(false)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="m6 6 12 12M18 6 6 18" strokeLinecap="round" />
              </svg>
            </button>
          </div>
          <textarea
            className="group-context-input"
            rows={3}
            value={contextNote}
            placeholder="Share decisions, findings, or constraints the next bot should know."
            onChange={(event) => {
              const next = event.target.value;
              contextDraftDirtyRef.current = next.trim() !== (detail?.context_note || "").trim();
              setContextNote(next);
            }}
            aria-label="Shared context for every bot in this group"
          />
          <div className="group-context-actions">
            {contextNote.trim() && (
              <button
                type="button"
                className="mini-ghost"
                onClick={() => void saveContext("")}
              >
                Clear
              </button>
            )}
            <button
              type="button"
              className="mini-primary"
              disabled={!contextDirty}
              onClick={() => void saveContext(contextNote)}
            >
              {contextNote.trim() ? "Pin brief" : "Clear brief"}
            </button>
          </div>
        </section>
      )}

      {group?.aim ? <p className="group-aim">{group.aim}</p> : null}
      {error ? <p className="group-error">{error}</p> : null}

      <div className="group-scroll" ref={scrollRef}>
        <ol className="group-thread">
          {messages.map((message) => {
            if (message.role === "system") {
              return (
                <li key={message.id} className="group-note">
                  {message.text}
                </li>
              );
            }
            const human = message.role === "human";
            return (
              <li
                key={message.id}
                className={`group-msg${human ? " is-human" : ""}`}
              >
                {!human && (
                  <BotAvatar
                    name={message.author}
                    size={32}
                    className="group-msg-avatar"
                  />
                )}
                <div className="group-msg-body">
                  <span className="group-msg-meta">
                    <strong>{human ? "You" : message.author}</strong>
                    {timeLabel(message.created_at) ? (
                      <span>{timeLabel(message.created_at)}</span>
                    ) : null}
                  </span>
                  <div className="group-bubble">
                    <MessageBody text={message.text} members={memberNames} />
                  </div>
                </div>
              </li>
            );
          })}
          {speaking ? (
            <li className="group-msg">
              <BotAvatar
                name={speaking}
                size={32}
                className="group-msg-avatar thinking-avatar"
              />
              <div className="group-msg-body">
                <span className="group-msg-meta">
                  <strong>{speaking}</strong>
                  <span>typing</span>
                </span>
                <div
                  className="group-bubble is-typing"
                  aria-label={`${speaking} is typing`}
                >
                  <ThinkingDots />
                </div>
              </div>
            </li>
          ) : null}
          {messages.length === 0 && !speaking ? (
            <li className="group-note">
              No messages yet. Start a round and the bots will take turns
              working the shared aim.
            </li>
          ) : null}
        </ol>
      </div>

      <Composer
        disabled={false}
        busy={running}
        hint={
          memberNames.length > 0
            ? `@${memberNames[0]} to direct a question · everyone sees this`
            : "Everyone in this group sees this"
        }
        mirrorNote={false}
        placeholder={
          running
            ? "Add to the thread — the next speaker reads it…"
            : `Message ${group?.name || "the group"} — @name to ask one bot…`
        }
        commands={commands}
        members={memberNames}
        onSubmit={(message) => void post(message)}
        onStop={() => void stop()}
      />
    </div>
  );
}
