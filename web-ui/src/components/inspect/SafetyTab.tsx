import { useEffect, useRef, useState } from "react";
import type { AuditItem, BotPluginBinding, Plugin, Policy } from "../../types";
import { shortTime } from "../../lib/format";
import { ToolPermissions } from "./ToolPermissions";
import { ActionLink, ManagementCard } from "./ManagementCard";
import { EmptyState, Badge } from "../ui/Basics";
import { NumberStepper, SegmentedControl, TagInput, ToggleSwitch } from "../ui/Pickers";
import type { Option } from "../ui/Pickers";

export interface SafetyActions {
  onSavePolicy: (policy: Policy) => Promise<void>;
  onNewPlugin: () => void;
  onDisconnectPlugin: (pluginId: string) => void;
  onUpdatePlugin: (
    pluginId: string,
    payload: { enabled?: boolean; allow_tools?: string[]; deny_tools?: string[] },
  ) => void;
}

interface Props {
  policy: Policy | null;
  plugins: Plugin[];
  bindings: BotPluginBinding[];
  audit: AuditItem[];
  actions: SafetyActions;
}

const MODES: Option<string>[] = [
  { value: "ask", label: "Ask me", hint: "Prompt before every governed tool call" },
  { value: "allow_list", label: "Allow listed", hint: "Run allowed tools silently, ask for the rest" },
  { value: "deny", label: "Deny all", hint: "Block every tool until you change this" },
];

const ENGINES = ["kiro", "opencode", "codex"];

const AUDIT_TONE: Record<string, "accent" | "success" | "warning" | "danger" | "muted"> = {
  denied: "danger",
  blocked: "danger",
  approved: "success",
  allowed: "success",
  requested: "warning",
  auto_approved: "accent",
};

