import { AnimatePresence, motion } from "framer-motion";
import type { Bot, RunPhase, TimelineEntry, PermissionRequest } from "../../types";
import { BotAvatar } from "../BotAvatar";
import { BotTab } from "./BotTab";
import { LiveTab } from "./LiveTab";
import { WorkTab, type WorkActions } from "./WorkTab";
import { SafetyTab, type SafetyActions } from "./SafetyTab";
import { MemoryTab } from "./MemoryTab";
import type {
  AuditItem,
  BotPluginBinding,
  Channel,
  ChannelEvent,
  CodingExecution,
  DelegationPlan,
  MemoryRecord,
  Plugin,
  Policy,
  Routine,
} from "../../types";

export type InspectTab = "run" | "bot" | "work" | "safety" | "memory";

const TABS: { id: InspectTab; label: string }[] = [
  { id: "run", label: "Live" },
  { id: "bot", label: "Bot" },
  { id: "work", label: "Work" },
  { id: "safety", label: "Safety" },
  { id: "memory", label: "Memory" },
];

export interface ManagementData {
  policy: Policy | null;
  routines: Routine[];
  plugins: Plugin[];
  bindings: BotPluginBinding[];
  audit: AuditItem[];
  delegations: DelegationPlan[];
  codingExecutions: CodingExecution[];
  channels: Channel[];
  channelEvents: ChannelEvent[];
  memoryRecords: MemoryRecord[];
}

interface Props {
  open: boolean;
  tab: InspectTab;
  onTab: (tab: InspectTab) => void;
  onClose: () => void;
  inspectTitle: string;
  phase: RunPhase;
  runDetail: string;
  permissions: PermissionRequest[];
  onDecide: (id: string, decision: "once" | "reject") => void;
  timeline: TimelineEntry[];
  management: ManagementData;
  workActions: WorkActions;
  safetyActions: SafetyActions;
  hasBot: boolean;
  /** Bot identity + session controls for the Bot tab. */
  bot: Bot | null;
  runStartedAt: number | null;
  queue: number;
  onSwitchModel: (model: string) => Promise<boolean>;
  switchingDisabled: boolean;
  /** Bot-tab shortcuts: open the handoff dialog, stop the live run. */
  onHandoff: () => void;
  onStopRun: () => void;
  /** Bumped whenever a run ends so usage re-reads. */
  usageRefreshKey: number;
}

export function InspectPanel({
  open,
  tab,
  onTab,
  onClose,
  inspectTitle,
  phase,
  runDetail,
  permissions,
  onDecide,
  timeline,
  management,
  workActions,
  safetyActions,
  hasBot,
  bot,
  runStartedAt,
  queue,
  onSwitchModel,
  switchingDisabled,
  onHandoff,
  onStopRun,
  usageRefreshKey,
}: Props) {
  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          className="inspect"
          aria-label="Inspect"
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 24 }}
          transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
        >
          <header className="inspect-header">
            {bot ? <BotAvatar name={bot.name} size={38} className="inspect-avatar" /> : null}
            <div className="inspect-heading">
              <p className="eyebrow">Inspect</p>
              <h2>{inspectTitle}</h2>
              <span className="inspect-heading-meta">
                {bot ? (
                  <span className="engine-badge" data-engine={(bot.engine || "kiro").toLowerCase()}>
                    {bot.engine || "kiro"}
                  </span>
                ) : null}
                <span className={`panel-phase phase-${phase}`}>{phase === "idle" ? "Idle" : phase}</span>
              </span>
            </div>
            <button type="button" className="close-x" aria-label="Close inspect" onClick={onClose}>
              ×
            </button>
          </header>
          <nav className="panel-tabs" aria-label="Inspect views">
            {TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                className="panel-tab"
                aria-selected={tab === item.id}
                onClick={() => onTab(item.id)}
              >
                {item.label}
              </button>
            ))}
          </nav>
          <div className="panel-view">
            {!hasBot ? (
              <div className="inspect-blank">
                <h3>Nothing selected</h3>
                <p>Pick a bot or a group from the sidebar to watch its runs, work and permissions here.</p>
              </div>
            ) : tab === "run" ? (
              <LiveTab
                phase={phase}
                detail={runDetail}
                permissions={permissions}
                onDecide={onDecide}
                timeline={timeline}
              />
            ) : tab === "bot" && bot ? (
              <BotTab
                bot={bot}
                phase={phase}
                detail={runDetail}
                runStartedAt={runStartedAt}
                queue={queue}
                timelineCount={timeline.length}
                onSwitchModel={onSwitchModel}
                switchingDisabled={switchingDisabled}
                policy={management.policy}
                plugins={management.plugins}
                bindings={management.bindings}
                onHandoff={onHandoff}
                onStop={onStopRun}
                usageRefreshKey={usageRefreshKey}
              />
            ) : tab === "work" ? (
              <WorkTab
                routines={management.routines}
                codingExecutions={management.codingExecutions}
                delegations={management.delegations}
                channels={management.channels}
                channelEvents={management.channelEvents}
                actions={workActions}
              />
            ) : tab === "safety" ? (
              <SafetyTab
                policy={management.policy}
                plugins={management.plugins}
                bindings={management.bindings}
                audit={management.audit}
                actions={safetyActions}
              />
            ) : (
              <MemoryTab records={management.memoryRecords} />
            )}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
