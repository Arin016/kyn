import { useEffect, useState } from "react";
import type { AuditItem, BotPluginBinding, Plugin, Policy } from "../../types";
import { shortTime } from "../../lib/format";
import { ActionLink, ManagementCard } from "./ManagementCard";
import { EmptyState } from "../ui/Basics";

export interface SafetyActions {
  onSavePolicy: (policy: Policy) => Promise<void>;
  onNewPlugin: () => void;
  onDisconnectPlugin: (pluginId: string) => void;
}

interface Props {
  policy: Policy | null;
  plugins: Plugin[];
  bindings: BotPluginBinding[];
  audit: AuditItem[];
  actions: SafetyActions;
}

const MODES = [
  { value: "ask", label: "Ask me" },
  { value: "deny", label: "Deny all" },
  { value: "allow_list", label: "Allow listed tools" },
];

export function SafetyTab({ policy, plugins, bindings, audit, actions }: Props) {
  const [approvalMode, setApprovalMode] = useState("ask");
  const [allowedTools, setAllowedTools] = useState("");
  const [deniedTools, setDeniedTools] = useState("");
  const [quotaHour, setQuotaHour] = useState(0);
  const [quotaConcurrent, setQuotaConcurrent] = useState(0);
  const [quotaDay, setQuotaDay] = useState(0);

  useEffect(() => {
    if (!policy) return;
    setApprovalMode(policy.approval_mode || "ask");
    setAllowedTools((policy.allowed_tools || []).join(", "));
    setDeniedTools((policy.denied_tools || []).join(", "));
    setQuotaHour(policy.max_turns_per_hour || 0);
    setQuotaConcurrent(policy.max_concurrent_runs || 0);
    setQuotaDay(policy.max_daily_runs || 0);
  }, [policy]);

  const csvList = (value: string) =>
    value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);

  return (
    <>
      <form
        className="policy-form"
        onSubmit={(event) => {
          event.preventDefault();
          void actions.onSavePolicy({
            approval_mode: approvalMode,
            allowed_tools: csvList(allowedTools),
            denied_tools: csvList(deniedTools),
            max_turns_per_hour: Number(quotaHour || 0),
            max_concurrent_runs: Number(quotaConcurrent || 0),
            max_daily_runs: Number(quotaDay || 0),
          });
        }}
      >
        <p className="section-label">Tool approvals</p>
        <label>
          Default behavior
          <select value={approvalMode} onChange={(event) => setApprovalMode(event.target.value)}>
            {MODES.map((mode) => (
              <option key={mode.value} value={mode.value}>
                {mode.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Allowed tools
          <input
            value={allowedTools}
            onChange={(event) => setAllowedTools(event.target.value)}
            placeholder="filesystem.read, github.search"
          />
        </label>
        <label>
          Denied tools
          <input
            value={deniedTools}
            onChange={(event) => setDeniedTools(event.target.value)}
            placeholder="filesystem.delete"
          />
        </label>
        <p className="section-label spaced">Run limits · 0 means unlimited</p>
        <div className="quota-grid">
          <label>
            Per hour
            <input type="number" min={0} value={quotaHour} onChange={(event) => setQuotaHour(Number(event.target.value))} />
          </label>
          <label>
            Concurrent
            <input
              type="number"
              min={0}
              value={quotaConcurrent}
              onChange={(event) => setQuotaConcurrent(Number(event.target.value))}
            />
          </label>
          <label>
            Per day
            <input type="number" min={0} value={quotaDay} onChange={(event) => setQuotaDay(Number(event.target.value))} />
          </label>
        </div>
        <button className="mini-primary full" type="submit" style={{ minHeight: 34 }}>
          Save safety policy
        </button>
      </form>

      <section className="connections-section">
        <div className="panel-action-row">
          <p className="section-label">MCP connections</p>
          <button type="button" className="mini-primary" onClick={actions.onNewPlugin}>
            Add
          </button>
        </div>
        <div className="management-list">
          {bindings.length === 0 && <EmptyState>No MCP connections for this bot.</EmptyState>}
          {bindings.map((binding) => {
            const plugin = plugins.find((item) => item.id === binding.plugin_id);
            const tools =
              binding.allow_tools?.includes("*")
                ? "All tools"
                : `${(binding.allow_tools || []).length} allowed tool(s)`;
            return (
              <ManagementCard
                key={binding.plugin_id}
                title={plugin?.name || binding.plugin_id}
                meta={`${plugin?.transport || "MCP"} · ${tools}`}
                badge={binding.enabled === false ? "off" : "connected"}
                enabled={binding.enabled !== false}
                actions={<ActionLink onClick={() => actions.onDisconnectPlugin(binding.plugin_id)}>Disconnect</ActionLink>}
              />
            );
          })}
        </div>
      </section>

      <section className="connections-section">
        <p className="section-label">Recent audit</p>
        <div className="management-list">
          {audit.length === 0 && <EmptyState>No decisions recorded.</EmptyState>}
          {audit.map((item, index) => (
            <ManagementCard
              key={index}
              title={item.event_type.replaceAll("_", " ")}
              meta={`${item.outcome} · ${item.reason}${item.canonical_tool_name ? ` · ${item.canonical_tool_name}` : ""}`}
              badge={shortTime(item.created_at)}
              enabled
            />
          ))}
        </div>
      </section>
    </>
  );
}
