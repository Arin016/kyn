/**
 * Slash commands — the composer's command palette.
 *
 * Typing "/" in the composer opens a menu of commands; a command either runs
 * immediately or opens a second level of choices (e.g. `/model` lists the
 * engine's models). The Composer owns only the UI: detection, filtering,
 * keyboard navigation. The callers own the actions, so nothing here touches
 * the API or app state.
 *
 * Group chats additionally get @-mention autocomplete (`members` prop on the
 * Composer) and the backend routes a mentioned bot's turn directly — see
 * `kyn/groups.py`.
 */

export interface SlashChoice {
  id: string;
  label: string;
  detail?: string;
  /** Rendered but not selectable (e.g. a state note). */
  disabled?: boolean;
}

export interface SlashCommand {
  /** Command word, without the slash: `model` → `/model`. */
  id: string;
  /** What the command does, shown next to the command word. */
  name: string;
  /** One line of extra context: the current value, or what happens on run. */
  hint: string;
  keywords?: string[];
  /** Present → selecting the command opens these choices instead of running. */
  choices?: SlashChoice[] | (() => Promise<SlashChoice[]> | SlashChoice[]);
  run: (choice?: SlashChoice) => void;
}

export type DialogName = "bot" | "group" | "routine" | "plugin" | "channel" | "coding" | "handoff";

export interface BotCommandContext {
  engine: string;
  currentModel?: string;
  marketing: boolean;
  busy: boolean;
  modelChoices: () => Promise<SlashChoice[]>;
  onModel: (id: string) => void;
  onStop: () => void;
  onDialog: (name: DialogName) => void;
  onWorkflows: () => void;
  onInspect: () => void;
  onTheme: (theme: "light" | "dark") => void;
}

/** Commands for a one-to-one bot conversation. */
export function buildBotCommands(ctx: BotCommandContext): SlashCommand[] {
  const engine = ctx.engine.toLowerCase();
  return [
    {
      id: "model",
      name: "Switch model",
      hint: ctx.currentModel ? `Now ${ctx.currentModel} — applies to the live session` : "Applies to the live session",
      keywords: ["engine", "llm"],
      choices: ctx.modelChoices,
      run: (choice) => {
        if (!choice) return;
        ctx.onModel(choice.id);
      },
    },
    {
      id: "theme",
      name: "Switch theme",
      hint: "Paper light or black dark",
      keywords: ["dark", "light", "appearance", "mode"],
      choices: [
        { id: "light", label: "Paper", detail: "Light theme" },
        { id: "dark", label: "Black", detail: "Dark theme" },
      ],
      run: (choice) => {
        if (choice?.id === "light" || choice?.id === "dark") ctx.onTheme(choice.id);
      },
    },
    {
      id: "stop",
      name: "Stop the current run",
      hint: ctx.busy ? "Cancels what the bot is doing now" : "Nothing is running right now",
      keywords: ["cancel", "abort"],
      run: () => ctx.onStop(),
    },
    {
      id: "handoff",
      name: "Hand off to another bot",
      hint: ctx.marketing ? "Needs a local daemon" : "Pass the thread to a specialist",
      keywords: ["transfer", "delegate"],
      run: () => ctx.onDialog("handoff"),
    },
    {
      id: "new-bot",
      name: "Create a bot",
      hint: "A named agent with its own policy",
      keywords: ["agent", "add", "create"],
      run: () => ctx.onDialog("bot"),
    },
    {
      id: "group",
      name: "Create a group chat",
      hint: "Several bots on one shared aim",
      keywords: ["team", "multi", "squad"],
      run: () => ctx.onDialog("group"),
    },
    {
      id: "routine",
      name: "Schedule recurring work",
      hint: "Runs on a cadence, survives restarts",
      keywords: ["cron", "schedule", "timer"],
      run: () => ctx.onDialog("routine"),
    },
    {
      id: "plugin",
      name: "Add an MCP connection",
      hint: "Give this bot more tools",
      keywords: ["mcp", "tool", "server"],
      run: () => ctx.onDialog("plugin"),
    },
    {
      id: "channel",
      name: "Connect a channel",
      hint: "Slack, Telegram, GitHub, WhatsApp, email",
      keywords: ["slack", "telegram", "github", "remote"],
      run: () => ctx.onDialog("channel"),
    },
    {
      id: "coding",
      name: "Start a verified coding execution",
      hint: "Isolated build → checks → review → handoff",
      keywords: ["code", "repo", "worktree"],
      run: () => ctx.onDialog("coding"),
    },
    {
      id: "inspect",
      name: "Open the bot profile",
      hint: "Usage, autonomy, extensions, live run",
      keywords: ["usage", "settings", "profile", "policy"],
      run: () => ctx.onInspect(),
    },
    {
      id: "workflows",
      name: "Open the workflow canvas",
      hint: "Drag bots into a saved plan",
      keywords: ["dag", "plan", "canvas"],
      run: () => ctx.onWorkflows(),
    },
    ...(engine === "codex"
      ? []
      : []),
  ];
}

export interface GroupCommandContext {
  running: boolean;
  onStart: () => void;
  onStop: () => void;
}

/** Commands inside a group chat. */
export function buildGroupCommands(ctx: GroupCommandContext): SlashCommand[] {
  return [
    {
      id: "start",
      name: "Run a round",
      hint: ctx.running ? "A round is already running" : "Every bot takes a turn on the aim",
      keywords: ["round", "run", "go"],
      run: () => ctx.onStart(),
    },
    {
      id: "stop",
      name: "Stop the group",
      hint: ctx.running ? "Cancels the in-flight turn" : "The group is not running",
      keywords: ["cancel", "pause"],
      run: () => ctx.onStop(),
    },
  ];
}

/**
 * Parse `@name` mentions against a roster. Returns the canonical member names
 * in order of first appearance. Case-insensitive; tokens that match no member
 * are ignored (they are just prose).
 */
export function parseMentions(text: string, members: string[]): string[] {
  const found: string[] = [];
  const re = /(?:^|\s)@([A-Za-z0-9][A-Za-z0-9_\-.]*)/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    const token = match[1].toLowerCase();
    const member = members.find((name) => name.toLowerCase() === token);
    if (member && !found.includes(member)) found.push(member);
  }
  return found;
}

/**
 * Split message text into plain segments and mention tokens so the UI can
 * highlight them without dangerouslySetInnerHTML.
 */
export function splitMentions(
  text: string,
  members: string[],
): Array<{ kind: "text"; value: string } | { kind: "mention"; value: string }> {
  if (members.length === 0) return [{ kind: "text", value: text }];
  const escaped = members
    .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .sort((a, b) => b.length - a.length);
  const re = new RegExp(`(@(?:${escaped.join("|")}))`, "gi");
  return text
    .split(re)
    .filter((part) => part !== "")
    .map((part) =>
      part.startsWith("@") && members.some((name) => name.toLowerCase() === part.slice(1).toLowerCase())
        ? { kind: "mention", value: part.slice(1) }
        : { kind: "text", value: part },
    );
}
