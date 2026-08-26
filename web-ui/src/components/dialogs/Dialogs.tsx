import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Modal } from "../ui/Modal";
import api from "../../api";
import { csv, parseEnvReferences } from "../../lib/format";
import type { Bot } from "../../types";
import { WorkflowStudio } from "./WorkflowStudio";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  bot: Bot | null;
  bots?: Bot[];
  onDone: () => void;
}

function formValues(form: HTMLFormElement): Record<string, string> {
  const data = new FormData(form);
  const result: Record<string, string> = {};
  for (const [key, value] of data.entries()) result[key] = String(value).trim();
  return result;
}

const KIRO_AGENTS: { id: string; label: string; hint: string }[] = [
  { id: "", label: "Kiro default", hint: "Built-in general-purpose agent" },
  { id: "kiro_default", label: "kiro_default", hint: "Explicit built-in default" },
  { id: "kiro_help", label: "kiro_help", hint: "Answers questions about Kiro CLI" },
  { id: "kiro_planner", label: "kiro_planner", hint: "Breaks down ideas into implementation plans" },
  { id: "kirocrew", label: "kirocrew", hint: "Autonomous personal AI agent" },
  { id: "kirocrew-heartbeat", label: "kirocrew-heartbeat", hint: "Unattended polling worker, read-only MCP" },
  { id: "cook", label: "cook", hint: "Architect mentor, design review, spec writer" },
  { id: "debrief", label: "debrief", hint: "Extracts lessons after debugging/shipping" },
];

