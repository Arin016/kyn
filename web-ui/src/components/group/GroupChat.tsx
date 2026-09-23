import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../api";
import { DEMO_GROUP_DETAIL, demoGroupReply } from "../../lib/demoConsole";
import { buildGroupCommands, parseMentions, splitMentions } from "../../lib/slash";
import type { Bot, GroupDetail, GroupMessage } from "../../types";
import { BotAvatar } from "../BotAvatar";
import { Composer } from "../chat/Composer";
import { useToast } from "../../hooks/useToast";

const POLL_MS = 1500;

const STATUS_LABEL: Record<string, string> = {
  idle: "Paused",
  running: "Working",
  stopped: "Stopped",
  done: "Aim met",
  error: "Error",
};

function mergeMessages(current: GroupMessage[], incoming: GroupMessage[]): GroupMessage[] {
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
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** Message body with @mentions highlighted (no HTML injection involved). */
function MessageBody({ text, members }: { text: string; members: string[] }) {
  const segments = useMemo(() => splitMentions(text, members), [text, members]);
  return (
    <>
      {segments.map((segment, index) =>
        segment.kind === "mention" ? (
          <span className="group-mention" key={index}>@{segment.value}</span>
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

export function GroupChat({ groupId, bots, marketing, onBack, onChanged, onDeleted }: Props) {
  const { showToast } = useToast();
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [error, setError] = useState("");
  const [contextNote, setContextNote] = useState("");
  const lastIdRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(
    async (full = true) => {
      if (marketing) return;
      try {
        const data = await api.group(groupId, full ? 0 : lastIdRef.current);
        setDetail(data);
        setContextNote(data.context_note || "");
        setMessages((current) =>
          full ? mergeMessages([], data.messages) : mergeMessages(current, data.messages),
        );
        lastIdRef.current = Math.max(
          lastIdRef.current,
          ...data.messages.map((message) => message.id),
        );
        setError("");
      } catch (exc) {
        setError((exc as Error).message || "Could not load this group");
      }
    },
    [groupId, marketing],
  );

  useEffect(() => {
    if (marketing) {
      const demo = { ...DEMO_GROUP_DETAIL, group: { ...DEMO_GROUP_DETAIL.group, id: groupId } };
      setDetail(demo);
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
        setMessages((current) => mergeMessages(current, [data.message, ...data.group.messages]));
        lastIdRef.current = Math.max(
          lastIdRef.current,
          data.message.id,
          ...data.group.messages.map((message) => message.id),
        );
        setDetail(data.group);
        if (mentioned.length > 0) {
          showToast(`Asked ${mentioned.join(", ")} to reply — the rest will hold.`);
        }
        onChanged();
      } catch (exc) {
        showToast((exc as Error).message || "Could not send that message", true);
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
        showToast(
          note.trim()
            ? "Handoff brief pinned — every agent in this thread will see it."
            : "Handoff brief cleared.",
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

  return (
    <div className="group-surface">
      <header className="group-header">
        <button type="button" className="group-back" onClick={onBack} aria-label="Back to bots">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M15 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          All chats
        </button>

        <div className="group-stack" aria-hidden>
          {roster.slice(0, 4).map((bot, index) => (
            <span key={bot.name} className="group-stack-item" style={{ zIndex: 4 - index }}>
              <BotAvatar name={bot.name} size={34} />
            </span>
          ))}
        </div>

        <div className="group-heading">
          <strong>{group?.name || "Group chat"}</strong>
          <span className="group-heading-line">
            <span className={`status-pill${running ? "" : " quiet"}`} data-state={running ? "running" : "idle"}>
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
          {running ? (
            <button type="button" className="mini-danger" onClick={() => void stop()}>
              Stop
            </button>
          ) : (
            <button type="button" className="mini-primary" onClick={() => void start()}>
              {status === "idle" && messages.length === 0 ? "Start round" : "Next round"}
            </button>
          )}
          <button type="button" className="mini-ghost" onClick={() => void remove()}>
            Delete
          </button>
        </div>
      </header>

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
              <li key={message.id} className={`group-msg${human ? " is-human" : ""}`}>
                {!human && <BotAvatar name={message.author} size={32} className="group-msg-avatar" />}
                <div className="group-msg-body">
                  <span className="group-msg-meta">
                    <strong>{human ? "You" : message.author}</strong>
                    {timeLabel(message.created_at) ? <span>{timeLabel(message.created_at)}</span> : null}
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
              <BotAvatar name={speaking} size={32} className="group-msg-avatar" />
              <div className="group-msg-body">
                <span className="group-msg-meta">
                  <strong>{speaking}</strong>
                  <span>typing</span>
                </span>
                <div className="group-bubble is-typing" aria-label={`${speaking} is typing`}>
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            </li>
          ) : null}
          {messages.length === 0 && !speaking ? (
            <li className="group-note">
              No messages yet. Start a round and the bots will take turns working the shared aim.
            </li>
          ) : null}
        </ol>
      </div>

      <div className="group-context">
        <div className="group-context-head">
          <span className="group-context-title">Handoff brief</span>
          <span className="group-context-hint">Pinned context every agent sees — carry findings across bots without loss.</span>
        </div>
        <textarea
          className="group-context-input"
          rows={2}
          value={contextNote}
          placeholder="e.g. scout mapped the blockers; writer owns the changelog. Reviewer already approved sections 1–3…"
          onChange={(event) => setContextNote(event.target.value)}
          onBlur={() => {
            if (contextNote.trim() !== (detail?.context_note || "").trim()) void saveContext(contextNote);
          }}
          aria-label="Pinned handoff brief for every agent in this group"
        />
        {contextNote.trim() !== (detail?.context_note || "").trim() && (
          <div className="group-context-actions">
            <button type="button" className="mini-primary" onClick={() => void saveContext(contextNote)}>
              Pin brief
            </button>
            <button
              type="button"
              className="mini-ghost"
              onClick={() => {
                setContextNote("");
                void saveContext("");
              }}
            >
              Clear
            </button>
          </div>
        )}
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
