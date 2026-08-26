import { AnimatePresence, motion } from "framer-motion";
import type { RunPhase, TimelineEntry, PermissionRequest } from "../../types";
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

export type InspectTab = "run" | "work" | "safety" | "memory";

const TABS: { id: InspectTab; label: string }[] = [
  { id: "run", label: "Live" },
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
            <div>
              <p className="eyebrow">Inspect</p>
              <h2>{inspectTitle}</h2>
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
              <p className="activity-empty">Choose a bot to inspect its activity and controls.</p>
            ) : tab === "run" ? (
              <LiveTab
                phase={phase}
                detail={runDetail}
                permissions={permissions}
                onDecide={onDecide}
                timeline={timeline}
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
