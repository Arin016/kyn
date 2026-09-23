import { useMemo, useState } from "react";
import { BUILTIN_TOOLS, TOOL_PRESETS, pluginTools } from "../../lib/tools";
import type { ToolEntry } from "../../lib/tools";
import type { Plugin } from "../../types";

export type ToolDecision = "allow" | "ask" | "deny";

const DECISIONS: { value: ToolDecision; label: string }[] = [
  { value: "allow", label: "Allow" },
  { value: "ask", label: "Ask" },
  { value: "deny", label: "Deny" },
];

export function decisionFor(tool: string, allowed: string[], denied: string[]): ToolDecision {
  if (denied.includes(tool)) return "deny";
  if (allowed.includes(tool)) return "allow";
  return "ask";
}

/**
 * One row per tool family: Allow runs it silently, Ask prompts you, Deny blocks
 * it. The two backend lists are derived from these three choices, so the model
 * stays simple even though the engine only speaks allow/deny.
 */
export function ToolPermissions({
  allowed,
  denied,
  plugins,
  onChange,
}: {
  allowed: string[];
  denied: string[];
  plugins: Plugin[];
  onChange: (next: { allowed_tools: string[]; denied_tools: string[] }) => void;
}) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);

  const catalog = useMemo<ToolEntry[]>(
    () => [
      ...BUILTIN_TOOLS,
      ...pluginTools(plugins),
      {
        id: "*",
        group: "Everything else",
        label: "Any other tool",
        hint: "Tools not named above, including future ones",
        sensitive: true,
      },
    ],
    [plugins],
  );

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = catalog.filter(
      (tool) =>
        !needle ||
        tool.id.toLowerCase().includes(needle) ||
        tool.label.toLowerCase().includes(needle) ||
        tool.group.toLowerCase().includes(needle),
    );
    const grouped = new Map<string, ToolEntry[]>();
    for (const tool of filtered) {
      const bucket = grouped.get(tool.group) || [];
      bucket.push(tool);
      grouped.set(tool.group, bucket);
    }
    return [...grouped.entries()];
  }, [catalog, query]);

  const decide = (tool: string, decision: ToolDecision) => {
    const nextAllowed = allowed.filter((item) => item !== tool);
    const nextDenied = denied.filter((item) => item !== tool);
    if (decision === "allow") nextAllowed.push(tool);
    if (decision === "deny") nextDenied.push(tool);
    onChange({ allowed_tools: nextAllowed, denied_tools: nextDenied });
  };

  const counts = useMemo(
    () => ({
      allow: catalog.filter((tool) => decisionFor(tool.id, allowed, denied) === "allow").length,
      ask: catalog.filter((tool) => decisionFor(tool.id, allowed, denied) === "ask").length,
      deny: catalog.filter((tool) => decisionFor(tool.id, allowed, denied) === "deny").length,
    }),
    [catalog, allowed, denied],
  );

  const visibleGroups = expanded ? groups : groups.slice(0, 3);

  return (
    <div className="perm-matrix">
      <div className="perm-presets" role="group" aria-label="Permission presets">
        {TOOL_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className="perm-preset"
            title={preset.hint}
            onClick={() => onChange({ allowed_tools: [...preset.allowed], denied_tools: [...preset.denied] })}
          >
            {preset.label}
          </button>
        ))}
        <button
          type="button"
          className="perm-preset perm-preset--quiet"
          onClick={() => onChange({ allowed_tools: [], denied_tools: [] })}
        >
          Ask for everything
        </button>
      </div>

      <div className="perm-toolbar">
        <span className="perm-counts">
          <span className="perm-count" data-tone="allow">
            {counts.allow} allowed
          </span>
          <span className="perm-count" data-tone="ask">
            {counts.ask} ask
          </span>
          <span className="perm-count" data-tone="deny">
            {counts.deny} denied
          </span>
        </span>
        <input
          className="perm-search"
          value={query}
          placeholder="Filter tools…"
          aria-label="Filter tools"
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <div className="perm-groups">
        {visibleGroups.length === 0 && <p className="activity-empty">No tool matches “{query}”.</p>}
        {visibleGroups.map(([group, tools]) => (
          <div className="perm-group" key={group}>
            <p className="perm-group-label">{group}</p>
            {tools.map((tool) => {
              const decision = decisionFor(tool.id, allowed, denied);
              return (
                <div className="perm-row" key={tool.id} data-sensitivity={tool.sensitive ? "high" : "normal"}>
                  <span className="perm-tool">
                    <span className="perm-tool-name">{tool.label}</span>
                    <span className="perm-tool-id">{tool.id}</span>
                    {tool.hint ? <span className="perm-tool-hint">{tool.hint}</span> : null}
                  </span>
                  <span className="perm-states" role="radiogroup" aria-label={`${tool.label} permission`}>
                    {DECISIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        role="radio"
                        aria-checked={decision === option.value}
                        className="perm-state"
                        data-decision={option.value}
                        data-active={decision === option.value ? "true" : undefined}
                        onClick={() => decide(tool.id, option.value)}
                      >
                        {option.label}
                      </button>
                    ))}
                  </span>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {groups.length > 3 && (
        <button type="button" className="perm-more" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
          {expanded ? "Show fewer tool families" : `Show all ${groups.length} tool families`}
        </button>
      )}
    </div>
  );
}