export function SafetyTab({ policy, plugins, bindings, audit, actions }: Props) {
  const [approvalMode, setApprovalMode] = useState("ask");
  const [allowedTools, setAllowedTools] = useState<string[]>([]);
  const [deniedTools, setDeniedTools] = useState<string[]>([]);
  const [quotaHour, setQuotaHour] = useState(0);
  const [quotaConcurrent, setQuotaConcurrent] = useState(0);
  const [quotaDay, setQuotaDay] = useState(0);
  const [autoFailover, setAutoFailover] = useState(false);
  const [failoverEngines, setFailoverEngines] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState("");
  const [dirty, setDirty] = useState(false);

  // Sync on policy CONTENT, not object identity: background refetches
  // (reconnect heal, tab switches) mint fresh objects for identical content,
  // which must not wipe unsaved edits. A genuinely different policy (bot
  // switch, server-side change) still syncs and resets the form.
  const syncedRef = useRef("");
  useEffect(() => {
    if (!policy) return;
    const snapshot = JSON.stringify(policy);
    if (snapshot === syncedRef.current) return;
    syncedRef.current = snapshot;
    setApprovalMode(policy.approval_mode || "ask");
    setAllowedTools(policy.allowed_tools || []);
    setDeniedTools(policy.denied_tools || []);
    setQuotaHour(policy.max_turns_per_hour || 0);
    setQuotaConcurrent(policy.max_concurrent_runs || 0);
    setQuotaDay(policy.max_daily_runs || 0);
    setAutoFailover(Boolean(policy.auto_failover));
    setFailoverEngines(policy.failover_engines || []);
    setDirty(false);
  }, [policy]);

  const mark = () => setDirty(true);

  return (
    <>
      <section className="panel-section" aria-label="Approvals">
        <div className="panel-section-head">
          <div>
            <p className="section-label">Approvals</p>
            <p className="section-hint">How this bot asks before it touches anything.</p>
          </div>
          {dirty ? <Badge tone="warning">Unsaved</Badge> : savedAt ? <Badge tone="success">Saved</Badge> : null}
        </div>
        <SegmentedControl
          value={approvalMode}
          options={MODES}
          label="Approval mode"
          onChange={(value) => {
            setApprovalMode(value);
            mark();
          }}
        />
        <p className="field-hint">{MODES.find((mode) => mode.value === approvalMode)?.hint}</p>
      </section>

      <section className="panel-section" aria-label="Tool permissions">
        <div className="panel-section-head">
          <div>
            <p className="section-label">Tool permissions</p>
            <p className="section-hint">
              Allow runs quietly, Ask stops for you, Deny blocks the tool for this bot only.
            </p>
          </div>
        </div>
        <ToolPermissions
          allowed={allowedTools}
          denied={deniedTools}
          plugins={plugins}
          onChange={(next) => {
            setAllowedTools(next.allowed_tools);
            setDeniedTools(next.denied_tools);
            mark();
          }}
        />
      </section>

      <section className="panel-section" aria-label="Run limits">
        <div className="panel-section-head">
          <div>
            <p className="section-label">Run limits</p>
            <p className="section-hint">Circuit breakers for unattended and scheduled runs.</p>
          </div>
        </div>
        <div className="stepper-grid">
          <NumberStepper
            label="Turns per hour"
            value={quotaHour}
            min={0}
            max={500}
            onChange={(value) => {
              setQuotaHour(value);
              mark();
            }}
          />
          <NumberStepper
            label="Concurrent runs"
            value={quotaConcurrent}
            min={0}
            max={32}
            onChange={(value) => {
              setQuotaConcurrent(value);
              mark();
            }}
          />
          <NumberStepper
            label="Runs per day"
            value={quotaDay}
            min={0}
            max={500}
            onChange={(value) => {
              setQuotaDay(value);
              mark();
            }}
          />
        </div>
      </section>

      <section className="panel-section" aria-label="Failover">
        <div className="panel-section-head">
          <div>
            <p className="section-label">Failover</p>
            <p className="section-hint">Hand a failed run to another engine instead of stopping.</p>
          </div>
        </div>
        <ToggleSwitch
          label="Automatic engine failover"
          hint={autoFailover ? "Failed runs continue on the next engine" : "A failed run stops and reports"}
          checked={autoFailover}
          onChange={(checked) => {
            setAutoFailover(checked);
            mark();
          }}
        />
        {autoFailover && (
          <TagInput
            label="Fallback engines, in order"
            value={failoverEngines}
            suggestions={ENGINES.filter((engine) => !failoverEngines.includes(engine))}
            placeholder="opencode"
            hint="Runs retry on the first engine that accepts them."
            onChange={(next) => {
              setFailoverEngines(next);
              mark();
            }}
          />
        )}
      </section>

      <div className="panel-save-bar">
        <span className="field-hint">
          {dirty ? "Unsaved changes" : savedAt ? `Saved ${savedAt}` : "No changes yet"}
        </span>
        <button
          type="button"
          className="mini-primary"
          disabled={!policy || saving}
          onClick={async () => {
            setSaving(true);
            try {
              await actions.onSavePolicy({
                approval_mode: approvalMode,
                allowed_tools: allowedTools,
                denied_tools: deniedTools,
                max_turns_per_hour: quotaHour,
                max_concurrent_runs: quotaConcurrent,
                max_daily_runs: quotaDay,
                auto_failover: autoFailover,
                failover_engines: failoverEngines,
              });
              setDirty(false);
              setSavedAt(new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }));
            } finally {
              setSaving(false);
            }
          }}
        >
          {saving ? "Saving…" : "Save policy"}
        </button>
      </div>

      <section className="panel-section" aria-label="MCP connections">
        <div className="panel-section-head">
          <div>
            <p className="section-label">MCP connections</p>
            <p className="section-hint">External tool servers this bot may call.</p>
          </div>
          <button type="button" className="mini-primary" onClick={actions.onNewPlugin}>
            Add connection
          </button>
        </div>
        <div className="management-list">
          {bindings.length === 0 && <EmptyState>No MCP connections for this bot.</EmptyState>}
          {bindings.map((binding) => {
            const plugin = plugins.find((item) => item.id === binding.plugin_id);
            const wildcard = binding.allow_tools?.includes("*");
            return (
              <ManagementCard
                key={binding.plugin_id}
                title={plugin?.name || binding.plugin_id}
                meta={`${plugin?.transport || "MCP"} · ${
                  wildcard ? "All tools" : `${(binding.allow_tools || []).length} scoped tool(s)`
                }`}
                badge={binding.enabled === false ? "off" : "connected"}
                enabled={binding.enabled !== false}
                actions={
                  <>
                    <ActionLink
                      onClick={() =>
                        actions.onUpdatePlugin(binding.plugin_id, { allow_tools: wildcard ? [] : ["*"] })
                      }
                    >
                      {wildcard ? "Require approval" : "Allow all tools"}
                    </ActionLink>
                    <ActionLink onClick={() => actions.onDisconnectPlugin(binding.plugin_id)}>Disconnect</ActionLink>
                  </>
                }
              />
            );
          })}
        </div>
      </section>

      <section className="panel-section" aria-label="Audit">
        <p className="section-label">Recent decisions</p>
        <ol className="audit-list">
          {audit.length === 0 && <EmptyState>No decisions recorded.</EmptyState>}
          {audit.map((item, index) => (
            <li key={index} className="audit-row">
              <Badge tone={AUDIT_TONE[item.outcome] || "muted"} dot>
                {item.outcome}
              </Badge>
              <span className="audit-copy">
                <span className="audit-event">{item.event_type.replaceAll("_", " ")}</span>
                {item.canonical_tool_name ? <code className="audit-tool">{item.canonical_tool_name}</code> : null}
                {item.reason ? <span className="audit-reason">{item.reason}</span> : null}
              </span>
              <span className="audit-time">{shortTime(item.created_at)}</span>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
