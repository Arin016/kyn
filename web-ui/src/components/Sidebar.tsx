import { useMemo, useState } from "react";
import type { Channel, ChannelEvent, Surface } from "../types";
import type { Theme } from "../lib/theme";
import { KiroGlyph } from "./KiroGlyph";

interface Props {
  bots: { name: string; cwd?: string; model?: string; agent?: string }[];
  selectedBot: string | null;
  onSelectBot: (name: string) => void;
  channels: Channel[];
  channelEvents: ChannelEvent[];
  surface: Surface;
  onSelectSurface: (surface: Surface) => void;
  unread: Record<string, number>;
  localLive: boolean;
  connected: boolean;
  open: boolean;
  theme: Theme;
  onToggleTheme: () => void;
  onNewBot: () => void;
  workspace: "conversation" | "workflows";
  onWorkspaceChange: (workspace: "conversation" | "workflows") => void;
}

function latestThread(events: ChannelEvent[], channelId: string): { threadKey: string; preview: string; live: boolean } {
  const mine = events.filter((event) => event.binding_id === channelId);
  const newest = [...mine]
    .sort((a, b) => String(a.created_at ?? "").localeCompare(String(b.created_at ?? "")))
    .at(-1);
  if (!newest) return { threadKey: "", preview: "Waiting for the first message", live: false };
  return {
    threadKey: String(newest.thread_key || ""),
    preview: String(newest.text || "Remote request").replaceAll("\n", " "),
    live: ["queued", "running"].includes(newest.status),
  };
}

export function Sidebar({
  bots,
  selectedBot,
  onSelectBot,
  channels,
  channelEvents,
  surface,
  onSelectSurface,
  unread,
  localLive,
  connected,
  open,
  theme,
  onToggleTheme,
  onNewBot,
  workspace,
  onWorkspaceChange,
}: Props) {
  const [query, setQuery] = useState("");

  const filteredBots = useMemo(
    () => bots.filter((bot) => bot.name.toLowerCase().includes(query.toLowerCase())),
    [bots, query],
  );
  const filteredChannels = useMemo(
    () => channels.filter((channel) => channel.name.toLowerCase().includes(query.toLowerCase())),
    [channels, query],
  );

  return (
    <aside className={`sidebar${open ? " is-open" : " collapsed"}`} aria-label="Bots and channels">
      <div className="sidebar-inner">
        <div className="sidebar-top">
          <KiroGlyph className="sidebar-brand-mark" size={24} />
          <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--fg-muted)" }}>KYN</span>
        </div>
        <input
          className="sidebar-search"
          placeholder="Search…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search bots and channels"
        />
        <button type="button" className="new-chat-btn" onClick={onNewBot}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M12 5v14M5 12h14" strokeLinecap="round" />
          </svg>
          New bot
        </button>

        <div className="sidebar-heading">Workspace</div>
        <ul className="sidebar-list" aria-label="Workspace views">
          <li><button type="button" className={`side-item${workspace === "conversation" ? " selected" : ""}`} onClick={() => onWorkspaceChange("conversation")}><span className="side-item-mark" aria-hidden /><span className="side-item-copy"><span className="side-item-name">Conversation</span><span className="side-item-meta">Talk to one bot</span></span></button></li>
          <li><button type="button" className={`side-item${workspace === "workflows" ? " selected" : ""}`} onClick={() => onWorkspaceChange("workflows")}><span className="side-item-mark live" aria-hidden /><span className="side-item-copy"><span className="side-item-name">Workflows</span><span className="side-item-meta">Build a team graph</span></span></button></li>
        </ul>

        <div className="sidebar-heading">Bots</div>
        <ul className="sidebar-list" aria-label="Available bots">
          {filteredBots.length === 0 && <li><p className="activity-empty">No bots yet.</p></li>}
          {filteredBots.map((bot) => (
            <li key={bot.name}>
              <button
                type="button"
                className={`side-item${selectedBot === bot.name ? " selected" : ""}`}
                aria-current={selectedBot === bot.name ? "page" : undefined}
                onClick={() => onSelectBot(bot.name)}
              >
                <span
                  className={`side-item-mark${selectedBot === bot.name && localLive ? " live" : ""}`}
                  aria-hidden
                />
                <span className="side-item-copy">
                  <span className="side-item-name">{bot.name}</span>
                  <span className="side-item-meta">{bot.model || bot.agent || bot.cwd || "Kiro agent"}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>

        <div className="sidebar-heading">Channels</div>
        <ul className="sidebar-list" aria-label="Conversation surfaces">
          <li>
            <button
              type="button"
              className={`side-item${surface.kind === "local" ? " selected" : ""}`}
              onClick={() => onSelectSurface({ kind: "local" })}
            >
              <span className={`side-item-mark${surface.kind === "local" && localLive ? " live" : ""}`} aria-hidden />
              <span className="side-item-copy">
                <span className="side-item-name">This laptop</span>
                <span className="side-item-meta">Local conversation</span>
              </span>
            </button>
          </li>
          {filteredChannels.map((channel) => {
            const thread = latestThread(channelEvents, channel.id);
            const count = unread[`channel:${channel.id}:${thread.threadKey}`] || 0;
            const selected = surface.kind === "channel" && surface.id === channel.id;
            return (
              <li key={channel.id}>
                <button
                  type="button"
                  className={`side-item${selected ? " selected" : ""}`}
                  onClick={() =>
                    onSelectSurface({ kind: "channel", id: channel.id, threadKey: thread.threadKey })
                  }
                >
                  <span className={`side-item-mark${thread.live ? " live" : ""}`} aria-hidden />
                  <span className="side-item-copy">
                    <span className="side-item-name">
                      {channel.kind === "telegram" ? "Telegram" : channel.name}
                    </span>
                    <span className="side-item-meta">{thread.preview.slice(0, 44)}</span>
                  </span>
                  {count > 0 && <span className="side-unread">{count}</span>}
                </button>
              </li>
            );
          })}
        </ul>

        <div className="sidebar-footer">
          <span>{connected ? "Control plane online" : "Offline"}</span>
          <button type="button" className="theme-toggle" onClick={onToggleTheme} aria-label="Toggle color theme">
            {theme === "dark" ? "Light" : "Dark"}
          </button>
        </div>
      </div>
    </aside>
  );
}
