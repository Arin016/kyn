import React from "react";
import { AriGlyph } from "../../src/components/AriGlyph";
import { Sidebar } from "../../src/components/Sidebar";
import { Thread } from "../../src/components/chat/Thread";
import type { Part } from "../../src/components/chat/Message";
import { DemoComposer } from "./DemoComposer";
import { DemoInspect } from "./DemoInspect";
import type { Channel, ChannelEvent, PermissionRequest, RunPhase, Surface, TimelineEntry } from "../../src/types";

export interface ConsoleSnapshot {
  surface: Surface;
  phase: RunPhase;
  runDetail: string;
  parts: Part[];
  permissions: PermissionRequest[];
  timeline: TimelineEntry[];
  unread: Record<string, number>;
  channels: Channel[];
  channelEvents: ChannelEvent[];
  localLive: boolean;
  inspectOpen: boolean;
  inspectOpenedAt: number;
  composerValue: string;
  composerBusy: boolean;
  composerDisabled: boolean;
  mirrorNote: boolean;
  sendHot: boolean;
  approveHot: boolean;
  emptyGreeting: string;
}

const BOTS = [
  { name: "builder", cwd: "/Users/arin.mallanna/personal", model: "Kiro" },
  { name: "reviewer", cwd: "/Users/arin.mallanna/personal", model: "Kiro" },
  { name: "triage", cwd: "/Users/arin.mallanna/personal/kyn", agent: "triage" },
];

const PHASE_TITLE: Record<RunPhase, string> = {
  idle: "Idle",
  starting: "Starting",
  running: "Working",
  waiting: "Approval needed",
  stopping: "Stopping",
  error: "Error",
};

const noop = () => undefined;

interface Props {
  snapshot: ConsoleSnapshot;
}

export const StagedConsole: React.FC<Props> = ({ snapshot }) => {
  const title =
    snapshot.surface.kind === "channel"
      ? "Telegram · builder"
      : "builder";

  return (
    <div className="app demo-console" data-theme="dark">
      <Sidebar
        bots={BOTS}
        selectedBot="builder"
        onSelectBot={noop}
        groups={[]}
        activeGroup={null}
        onSelectGroup={noop}
        onNewGroup={noop}
        channels={snapshot.channels}
        channelEvents={snapshot.channelEvents}
        surface={snapshot.surface}
        onSelectSurface={noop}
        unread={snapshot.unread}
        localLive={snapshot.localLive}
        connected
        open
        onClose={noop}
        onNewBot={noop}
        workspace="conversation"
        onWorkspaceChange={noop}
      />

      <main className="main">
        <header className="header">
          <div className="header-brand">
            <span className="header-logo" aria-hidden>
              <AriGlyph size={20} />
            </span>
            <span
              style={{
                fontWeight: 600,
                fontSize: "0.95rem",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {title}
            </span>
          </div>
          <div className="header-actions">
            <button type="button" className="workflow-launch">
              Workflows
            </button>
            <span className="status-pill" data-state={snapshot.phase}>
              <span className="status-dot" aria-hidden />
              {PHASE_TITLE[snapshot.phase]}
            </span>
            <button
              type="button"
              className={`icon-btn${snapshot.inspectOpen ? " active" : ""}`}
              aria-pressed={snapshot.inspectOpen}
            >
              Inspect
            </button>
          </div>
        </header>

        <div className="thread-scroll">
          <Thread
            parts={snapshot.parts}
            emptyEyebrow="Ari · AGENT WORKSPACE"
            emptyGreeting={snapshot.emptyGreeting}
            emptyDescription="Give your bot a clear task, then steer or review its work as it goes."
            suggestions={[
              { title: "Understand this project", detail: "Get a quick map of what it does", prompt: "Summarize what this repo does" },
              { title: "Review recent changes", detail: "Spot risk in the latest work", prompt: "What changed here recently?" },
              { title: "Rank open TODOs", detail: "Find the most urgent unfinished work", prompt: "Find TODOs and rank them by urgency" },
              { title: "Add a safety net", detail: "Test the riskiest paths", prompt: "Write tests for the riskiest module" },
            ]}
            onSuggestion={noop}
            onApproval={noop}
          />
        </div>

        <DemoComposer
          value={snapshot.composerValue}
          hint={
            snapshot.mirrorNote
              ? "This view follows the live remote thread."
              : "/Users/arin.mallanna/personal"
          }
          mirrorNote={snapshot.mirrorNote}
          placeholder="Message Kiro…"
          busy={snapshot.composerBusy}
          disabled={snapshot.composerDisabled}
          sendHot={snapshot.sendHot}
        />
      </main>

      <DemoInspect
        open={snapshot.inspectOpen}
        openedAt={snapshot.inspectOpenedAt}
        phase={snapshot.phase}
        runDetail={snapshot.runDetail}
        permissions={snapshot.permissions}
        timeline={snapshot.timeline}
        approveHot={snapshot.approveHot}
      />
    </div>
  );
};
