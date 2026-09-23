import type { Plugin } from "../types";

/** A selectable permission target in the Safety tab. */
export interface ToolEntry {
  id: string;
  group: string;
  label: string;
  hint?: string;
  /** Destructive or outward-facing — gets a warning style in the matrix. */
  sensitive?: boolean;
}

/**
 * Built-in tool families KYN governs. Deny/allow rules match on these names,
 * so the console offers them as first-class choices instead of free text.
 */
export const BUILTIN_TOOLS: ToolEntry[] = [
  { id: "filesystem.read", group: "Files", label: "Read files", hint: "Open, list and inspect workspace files" },
  {
    id: "filesystem.write",
    group: "Files",
    label: "Write files",
    hint: "Create or edit files in the working directory",
    sensitive: true,
  },
  {
    id: "filesystem.delete",
    group: "Files",
    label: "Delete files",
    hint: "Remove files or directories",
    sensitive: true,
  },
  { id: "search.grep", group: "Search", label: "Search code", hint: "Grep, glob and find references" },
  { id: "web.fetch", group: "Search", label: "Fetch URLs", hint: "Read pages and HTTP APIs", sensitive: true },
  {
    id: "shell.exec",
    group: "System",
    label: "Run commands",
    hint: "Execute shell commands in the working directory",
    sensitive: true,
  },
  { id: "git.commit", group: "Git", label: "Commit changes", hint: "Stage and commit local changes", sensitive: true },
  { id: "git.push", group: "Git", label: "Push branches", hint: "Push commits to a remote", sensitive: true },
  { id: "memory.write", group: "Memory", label: "Write memory", hint: "Store shared evidence for later turns" },
];

/** Plugin tools are namespaced by connection id, so they extend the catalog. */
export function pluginTools(plugins: Plugin[]): ToolEntry[] {
  return plugins
    .filter((plugin) => plugin.id !== "kyn-control")
    .map((plugin) => ({
      id: `${plugin.id}.*`,
      group: "MCP connections",
      label: plugin.name || plugin.id,
      hint: `${plugin.transport || "MCP"} connection tools`,
      sensitive: true,
    }));
}

export interface ToolPreset {
  id: string;
  label: string;
  hint: string;
  allowed: string[];
  denied: string[];
}

export const TOOL_PRESETS: ToolPreset[] = [
  {
    id: "read-only",
    label: "Read only",
    hint: "Look, never touch",
    allowed: ["filesystem.read", "search.grep", "memory.write"],
    denied: ["filesystem.write", "filesystem.delete", "shell.exec", "git.push", "git.commit"],
  },
  {
    id: "no-shell",
    label: "No shell",
    hint: "Everything except running commands",
    allowed: ["*"],
    denied: ["shell.exec"],
  },
  {
    id: "review",
    label: "Pair review",
    hint: "Edit freely, ask before pushing",
    allowed: ["filesystem.read", "filesystem.write", "search.grep", "shell.exec"],
    denied: ["git.push"],
  },
  {
    id: "trust",
    label: "Trust all",
    hint: "No prompts at all",
    allowed: ["*"],
    denied: [],
  },
];