const KIRO_MODELS: { id: string; label: string }[] = [
  { id: "", label: "Kiro default model" },
  { id: "claude-sonnet-4-5", label: "Claude Sonnet 4.5" },
  { id: "claude-opus-4-1", label: "Claude Opus 4.1" },
  { id: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
  { id: "claude-sonnet-4", label: "Claude Sonnet 4" },
  { id: "claude-opus-4", label: "Claude Opus 4" },
  { id: "claude-3-5-sonnet-latest", label: "Claude 3.5 Sonnet" },
  { id: "__custom", label: "Other model ID…" },
];

const KIRO_EFFORT: { id: string; label: string; hint: string }[] = [
  { id: "", label: "Default", hint: "Kiro chooses per turn" },
  { id: "low", label: "Low", hint: "Faster, cheaper, less thinking" },
  { id: "medium", label: "Medium", hint: "Balanced default" },
  { id: "high", label: "High", hint: "More thinking, slower" },
  { id: "xhigh", label: "X-High", hint: "Extended reasoning budget" },
  { id: "max", label: "Max", hint: "Longest reasoning available" },
];

export function CreateBotDialog({ open, onClose, onDone }: DialogProps) {
  const [error, setError] = useState("");
  const [agent, setAgent] = useState("");
  const [model, setModel] = useState("");
  const [customModel, setCustomModel] = useState("");
  const [effort, setEffort] = useState("");

  const modelValue = model === "__custom" ? customModel : model;
  const agentHint = KIRO_AGENTS.find((item) => item.id === agent)?.hint || "";
  const effortHint = KIRO_EFFORT.find((item) => item.id === effort)?.hint || "";

  return (
    <Modal eyebrow="New bot" title="Create a bot" open={open} onClose={onClose}>
      <form
        className="modal-form"
        onSubmit={async (event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          const form = event.currentTarget;
          setError("");
          const values = formValues(form);
          const payload: Record<string, string> = {
            name: values.name,
            cwd: values.cwd,
          };
          if (agent) payload.agent = agent;
          if (modelValue) payload.model = modelValue;
          if (effort) payload.effort = effort;
          try {
            await api.createBot(payload);
            form.reset();
            setAgent(""); setModel(""); setCustomModel(""); setEffort("");
            onClose();
            onDone();
          } catch (exc) {
            setError((exc as Error).message || "Could not create bot");
          }
        }}
      >
        <p className="dialog-copy">A bot keeps its Kiro session and conversation context between runs.</p>
        <label>
          Name <input name="name" autoComplete="off" required maxLength={60} placeholder="release-sherpa" />
        </label>
        <label>
          Working directory <input name="cwd" required placeholder="/Users/you/project" />
        </label>
        <details open>
          <summary>Kiro options</summary>
          <div className="advanced-fields">
            <label>
              Agent mode
              <select value={agent} onChange={(event) => setAgent(event.target.value)}>
                {KIRO_AGENTS.map((item) => (
                  <option key={item.id || "default"} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
              {agentHint && <span className="field-hint">{agentHint}</span>}
            </label>
            <label>
              Model
              <select value={model} onChange={(event) => setModel(event.target.value)}>
                {KIRO_MODELS.map((item) => (
                  <option key={item.id || "default"} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            {model === "__custom" && (
              <label>
                Custom model ID
                <input
                  value={customModel}
                  onChange={(event) => setCustomModel(event.target.value)}
                  placeholder="e.g. claude-3-5-haiku-latest"
                />
              </label>
            )}
            <label>
              Effort
              <select value={effort} onChange={(event) => setEffort(event.target.value)}>
                {KIRO_EFFORT.map((item) => (
                  <option key={item.id || "default"} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
              {effortHint && <span className="field-hint">{effortHint}</span>}
            </label>
          </div>
        </details>
        <p className="form-error" role="alert">
          {error}
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn btn-sm btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-sm btn-primary">
            Create bot
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function RoutineDialog({ open, onClose, bot, onDone }: DialogProps) {
  const [error, setError] = useState("");
  const [kind, setKind] = useState("interval");
  return (
    <Modal eyebrow="Work" title="Schedule a routine" open={open} onClose={onClose}>
      <form
        className="modal-form"
        onSubmit={async (event) => {
          event.preventDefault();
          const form = event.currentTarget;
          if (!bot) return;
          setError("");
          const values = formValues(form);
          const payload: Record<string, unknown> = {
            name: values.name,
            bot_name: bot.name,
            prompt: values.prompt,
            trigger_kind: kind,
          };
          if (kind === "interval") payload.interval_seconds = Number(values.interval_minutes || 0) * 60;
          else payload.run_at = values.run_at ? new Date(values.run_at).toISOString() : "";
          try {
            await api.createRoutine(payload);
            form.reset();
            setKind("interval");
            onClose();
            onDone();
          } catch (exc) {
            setError((exc as Error).message || "Could not create routine");
          }
        }}
      >
        <p className="dialog-copy">The selected bot will receive this prompt on the schedule you choose.</p>
        <label>
          Name <input name="name" required maxLength={100} placeholder="Repository pulse" />
        </label>
        <label>
          Prompt
          <textarea name="prompt" required rows={4} placeholder="Review open work and summarize blockers." />
        </label>
        <label>
          Schedule
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="interval">Repeat</option>
            <option value="once">Run once</option>
          </select>
        </label>
        {kind === "interval" ? (
          <label>
            Every minutes <input name="interval_minutes" type="number" min={1} defaultValue={60} />
          </label>
        ) : (
          <label>
            Run at <input name="run_at" type="datetime-local" />
          </label>
        )}
        <p className="form-error" role="alert">
          {error}
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn btn-sm btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-sm btn-primary">
            Create routine
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function PluginDialog({ open, onClose, bot, onDone }: DialogProps) {
  const [error, setError] = useState("");
  const [transport, setTransport] = useState("stdio");
  return (
    <Modal eyebrow="Safety" title="Add an MCP server" open={open} onClose={onClose}>
      <form
        className="modal-form"
        onSubmit={async (event) => {
          event.preventDefault();
          const form = event.currentTarget;
          if (!bot) return;
          setError("");
          const values = formValues(form);
          const payload: Record<string, unknown> = {
            id: values.id,
            name: values.name,
            transport,
            command: "",
            args: [],
            url: "",
            env: {},
          };
          if (transport === "stdio") {
            payload.command = values.command;
            payload.args = csv(values.args);
            try {
              payload.env = parseEnvReferences(values.env);
            } catch (exc) {
              setError((exc as Error).message);
              return;
            }
          } else {
            payload.url = values.url;
          }
          try {
            await api.createPlugin(payload);
            await api.bindPlugin(bot.name, payload.id as string);
            form.reset();
            setTransport("stdio");
            onClose();
            onDone();
          } catch (exc) {
            setError((exc as Error).message || "Could not add connection");
          }
        }}
      >
        <p className="dialog-copy">
          Connect a capability to this bot. Secret fields accept environment references only, such as
          API_TOKEN=env:MY_TOKEN.
        </p>
        <label>
          Connection ID <input name="id" required maxLength={64} placeholder="github" />
        </label>
        <label>
          Display name <input name="name" required maxLength={100} placeholder="GitHub" />
        </label>
        <label>
          Transport
          <select value={transport} onChange={(event) => setTransport(event.target.value)}>
            <option value="stdio">Local command</option>
            <option value="http">Secure URL</option>
          </select>
        </label>
        {transport === "stdio" ? (
          <>
            <label>
              Command <input name="command" placeholder="npx" />
            </label>
            <label>
              Arguments <input name="args" placeholder="-y, @example/mcp" />
            </label>
            <label>
              Environment references
              <textarea name="env" rows={3} placeholder="API_TOKEN=env:MY_API_TOKEN" />
            </label>
          </>
        ) : (
          <label>
            HTTPS URL <input name="url" placeholder="https://mcp.example.com/mcp" />
          </label>
        )}
        <p className="form-error" role="alert">
          {error}
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn btn-sm btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-sm btn-primary">
            Add connection
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function ChannelDialog({ open, onClose, bot, onDone }: DialogProps) {
  const [error, setError] = useState("");
  return (
    <Modal eyebrow="Work" title="Connect another place" open={open} onClose={onClose}>
      <form
        className="modal-form"
        onSubmit={async (event) => {
          event.preventDefault();
          const form = event.currentTarget;
          if (!bot) return;
          setError("");
          const values = formValues(form);
          try {
            await api.createChannel({
              id: values.id,
              name: values.name,
              kind: values.kind,
              bot_name: bot.name,
              signing_secret_env: values.signing_secret_env,
              verify_token_env: values.verify_token_env,
              outbound_token_env: values.outbound_token_env,
              trigger_prefix: values.trigger_prefix,
              allowed_sources: csv(values.allowed_sources),
              allowed_senders: csv(values.allowed_senders),
            });
            form.reset();
            onClose();
            onDone();
          } catch (exc) {
            setError((exc as Error).message || "Could not create channel");
          }
        }}
      >
        <p className="dialog-copy">
          Signed events become durable bot requests with their source thread context. Secrets stay in environment
          variables. Telegram polls from this laptop, so it needs no public URL.
        </p>
        <label>
          Connection name <input name="name" required maxLength={100} placeholder="Phone Telegram" />
        </label>
        <label>
          Connection ID <input name="id" required maxLength={80} placeholder="iphone-telegram" />
        </label>
        <label>
          Source
          <select name="kind" defaultValue="telegram">
            <option value="telegram">Telegram</option>
            <option value="slack">Slack</option>
            <option value="github">GitHub</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="email">Email gateway</option>
            <option value="webhook">Signed webhook</option>
          </select>
        </label>
        <label>
          Signing-secret environment variable{" "}
          <input name="signing_secret_env" required placeholder="KIRO_TELEGRAM_BOT_TOKEN" />
        </label>
        <label>
          Verification-token environment variable{" "}
          <input name="verify_token_env" placeholder="Required for WhatsApp · KIRO_WHATSAPP_VERIFY_TOKEN" />
        </label>
        <label>
          Reply-token environment variable{" "}
          <input name="outbound_token_env" placeholder="Leave empty for Telegram · uses the bot token" />
        </label>
        <label>
          Invocation phrase <input name="trigger_prefix" placeholder="Empty for Telegram DMs · @kiro for groups" />
        </label>
        <label>
          Allowed senders <input name="allowed_senders" placeholder="Your Telegram user id from @userinfobot" />
        </label>
        <details>
          <summary>Limit sources further</summary>
          <div className="advanced-fields">
            <label>
              Allowed sources{" "}
              <input name="allowed_sources" placeholder="Channel IDs, repositories, or recipients" />
            </label>
          </div>
        </details>
        <p className="form-error" role="alert">
          {error}
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn btn-sm btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-sm btn-primary">
            Create channel
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function DelegationDialog({ open, onClose, onDone, bots = [] }: DialogProps) {
  return <WorkflowStudio open={open} onClose={onClose} onDone={onDone} bots={bots} />;
}

export function CodingDialog({ open, onClose, bot, onDone }: DialogProps) {
  const [error, setError] = useState("");
  const [repoPath, setRepoPath] = useState("");

  useEffect(() => {
    if (open && bot?.cwd) setRepoPath(bot.cwd);
  }, [open, bot]);

  return (
    <Modal eyebrow="Work" title="Build a verified patch" open={open} onClose={onClose}>
      <form
        className="modal-form"
        onSubmit={async (event) => {
          event.preventDefault();
          const form = event.currentTarget;
          if (!bot) return;
          setError("");
          const values = formValues(form);
          try {
            const checks = String(values.checks || "")
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean)
              .map((line, index) => {
                const split = line.indexOf(":");
                if (split < 1) throw new Error(`Check line ${index + 1} must use name: executable, argument.`);
                const argv = csv(line.slice(split + 1));
                if (!argv.length) throw new Error(`Check line ${index + 1} has no executable.`);
                return { name: line.slice(0, split).trim(), argv };
              });
            if (!checks.length) throw new Error("Add at least one deterministic check.");
            await api.createCodingExecution({
              idempotency_key: `browser-${crypto.randomUUID()}`,
              repo_path: values.repo_path,
              task: values.task,
              builder_bot: bot.name,
              reviewer_bot: values.reviewer_bot,
              checks,
              max_repairs: Number(values.max_repairs || 0),
            });
            form.reset();
            setRepoPath("");
            onClose();
            onDone();
          } catch (exc) {
            setError((exc as Error).message || "Could not start coding execution");
          }
        }}
      >
        <p className="dialog-copy">The selected bot builds. Choose a different bot for independent review. Nothing is pushed or merged.</p>
        <label>
          Repository <input name="repo_path" required value={repoPath} onChange={(event) => setRepoPath(event.target.value)} placeholder="/Users/you/project" />
        </label>
        <label>
          Reviewer bot <input name="reviewer_bot" required placeholder="reviewer" />
        </label>
        <label>
          Task
          <textarea name="task" required rows={5} placeholder="Fix the issue, add tests, and explain the risk." />
        </label>
        <label>
          Checks
          <textarea name="checks" required rows={3} placeholder={"tests: pytest, -q\nlint: ruff, check, ."} />
        </label>
        <p className="dialog-copy">
          One check per line: <strong>name: executable, argument</strong>. Commands run directly without a shell.
        </p>
        <label>
          Maximum repairs <input name="max_repairs" type="number" min={0} max={3} defaultValue={1} />
        </label>
        <p className="form-error" role="alert">
          {error}
        </p>
        <div className="dialog-actions">
          <button type="button" className="btn btn-sm btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-sm btn-primary">
            Start coding
          </button>
        </div>
      </form>
    </Modal>
  );
}

export type { DialogProps };
