import { useEffect, useState } from "react";
import api, { type BotUsage } from "../../api";
import type { Bot, BotPluginBinding, Plugin, Policy, RunPhase } from "../../types";
import { BotAvatar } from "../BotAvatar";
import { ModelSwitcher } from "../ModelSwitcher";

const PHASE_LABEL: Record<RunPhase, string> = {
  idle: "Idle",
  starting: "Starting",
  running: "Working",
  waiting: "Approval needed",
  stopping: "Stopping",
  error: "Error",
};

const APPROVAL_LABEL: Record<string, string> = {
  ask: "Ask every time",
  auto: "Auto-approve",
  auto_approve: "Auto-approve",
  manual: "Ask every time",
  deny: "Deny by default",
  plan: "Plan first",
};

const numberFormat = new Intl.NumberFormat();

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
  return minutes > 0 ? `${minutes}m ${String(seconds).padStart(2, "0")}s` : `${seconds}s`;
}

function formatCost(cost: BotUsage["cost"] | undefined): string {
  if (!cost || !Number.isFinite(cost.amount)) return "—";
  const symbol = cost.currency === "EUR" ? "€" : cost.currency === "GBP" ? "£" : "$";
  return `${symbol}${cost.amount < 1 ? cost.amount.toFixed(4) : cost.amount.toFixed(2)}`;
}

function copyToClipboard(text: string): Promise<void> {
  return navigator.clipboard.writeText(text);
}

interface Props {
  bot: Bot;
  phase: RunPhase;
  detail: string;
  runStartedAt: number | null;
  queue: number;
  timelineCount: number;
  onSwitchModel: (model: string) => Promise<boolean>;
  switchingDisabled: boolean;
  policy: Policy | null;
  plugins: Plugin[];
  bindings: BotPluginBinding[];
  onHandoff: () => void;
  onStop: () => void;
  /** Re-read usage whenever the run completes. */
  usageRefreshKey: number;
}

