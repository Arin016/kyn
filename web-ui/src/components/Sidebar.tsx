import { useMemo, useState } from "react";
import type { Channel, ChannelEvent, Group, Surface } from "../types";
import { BotAvatar } from "./BotAvatar";
import { KiroGlyph } from "./KiroGlyph";
import { ThemeToggle } from "./ThemeToggle";

/** The chief-of-staff bot carries fleet tools; the badge marks it in the roster. */
export function isChiefBot(name: string): boolean {
  return name.trim().toLowerCase() === "chief";
}

interface Props {
  bots: { name: string; cwd?: string; model?: string; agent?: string; engine?: string }[];
  selectedBot: string | null;
  onSelectBot: (name: string) => void;
  groups: Group[];
  activeGroup: string | null;
  onSelectGroup: (groupId: string) => void;
  onNewGroup: () => void;
  channels: Channel[];
  channelEvents: ChannelEvent[];
  surface: Surface;
  onSelectSurface: (surface: Surface) => void;
  unread: Record<string, number>;
  localLive: boolean;
  connected: boolean;
  connectionLabel?: string;
  open: boolean;
  onClose: () => void;
  onNewBot: () => void;
  workspace: "conversation" | "workflows";
  onWorkspaceChange: (workspace: "conversation" | "workflows") => void;
}

export function Sidebar({
  bots,
  selectedBot,
  onSelectBot,
  groups,
  activeGroup,
  onSelectGroup,
  onNewGroup,
  localLive,
  connected,
  connectionLabel,
  open,
  onClose,
  onNewBot,
  workspace,
  onWorkspaceChange,
}: Props) {
  const [query, setQuery] = useState("");

  const filteredBots = useMemo(
    () => bots.filter((bot) => bot.name.toLowerCase().includes(query.toLowerCase())),
    [bots, query],
  );

  return (
    <aside className={`sidebar${open ? " is-open" : " collapsed"}`} aria-label="Bots and channels">
      <div className="sidebar-inner">
        <div className="sidebar-top">
          <div className="sidebar-brand">
            <KiroGlyph className="sidebar-brand-mark" size={24} />
            <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--fg-muted)" }}>KYN</span>
          </div>
          <button
            type="button"
            className="sidebar-close"
            aria-label="Close sidebar"
            onClick={onClose}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M15 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
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

        <div className="sidebar-heading">
          Groups
          <button
            type="button"
            className="sidebar-heading-add"
            onClick={onNewGroup}
            aria-label="New group chat"
            title="Group bots around one aim"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
              <path d="M12 5v14M5 12h14" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <ul className="sidebar-list" aria-label="Group chats">
          {groups.length === 0 && (
            <li>
              <p className="activity-empty">Group bots around one shared aim.</p>
            </li>
          )}
          {groups.map((group) => (
            <li key={group.id}>
              <button
                type="button"
                className={`side-item side-group${activeGroup === group.id ? " selected" : ""}`}
                aria-current={activeGroup === group.id ? "page" : undefined}
                onClick={() => onSelectGroup(group.id)}
              >
                <span className="side-stack" aria-hidden>
                  {group.members.slice(0, 3).map((member, index) => (
                    <span key={member} className="side-stack-item" style={{ zIndex: 3 - index }}>
                      <BotAvatar name={member} size={30} />
                    </span>
                  ))}
                </span>
                <span className="side-item-copy">
                  <span className="side-item-name">{group.name}</span>
                  <span className="side-item-meta">
                    <span className="side-item-meta-text">
                      {group.members.length} bot{group.members.length === 1 ? "" : "s"}
                      {group.running ? " · working" : group.status === "done" ? " · aim met" : ""}
                    </span>
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>

        <div className="sidebar-heading">Bots</div>
        <ul className="sidebar-list" aria-label="Available bots">
          {filteredBots.length === 0 && <li><p className="activity-empty">No bots yet.</p></li>}
          {filteredBots.map((bot) => (
            <li key={bot.name}>
              <button
                type="button"
                className={`side-item side-bot${selectedBot === bot.name ? " selected" : ""}`}
                aria-current={selectedBot === bot.name ? "page" : undefined}
                onClick={() => onSelectBot(bot.name)}
              >
                <span className="side-avatar">
                  <BotAvatar name={bot.name} size={38} />
                  {selectedBot === bot.name && localLive && (
                    <span className="side-avatar-live" aria-label="Working" />
                  )}
                </span>
                <span className="side-item-copy">
                  <span className="side-item-name">
                    {bot.name}
                    {isChiefBot(bot.name) && <span className="chief-badge">Chief of staff</span>}
                  </span>
                  <span className="side-item-meta">
                    {bot.engine && (
                      <span className="engine-badge" data-engine={bot.engine.toLowerCase()}>
                        {bot.engine}
                      </span>
                    )}
                    <span className="side-item-meta-text">
                      {bot.model || bot.agent || bot.cwd || "Kiro agent"}
                    </span>
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>

        <div className="sidebar-footer">
          <span>{connectionLabel ?? (connected ? "Control plane online" : "Offline")}</span>
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}
