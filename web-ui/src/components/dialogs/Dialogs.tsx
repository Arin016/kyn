import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Modal } from "../ui/Modal";
import { BotAvatar } from "../BotAvatar";
import api from "../../api";
import type { Bot } from "../../types";
import {
  FieldGroup,
  KeyValueRows,
  NumberStepper,
  SegmentedControl,
  TagInput,
  TilePicker,
} from "../ui/Pickers";
import type { KeyValueRow } from "../ui/Pickers";

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

export const KIRO_MODELS: { id: string; label: string }[] = [
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

const ENGINES: { id: string; label: string; hint: string }[] = [
  { id: "kiro", label: "Kiro", hint: "Native Kiro ACP session with resume" },
  { id: "opencode", label: "OpenCode", hint: "Native opencode acp session" },
  { id: "codex", label: "Codex", hint: "Codex ACP bridge; requires codex-acp" },
];

function DirectoryBrowser({ initial, onPick }: { initial: string; onPick: (path: string) => void }) {
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<{ name: string; path: string; has_git: boolean }[]>([]);
  const [error, setError] = useState("");

  const load = async (next: string) => {
    setError("");
    try {
      const listing = await api.directories(next);
      setPath(listing.path);
      setEntries(listing.entries);
    } catch (exc) {
      setError((exc as Error).message || "Could not list directory");
    }
  };

  useEffect(() => {
    void load(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="dir-browser">
      <div className="dir-browser__path" title={path}>{path || "…"}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="dir-browser__list">
        {entries.length === 0 && <p className="activity-empty">No subdirectories.</p>}
        {entries.map((entry) => (
          <button key={entry.path} type="button" className="dir-browser__row" onClick={() => void load(entry.path)}>
            <span className="dir-browser__name">{entry.name}</span>
            {entry.has_git && <span className="dir-browser__git">git</span>}
          </button>
        ))}
      </div>
      <div className="dialog-actions">
        <button type="button" className="btn btn-sm btn-primary" disabled={!path} onClick={() => onPick(path)}>
          Use this folder
        </button>
      </div>
    </div>
  );
}

export function CreateBotDialog({ open, onClose, onDone }: DialogProps) {
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [engine, setEngine] = useState<string>("kiro");
  const [cwd, setCwd] = useState("");
  const [browseOpen, setBrowseOpen] = useState(false);
  const [agent, setAgent] = useState("");
  const [model, setModel] = useState("");
  const [customModel, setCustomModel] = useState("");
  const [modelText, setModelText] = useState("");
  const [ocModels, setOcModels] = useState<{ id: string; label: string }[]>([]);
  const [ocLoading, setOcLoading] = useState(false);
  const [ocError, setOcError] = useState("");
  const [effort, setEffort] = useState("");

  const modelValue = engine === "kiro" ? (model === "__custom" ? customModel : model) : modelText;

  useEffect(() => {
    if (!open || engine !== "opencode" || ocModels.length > 0) return;
    setOcLoading(true);
    setOcError("");
    api
      .engines("opencode")
      .then((data) => setOcModels(data.models || []))
      .catch((exc: Error) => setOcError(exc.message || "Could not load OpenCode models"))
      .finally(() => setOcLoading(false));
  }, [open, engine, ocModels.length]);
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
            cwd,
            engine,
          };
          if (agent) payload.agent = agent;
          if (modelValue) payload.model = modelValue;
          if (effort) payload.effort = effort;
          try {
            await api.createBot(payload);
            form.reset();
            setName("");
            setEngine("kiro"); setCwd(""); setBrowseOpen(false);
            setAgent(""); setModel(""); setCustomModel(""); setModelText(""); setEffort("");
            onClose();
            onDone();
          } catch (exc) {
            setError((exc as Error).message || "Could not create bot");
          }
        }}
      >
        <p className="dialog-copy">A bot keeps its native engine session and conversation context between runs.</p>
        <label>
          Name
          <span className="bot-identity">
            <BotAvatar name={name || "kyn"} size={44} className="bot-identity__avatar" />
            <input
              name="name"
              autoComplete="off"
              required
              maxLength={60}
              placeholder="release-sherpa"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </span>
          <span className="field-hint">
            This mark is generated from the name — every bot gets its own face.
          </span>
        </label>
        <label>
          Working directory
          <div className="dir-input-row">
            <input
              name="cwd"
              required
              value={cwd}
              onChange={(event) => setCwd(event.target.value)}
              placeholder="/Users/you/project"
            />
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => setBrowseOpen((open) => !open)}>
              {browseOpen ? "Hide" : "Browse…"}
            </button>
          </div>
        </label>
        {browseOpen && (
          <DirectoryBrowser
            initial={cwd}
            onPick={(path) => {
              setCwd(path);
              setBrowseOpen(false);
            }}
          />
        )}
        <label>
          Engine
          <select value={engine} onChange={(event) => setEngine(event.target.value)}>
            {ENGINES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
          <span className="field-hint">{ENGINES.find((item) => item.id === engine)?.hint || ""}</span>
        </label>
        {engine === "opencode" && (
          <label>
            Model
            <select
              value={modelText}
              onChange={(event) => setModelText(event.target.value)}
              disabled={ocLoading || ocModels.length === 0}
            >
              <option value="">{ocLoading ? "Loading models…" : "OpenCode default model"}</option>
              {ocModels.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            {ocError && <span className="field-hint">{ocError}</span>}
          </label>
        )}
        {engine === "codex" && (
          <label>
            Model
            <input
              value={modelText}
              onChange={(event) => setModelText(event.target.value)}
              placeholder="e.g. gpt-5.6 (empty uses the Codex default)"
            />
          </label>
        )}
        {engine === "kiro" && (
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
            {engine === "kiro" && (
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
            )}
            {engine === "kiro" && model === "__custom" && (
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
        )}
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
  const [intervalMinutes, setIntervalMinutes] = useState(60);
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
        <FieldGroup label="Schedule">
          <SegmentedControl
            value={kind}
            options={[
              { value: "interval", label: "Repeat", hint: "Run again on a fixed cadence" },
              { value: "once", label: "Run once", hint: "Fire at a single moment" },
            ]}
            onChange={setKind}
            label="Schedule kind"
          />
        </FieldGroup>
        {kind === "interval" ? (
          <FieldGroup label="Cadence" hint="Custom values are allowed — the bot never runs more often than once a minute.">
            <input type="hidden" name="interval_minutes" value={intervalMinutes} readOnly />
            <SegmentedControl
              value={String(intervalMinutes)}
              options={[
                { value: "5", label: "5 min" },
                { value: "15", label: "15 min" },
                { value: "60", label: "Hourly" },
                { value: "360", label: "6 h" },
                { value: "1440", label: "Daily" },
              ]}
              onChange={(value) => setIntervalMinutes(Number(value))}
              label="Cadence presets"
              size="sm"
            />
            <NumberStepper
              label="Every minutes"
              value={intervalMinutes}
              min={1}
              max={10_080}
              onChange={setIntervalMinutes}
              hint={`Runs ≈ ${Math.max(1, Math.round((24 * 60) / Math.max(1, intervalMinutes)))} times a day`}
            />
          </FieldGroup>
        ) : (
          <label>
            Run at <input name="run_at" type="datetime-local" required />
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
  const [args, setArgs] = useState<string[]>([]);
  const [envRows, setEnvRows] = useState<KeyValueRow[]>([]);
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
            payload.args = args;
            const env: Record<string, string> = {};
            for (const row of envRows) {
              const key = row.key.trim();
              if (!key) continue;
              if (!row.value.trim()) {
                setError(`${key} needs a value such as env:MY_TOKEN.`);
                return;
              }
              env[key] = row.value.trim();
            }
            payload.env = env;
          } else {
            payload.url = values.url;
          }
          try {
            await api.createPlugin(payload);
            await api.bindPlugin(bot.name, payload.id as string);
            form.reset();
            setTransport("stdio");
            setArgs([]);
            setEnvRows([]);
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
        <FieldGroup label="Transport">
          <TilePicker
            value={transport}
            options={[
              { value: "stdio", label: "Local command", hint: "Runs an MCP server binary on this machine" },
              { value: "http", label: "Secure URL", hint: "Streams to a hosted MCP endpoint over HTTPS" },
            ]}
            onChange={setTransport}
            label="Transport"
            columns={2}
          />
        </FieldGroup>
        {transport === "stdio" ? (
          <>
            <label>
              Command <input name="command" placeholder="npx" />
            </label>
            <TagInput
              label="Arguments"
              value={args}
              onChange={setArgs}
              mono
              placeholder="-y"
              hint="Enter after each argument. Values are passed straight through, never through a shell."
            />
            <KeyValueRows
              label="Environment"
              value={envRows}
              onChange={setEnvRows}
              keyPlaceholder="API_TOKEN"
              valuePlaceholder="env:MY_API_TOKEN"
              addLabel="Add variable"
              hint="Only environment references are accepted — secrets never land in the database."
            />
          </>
        ) : (
          <label>
            HTTPS URL <input name="url" required placeholder="https://mcp.example.com/mcp" />
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
  const [channelKind, setChannelKind] = useState("telegram");
  const [allowedSenders, setAllowedSenders] = useState<string[]>([]);
  const [allowedSources, setAllowedSources] = useState<string[]>([]);
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
              kind: channelKind,
              bot_name: bot.name,
              signing_secret_env: values.signing_secret_env,
              verify_token_env: values.verify_token_env,
              outbound_token_env: values.outbound_token_env,
              trigger_prefix: values.trigger_prefix,
              allowed_sources: allowedSources,
              allowed_senders: allowedSenders,
            });
            form.reset();
            setChannelKind("telegram");
            setAllowedSenders([]);
            setAllowedSources([]);
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
        <input type="hidden" name="kind" value={channelKind} readOnly />
        <FieldGroup label="Source">
          <TilePicker
            value={channelKind}
            options={[
              { value: "telegram", label: "Telegram", hint: "Polls from this machine" },
              { value: "slack", label: "Slack", hint: "Signed events" },
              { value: "github", label: "GitHub", hint: "Issues and PRs" },
              { value: "whatsapp", label: "WhatsApp", hint: "Cloud API" },
              { value: "email", label: "Email", hint: "Gateway webhook" },
              { value: "webhook", label: "Webhook", hint: "Anything signed" },
            ]}
            onChange={setChannelKind}
            label="Channel source"
            columns={3}
          />
        </FieldGroup>
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
        <TagInput
          label="Allowed senders"
          value={allowedSenders}
          onChange={setAllowedSenders}
          placeholder="8961333191"
          hint="Enter after each id, handle or email. Leave empty to accept any authenticated sender."
        />
        <details>
          <summary>Limit sources further</summary>
          <div className="advanced-fields">
            <TagInput
              label="Allowed sources"
              value={allowedSources}
              onChange={setAllowedSources}
              placeholder="C0123ABCD · owner/repo"
              hint="Channel ids, repositories or recipients this bot will answer."
            />
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


interface CheckRow {
  name: string;
  argv: string[];
  timeout: number;
}

export function CodingDialog({ open, onClose, bot, bots = [], onDone }: DialogProps) {
  const [error, setError] = useState("");
  const [repoPath, setRepoPath] = useState("");
  const [reviewerBot, setReviewerBot] = useState("");
  const [task, setTask] = useState("");
  const [checks, setChecks] = useState<CheckRow[]>([{ name: "tests", argv: ["pytest", "-q"], timeout: 600 }]);
  const [maxRepairs, setMaxRepairs] = useState(1);

  useEffect(() => {
    if (open && bot?.cwd) setRepoPath(bot.cwd);
  }, [open, bot]);

  useEffect(() => {
    if (!open) return;
    const options = bots.filter((item) => item.name !== bot?.name);
    setReviewerBot((current) => current || options[0]?.name || "");
  }, [open, bots, bot?.name]);

  const reviewers = bots.filter((item) => item.name !== bot?.name);
  const updateCheck = (index: number, patch: Partial<CheckRow>) =>
    setChecks((current) => current.map((row, position) => (position === index ? { ...row, ...patch } : row)));

  return (
    <Modal eyebrow="Work" title="Build a verified patch" open={open} onClose={onClose}>
      <form
        className="modal-form"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!bot) return;
          setError("");
          try {
            if (!reviewerBot) throw new Error("Choose a reviewer bot — it must be a different bot.");
            const payload = checks.map((row, index) => {
              if (!row.name.trim()) throw new Error(`Check ${index + 1} needs a name.`);
              if (row.argv.length === 0) throw new Error(`Check ${index + 1} needs an executable.`);
              return { name: row.name.trim(), argv: row.argv, timeout_seconds: row.timeout };
            });
            if (payload.length === 0) throw new Error("Add at least one deterministic check.");
            await api.createCodingExecution({
              idempotency_key: `browser-${crypto.randomUUID()}`,
              repo_path: repoPath,
              task,
              builder_bot: bot.name,
              reviewer_bot: reviewerBot,
              checks: payload,
              max_repairs: maxRepairs,
            });
            setTask("");
            setRepoPath("");
            setChecks([{ name: "tests", argv: ["pytest", "-q"], timeout: 600 }]);
            setMaxRepairs(1);
            onClose();
            onDone();
          } catch (exc) {
            setError((exc as Error).message || "Could not start coding execution");
          }
        }}
      >
        <p className="dialog-copy">The selected bot builds. Choose a different bot for independent review. Nothing is pushed or merged.</p>
        <label>
          Repository
          <input
            name="repo_path"
            required
            value={repoPath}
            onChange={(event) => setRepoPath(event.target.value)}
            placeholder="/Users/you/project"
          />
          <span className="field-hint">A worktree is created from here; your working copy is left alone.</span>
        </label>
        <FieldGroup label="Reviewer bot" hint="Independent review must come from a different bot.">
          {reviewers.length === 0 ? (
            <p className="activity-empty">Create a second bot to review the work.</p>
          ) : (
            <TilePicker
              value={reviewerBot}
              options={reviewers.map((item) => ({
                value: item.name,
                label: item.name,
                hint: item.engine || "kiro",
              }))}
              onChange={setReviewerBot}
              label="Reviewer bot"
              columns={2}
            />
          )}
        </FieldGroup>
        <label>
          Task
          <textarea
            name="task"
            required
            rows={5}
            value={task}
            onChange={(event) => setTask(event.target.value)}
            placeholder="Fix the issue, add tests, and explain the risk."
          />
        </label>
        <FieldGroup label="Checks" hint="Commands run directly, without a shell. Enter after each argument.">
          {checks.map((row, index) => (
            <div className="check-row" key={index}>
              <div className="check-row-head">
                <input
                  className="check-name"
                  value={row.name}
                  placeholder="tests"
                  aria-label={`Check ${index + 1} name`}
                  onChange={(event) => updateCheck(index, { name: event.target.value })}
                />
                <NumberStepper
                  label="Timeout s"
                  value={row.timeout}
                  min={5}
                  max={3600}
                  step={30}
                  onChange={(value) => updateCheck(index, { timeout: value })}
                  hint="Seconds before the check is killed"
                />
                <button
                  type="button"
                  className="kv-remove"
                  aria-label={`Remove check ${index + 1}`}
                  onClick={() => setChecks((current) => current.filter((_, position) => position !== index))}
                >
                  ×
                </button>
              </div>
              <TagInput
                label="Command"
                value={row.argv}
                onChange={(argv) => updateCheck(index, { argv })}
                mono
                placeholder={row.name === "tests" ? "pytest" : "npm"}
              />
            </div>
          ))}
          <button
            type="button"
            className="kv-add"
            onClick={() => setChecks((current) => [...current, { name: "", argv: [], timeout: 600 }])}
          >
            Add check
          </button>
        </FieldGroup>
        <NumberStepper
          label="Maximum repairs"
          value={maxRepairs}
          min={0}
          max={3}
          onChange={setMaxRepairs}
          hint="How many times the builder may fix a failing check"
        />
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

export function HandoffDialog({ open, onClose, bot }: DialogProps) {
  const [target, setTarget] = useState("opencode");
  const [prompt, setPrompt] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [tokens, setTokens] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && bot) {
      const fallback = ["kiro", "opencode", "codex"].find((engine) => engine !== (bot.engine || "kiro")) || "opencode";
      setTarget(fallback);
      setPrompt("");
      setWarnings([]);
      setTokens(0);
      setError("");
    }
  }, [open, bot]);

  const compile = async () => {
    if (!bot) return;
    setLoading(true);
    setError("");
    try {
      const bundle = await api.handoff(bot.name, target);
      setPrompt(String(bundle.prompt || ""));
      setWarnings(Array.isArray(bundle.warnings) ? bundle.warnings.map(String) : []);
      setTokens(Number(bundle.total_estimated_tokens || 0));
    } catch (exc) {
      setError((exc as Error).message || "Could not compile handoff");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal eyebrow="Portable context" title="Hand off this thread" open={open} onClose={onClose} wide>
      <p className="dialog-copy">
        Compile the bot&apos;s durable turns and current workspace into a bounded bundle for another engine.
        The next worker must still verify assumptions against the repository.
      </p>
      <FieldGroup label="Next engine">
        <TilePicker
          value={target}
          options={[
            { value: "kiro", label: "Kiro", hint: "Native ACP session" },
            { value: "opencode", label: "OpenCode", hint: "Separate agent runtime" },
            { value: "codex", label: "Codex", hint: "Needs codex-acp installed" },
          ]}
          onChange={setTarget}
          label="Next engine"
        />
      </FieldGroup>
      {warnings.length > 0 && (
        <p className="dialog-copy">{warnings.join(" ")}</p>
      )}
      {prompt && (
        <pre className="handoff-preview">{prompt}</pre>
      )}
      <p className="form-error" role="alert">
        {error}
      </p>
      <div className="dialog-actions">
        <span className="field-hint">{tokens > 0 ? `~${tokens} tokens` : ""}</span>
        <button type="button" className="btn btn-sm btn-secondary" onClick={onClose}>
          Close
        </button>
        <button type="button" className="btn btn-sm btn-primary" disabled={loading || !bot} onClick={() => void compile()}>
          {loading ? "Compiling…" : "Compile handoff"}
        </button>
      </div>
    </Modal>
  );
}

interface CreateGroupDialogProps extends DialogProps {
  onCreated?: (groupId: string) => void;
}

export function CreateGroupDialog({ open, onClose, bots = [], onDone, onCreated }: CreateGroupDialogProps) {
  const [name, setName] = useState("");
  const [aim, setAim] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [rounds, setRounds] = useState(2);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError("");
    setMembers((current) =>
      current.length > 0 ? current : bots.slice(0, Math.min(3, bots.length)).map((bot) => bot.name),
    );
  }, [open, bots]);

  const toggle = (botName: string) => {
    setMembers((current) =>
      current.includes(botName)
        ? current.filter((item) => item !== botName)
        : [...current, botName],
    );
  };

  return (
    <Modal eyebrow="New group" title="Start a group chat" open={open} onClose={onClose}>
      <form
        className="modal-form"
        onSubmit={async (event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          setError("");
          if (members.length === 0) {
            setError("Pick at least one bot for the group.");
            return;
          }
          setBusy(true);
          try {
            const created = await api.createGroup({
              name: name.trim(),
              aim: aim.trim(),
              members,
              max_rounds: rounds,
              start: true,
            });
            onClose();
            onDone();
            onCreated?.(created.group.id);
            setName("");
            setAim("");
            setRounds(2);
            setMembers([]);
          } catch (exc) {
            setError((exc as Error).message || "Could not create this group");
          } finally {
            setBusy(false);
          }
        }}
      >
        <p className="dialog-copy">
          Bots in a group take turns working one shared aim and read each other's replies before they
          speak. You can jump into the thread at any time.
        </p>
        <label>
          Group name
          <input
            name="name"
            autoComplete="off"
            required
            maxLength={80}
            placeholder="Launch room"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          Shared aim
          <textarea
            name="aim"
            rows={3}
            required
            maxLength={400}
            placeholder="Ship the release notes with one verified changelog entry per merged pull request."
            value={aim}
            onChange={(event) => setAim(event.target.value)}
          />
          <span className="field-hint">Every bot is prompted with this aim on each turn.</span>
        </label>
        <div className="group-picker">
          <span className="field-label">Members</span>
          {bots.length === 0 && <p className="activity-empty">Create a bot first, then group them.</p>}
          <div className="group-picker__grid">
            {bots.map((bot) => {
              const picked = members.includes(bot.name);
              return (
                <button
                  key={bot.name}
                  type="button"
                  className={`group-pick${picked ? " is-picked" : ""}`}
                  aria-pressed={picked}
                  onClick={() => toggle(bot.name)}
                >
                  <BotAvatar name={bot.name} size={30} />
                  <span className="group-pick__copy">
                    <strong>{bot.name}</strong>
                    <small>{bot.engine || "kiro"}</small>
                  </span>
                  <span className="group-pick__mark" aria-hidden>
                    {picked ? "✓" : "+"}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
        <label>
          Rounds
          <input
            name="max_rounds"
            type="number"
            min={1}
            max={10}
            value={rounds}
            onChange={(event) => setRounds(Math.min(10, Math.max(1, Number(event.target.value) || 1)))}
          />
          <span className="field-hint">
            One round lets every member speak once. The group also stops early when a bot replies with
            [GROUP DONE].
          </span>
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn btn-sm btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={busy || members.length === 0}>
            {busy ? "Starting…" : "Create and start"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export type { DialogProps };