export function BotTab({
  bot,
  phase,
  detail,
  runStartedAt,
  queue,
  timelineCount,
  onSwitchModel,
  switchingDisabled,
  policy,
  plugins,
  bindings,
  onHandoff,
  onStop,
  usageRefreshKey,
}: Props) {
  const [now, setNow] = useState(() => Date.now());
  const [copied, setCopied] = useState("");
  const [usage, setUsage] = useState<BotUsage | null>(null);
  const [usageError, setUsageError] = useState(false);
  const live = phase !== "idle" && phase !== "error" && phase !== "stopping";

  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);

  useEffect(() => {
    let cancelled = false;
    setUsageError(false);
    api
      .usage(bot.name)
      .then((data) => {
        if (!cancelled) setUsage(data);
      })
      .catch(() => {
        if (!cancelled) {
          setUsage(null);
          setUsageError(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [bot.name, usageRefreshKey]);

  const elapsed = runStartedAt ? formatElapsed(now - runStartedAt) : null;
  const engine = (bot.engine || "kiro").toLowerCase();

  const boundPlugins = bindings
    .filter((binding) => binding.enabled !== false)
    .map((binding) => {
      const match = plugins.find((plugin) => plugin.id === binding.plugin_id);
      return match?.name || binding.plugin_id;
    });

  const approval = policy?.approval_mode
    ? APPROVAL_LABEL[policy.approval_mode] || policy.approval_mode
    : "Engine default";

  const summary = [
    `bot: ${bot.name}`,
    `engine: ${engine}`,
    `model: ${bot.model || "default"}`,
    bot.agent ? `agent: ${bot.agent}` : null,
    bot.effort ? `effort: ${bot.effort}` : null,
    bot.cwd ? `cwd: ${bot.cwd}` : null,
    `phase: ${PHASE_LABEL[phase]}`,
    usage ? `sessions: ${usage.turns}` : null,
    usage ? `tokens: ${usage.tokens}` : null,
    usage ? `cost: ${formatCost(usage.cost)}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  const flash = (key: string) => {
    setCopied(key);
    window.setTimeout(() => setCopied(""), 1600);
  };

  const copy = async (key: string, text: string) => {
    try {
      await copyToClipboard(text);
      flash(key);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <>
      {/* Identity */}
      <article className="bot-card">
        <BotAvatar name={bot.name} size={58} className="bot-card__avatar" />
        <div className="bot-card__copy">
          <strong>{bot.name}</strong>
          <span className="bot-card__meta">
            <span className="engine-badge" data-engine={engine}>
              {engine}
            </span>
            <span className={`bot-card__phase${live ? " is-live" : ""}`}>{PHASE_LABEL[phase]}</span>
          </span>
          {bot.cwd ? (
            <span className="bot-card__path" title={bot.cwd}>
              {bot.cwd}
            </span>
          ) : null}
        </div>
      </article>

      {/* Run */}
      <section aria-label="Current run">
        <p className="section-label">Run</p>
        <div className={`run-card${live ? " is-live" : ""}`}>
          <div className="run-card-top">
            <span className={`pulse-dot${live ? " on" : ""}`} aria-hidden />
            <span>{PHASE_LABEL[phase]}</span>
            {elapsed && <span className="run-card__elapsed">{elapsed}</span>}
          </div>
          <p className="run-card-detail">{detail || "Nothing running right now."}</p>
          <dl className="session-grid">
            <div>
              <dt>Queued</dt>
              <dd>{queue === 0 ? "none" : `${queue} message${queue === 1 ? "" : "s"}`}</dd>
            </div>
            <div>
              <dt>Timeline</dt>
              <dd>{timelineCount === 0 ? "empty" : `${timelineCount} event${timelineCount === 1 ? "" : "s"}`}</dd>
            </div>
          </dl>
           {(phase === "starting" || phase === "running" || phase === "waiting") && (
            <div className="panel-action-row">
              <button type="button" className="mini-danger" onClick={onStop}>
                Stop run
              </button>
            </div>
          )}
        </div>
      </section>

      {/* Model */}
      <section aria-label="Model">
        <p className="section-label">Model</p>
        <ModelSwitcher
          bot={bot}
          onSwitch={onSwitchModel}
          disabled={switchingDisabled}
          variant="block"
        />
        <p className="field-hint">
          Switch mid-conversation. Ari applies it to the live session when the engine allows it,
          otherwise it takes effect on the next run.
        </p>
      </section>

      {/* Usage */}
      <section aria-label="Usage">
        <p className="section-label">Usage</p>
        <dl className="meter-grid">
          <div>
            <dt>Sessions</dt>
            <dd>{usage ? numberFormat.format(usage.turns) : usageError ? "—" : "…"}</dd>
          </div>
          <div>
            <dt>Tokens</dt>
            <dd>{usage ? numberFormat.format(usage.tokens) : usageError ? "—" : "…"}</dd>
          </div>
          <div>
            <dt>Spend</dt>
            <dd>{usage ? formatCost(usage.cost) : usageError ? "—" : "…"}</dd>
          </div>
        </dl>
        {usageError && <p className="field-hint">Usage is unavailable until the daemon responds.</p>}
      </section>

      {/* Autonomy */}
      <section aria-label="Autonomy">
        <p className="section-label">Autonomy</p>
        <dl className="session-grid session-grid--facts">
          <div>
            <dt>Approvals</dt>
            <dd>{approval}</dd>
          </div>
          <div>
            <dt>Per hour</dt>
            <dd>{policy?.max_turns_per_hour ? `${policy.max_turns_per_hour} turns` : "unlimited"}</dd>
          </div>
          <div>
            <dt>Concurrent</dt>
            <dd>{policy?.max_concurrent_runs ? `${policy.max_concurrent_runs} runs` : "unlimited"}</dd>
          </div>
          <div>
            <dt>Per day</dt>
            <dd>{policy?.max_daily_runs ? `${policy.max_daily_runs} runs` : "unlimited"}</dd>
          </div>
          <div>
            <dt>Tools blocked</dt>
            <dd>{policy?.denied_tools?.length ? `${policy.denied_tools.length} rules` : "none"}</dd>
          </div>
          <div>
            <dt>Tools allowed</dt>
            <dd>
              {policy?.allowed_tools?.length
                ? policy.allowed_tools.includes("*")
                  ? "all tools"
                  : `${policy.allowed_tools.length} rules`
                : "none listed"}
            </dd>
          </div>
        </dl>
      </section>

      {/* Extensions */}
      <section aria-label="Extensions">
        <p className="section-label">Extensions</p>
        {boundPlugins.length === 0 ? (
          <p className="activity-empty">No plugins bound to this bot yet.</p>
        ) : (
          <ul className="binding-list">
            {boundPlugins.map((plugin) => (
              <li key={plugin}>
                <span className="binding-dot" aria-hidden />
                {plugin}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Session */}
      <section aria-label="Session">
        <p className="section-label">Session</p>
        <dl className="session-grid session-grid--facts">
          <div>
            <dt>Agent</dt>
            <dd>{bot.agent || "engine default"}</dd>
          </div>
          <div>
            <dt>Effort</dt>
            <dd>{bot.effort || "engine default"}</dd>
          </div>
          <div>
            <dt>Engine</dt>
            <dd>{engine}</dd>
          </div>
          <div>
            <dt>Working dir</dt>
            <dd className="session-grid__mono" title={bot.cwd || ""}>
              {bot.cwd || "not set"}
            </dd>
          </div>
        </dl>
        <div className="panel-action-row panel-action-row--wrap">
          <button type="button" className="mini-primary" onClick={() => void copy("session", summary)}>
            {copied === "session" ? "Copied" : "Copy session"}
          </button>
          <button
            type="button"
            className="mini-ghost"
            disabled={!bot.cwd}
            onClick={() => void copy("cwd", bot.cwd || "")}
          >
            {copied === "cwd" ? "Copied" : "Copy folder"}
          </button>
          <button type="button" className="mini-ghost" onClick={onHandoff}>
            Handoff
          </button>
        </div>
      </section>
    </>
  );
}
