import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../../api";
import type { Bot, BotPluginBinding, PluginPlaceTemplate } from "../../types";
import { BotAvatar } from "../BotAvatar";
import { Modal } from "../ui/Modal";
import "./plugin-place.css";

interface Props {
  bots: Bot[];
  demoMode?: boolean;
  onBackToChat: () => void;
  showToast: (message: string, isError?: boolean) => void;
}

const POLL_MS = 5000;
type CatalogFilter = "all" | "connected" | "setup" | "available";
const CATALOG_FILTERS: { id: CatalogFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "connected", label: "Connected" },
  { id: "setup", label: "Needs setup" },
  { id: "available", label: "Available" },
];

/**
 * The Plugin Place: browse curated MCP servers, install them onto bots in
 * ask mode, and manage vault secrets. Bots adopt new tools by asking the
 * operator for permission on first use — never silently.
 */
export function PluginPlaceBoard({
  bots,
  demoMode = false,
  onBackToChat,
  showToast,
}: Props) {
  const [templates, setTemplates] = useState<PluginPlaceTemplate[]>([]);
  const [bindings, setBindings] = useState<Record<string, BotPluginBinding[]>>(
    {},
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [catalogFilter, setCatalogFilter] = useState<CatalogFilter>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [installing, setInstalling] = useState<PluginPlaceTemplate | null>(
    null,
  );
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [secrets, setSecrets] = useState<Record<string, string[]>>({});
  const [newSecret, setNewSecret] = useState({ name: "", value: "" });
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setRefreshing(true);
    if (demoMode) {
      setLoading(false);
      setRefreshing(false);
      return;
    }
    try {
      const results = await Promise.allSettled([
        api.pluginCatalog(),
        ...bots.map((bot) => api.botPlugins(bot.name)),
      ]);
      const catalogResult = results[0] as PromiseSettledResult<
        PluginPlaceTemplate[]
      >;
      const bindingResults = results.slice(1) as PromiseSettledResult<
        BotPluginBinding[]
      >[];
      if (catalogResult.status === "rejected") throw catalogResult.reason;
      const catalog = catalogResult.value;
      setTemplates(catalog);
      setBindings((current) =>
        Object.fromEntries(
          bots.map((bot, index) => {
            const result = bindingResults[index];
            return [
              bot.name,
              result?.status === "fulfilled"
                ? result.value
                : current[bot.name] || [],
            ];
          }),
        ),
      );
      setCatalogError("");
    } catch (exc) {
      setCatalogError(
        (exc as Error).message || "Could not load the plugin catalog.",
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [demoMode, bots]);

  useEffect(() => {
    void refresh();
    if (demoMode) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, demoMode]);

  const loadSecrets = useCallback(
    async (pluginId: string) => {
      if (demoMode) return;
      try {
        const data = await api.pluginSecrets(pluginId);
        setSecrets((current) => ({ ...current, [pluginId]: data.secrets }));
      } catch {
        /* names-only read; failure leaves the last known list */
      }
    },
    [demoMode],
  );

  useEffect(() => {
    if (
      selectedId &&
      templates.find((item) => item.id === selectedId)?.installed
    ) {
      void loadSecrets(selectedId);
    }
  }, [selectedId, templates, loadSecrets]);

  useEffect(() => {
    if (!selectedId && templates.length > 0) setSelectedId(templates[0].id);
  }, [selectedId, templates]);

  const selected = templates.find((item) => item.id === selectedId) || null;
  const selectedSecrets = selected ? secrets[selected.id] || [] : [];
  const selectedConnections = selected
    ? bots.filter((bot) =>
        bindings[bot.name]?.some(
          (binding) =>
            binding.plugin_id === selected.id && binding.enabled !== false,
        ),
      )
    : [];
  const counts = useMemo(
    () => ({
      all: templates.length,
      connected: templates.filter((item) =>
        bots.some((bot) =>
          bindings[bot.name]?.some(
            (binding) =>
              binding.plugin_id === item.id && binding.enabled !== false,
          ),
        ),
      ).length,
      setup: templates.filter(
        (item) => item.installed && item.missing_secrets.length > 0,
      ).length,
      available: templates.filter((item) => !item.installed).length,
    }),
    [templates, bots, bindings],
  );
  const visibleTemplates = templates.filter((item) => {
    const matchesQuery =
      !query.trim() ||
      `${item.name} ${item.blurb}`
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase());
    const isConnected = bots.some((bot) =>
      bindings[bot.name]?.some(
        (binding) => binding.plugin_id === item.id && binding.enabled !== false,
      ),
    );
    const matchesFilter =
      catalogFilter === "all" ||
      (catalogFilter === "connected" && isConnected) ||
      (catalogFilter === "setup" &&
        item.installed &&
        item.missing_secrets.length > 0) ||
      (catalogFilter === "available" && !item.installed);
    return matchesQuery && matchesFilter;
  });

  const connectBot = async (botName: string) => {
    if (!selected) return;
    setBusy(`connect:${botName}`);
    setError("");
    try {
      await api.installPlacePlugin({
        template_id: selected.id,
        bot_names: [botName],
        config: {},
      });
      await refresh();
      showToast(`${selected.name} connected to ${botName} in ask mode.`);
    } catch (exc) {
      setError(
        (exc as Error).message ||
          `Could not connect ${selected.name} to ${botName}.`,
      );
    } finally {
      setBusy("");
    }
  };

  const disconnectBot = async () => {
    if (!selected || !disconnecting) return;
    const botName = disconnecting;
    setBusy(`disconnect:${botName}`);
    setError("");
    try {
      await api.unbindPlugin(botName, selected.id);
      setDisconnecting(null);
      await refresh();
      showToast(`${selected.name} disconnected from ${botName}.`);
    } catch (exc) {
      setError(
        (exc as Error).message || `Could not disconnect ${selected.name}.`,
      );
    } finally {
      setBusy("");
    }
  };

  const saveSecret = async () => {
    if (!selected || !newSecret.name.trim() || !newSecret.value) return;
    setBusy("secret");
    setError("");
    try {
      await api.setPluginSecret(
        selected.id,
        newSecret.name.trim(),
        newSecret.value,
      );
      setNewSecret({ name: "", value: "" });
      await loadSecrets(selected.id);
      void refresh();
      showToast(
        `Secret stored for ${selected.name} — values never leave the vault.`,
        false,
      );
    } catch (exc) {
      setError((exc as Error).message || "Could not store the secret.");
    } finally {
      setBusy("");
    }
  };

  const removeSecret = async (name: string) => {
    if (!selected) return;
    setBusy(`secret:${name}`);
    try {
      await api.deletePluginSecret(selected.id, name);
      await loadSecrets(selected.id);
      void refresh();
    } catch (exc) {
      setError((exc as Error).message || "Could not delete the secret.");
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="workflow-page place-page" aria-label="Plugin Place">
      <aside className="workflow-rail place-rail" aria-label="Plugin catalog">
        <div className="place-rail-heading">
          <div>
            <p className="eyebrow">Connections</p>
            <h2>Plugin Place</h2>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-secondary place-refresh"
            onClick={() => void refresh()}
            disabled={refreshing}
            aria-label="Refresh plugin catalog"
          >
            {refreshing ? "…" : "↻"}
          </button>
        </div>
        <p className="place-rail-copy">
          Give your bots access to the tools they need. Every new tool still
          asks before it acts.
        </p>
        <label className="place-search">
          <span aria-hidden>⌕</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find an integration"
            aria-label="Search integrations"
          />
        </label>
        <nav className="place-filters" aria-label="Filter integrations">
          {CATALOG_FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              aria-pressed={catalogFilter === filter.id}
              onClick={() => setCatalogFilter(filter.id)}
            >
              {filter.label}
              <span>{counts[filter.id]}</span>
            </button>
          ))}
        </nav>
        <div
          className="workflow-list place-list"
          role="list"
          aria-label="Integrations"
        >
          {loading ? (
            <p className="place-catalog-message">Loading integrations…</p>
          ) : demoMode ? (
            <div className="place-catalog-message">
              <strong>Connect Ari to explore tools</strong>
              <span>
                The live catalog appears when a local daemon is connected.
              </span>
            </div>
          ) : catalogError ? (
            <div className="place-catalog-message" role="alert">
              <strong>Catalog unavailable</strong>
              <span>{catalogError}</span>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => void refresh()}
              >
                Try again
              </button>
            </div>
          ) : visibleTemplates.length === 0 ? (
            <div className="place-catalog-message">
              <strong>
                {query ? "No matching integrations" : "Nothing in this view"}
              </strong>
              <span>
                {query
                  ? "Try another name or clear the search."
                  : "Change the filter to see more connections."}
              </span>
              {(query || catalogFilter !== "all") && (
                <button
                  type="button"
                  className="mini-ghost"
                  onClick={() => {
                    setQuery("");
                    setCatalogFilter("all");
                  }}
                >
                  Show all
                </button>
              )}
            </div>
          ) : (
            visibleTemplates.map((item) => {
              const connected = bots.filter((bot) =>
                bindings[bot.name]?.some(
                  (binding) =>
                    binding.plugin_id === item.id && binding.enabled !== false,
                ),
              ).length;
              const status = item.installed
                ? item.missing_secrets.length > 0
                  ? "Needs setup"
                  : `${connected} bot${connected === 1 ? "" : "s"} connected`
                : "Ready to connect";
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`workflow-list-item place-list-item${selectedId === item.id ? " selected" : ""}`}
                  onClick={() => {
                    setSelectedId(item.id);
                    setError("");
                  }}
                  aria-current={selectedId === item.id ? "page" : undefined}
                >
                  <span
                    className={`place-service-mark${item.installed ? " is-installed" : ""}`}
                    aria-hidden
                  >
                    {item.name.slice(0, 1)}
                  </span>
                  <span className="place-list-copy">
                    <strong>{item.name}</strong>
                    <small>{status}</small>
                  </span>
                  <span className="place-list-arrow" aria-hidden>
                    ↗
                  </span>
                </button>
              );
            })
          )}
        </div>
        <button
          type="button"
          className="workflow-back place-back"
          onClick={onBackToChat}
        >
          ← Back to conversation
        </button>
      </aside>

      <div className="workflow-stage place-stage">
        {!selected ? (
          <div className="place-stage-empty">
            <span className="place-empty-mark" aria-hidden>
              ⌘
            </span>
            <p className="eyebrow">Plugin Place</p>
            <h1>Bring your tools into Ari</h1>
            <p>
              Search the catalog, then choose an integration to see what it can
              do and which bots can use it.
            </p>
          </div>
        ) : (
          <div className="workflow-stage-body place-detail-body">
            <header className="workflow-stage-header place-detail-header">
              <div>
                <p className="eyebrow">
                  {selected.transport} integration ·{" "}
                  {selected.installed ? "configured" : "catalog"}
                </p>
                <h1>{selected.name}</h1>
              </div>
              <a
                className="btn btn-sm btn-secondary"
                href={selected.docs_url}
                target="_blank"
                rel="noreferrer"
              >
                Documentation ↗
              </a>
            </header>
            {error && (
              <div
                className="workflow-load-error place-inline-error"
                role="alert"
              >
                {error}
              </div>
            )}
            <div className="place-detail-content">
              <section className="place-intro">
                <div
                  className="place-service-mark place-service-mark--large"
                  aria-hidden
                >
                  {selected.name.slice(0, 1)}
                </div>
                <div className="place-intro-copy">
                  <div className="place-status-line">
                    <span
                      className={`place-status-dot${selected.installed ? " is-installed" : ""}`}
                      aria-hidden
                    />
                    <span>
                      {selected.installed
                        ? selected.missing_secrets.length
                          ? "Setup needs attention"
                          : "Configured and ready"
                        : "Not connected yet"}
                    </span>
                    <span className="place-transport">
                      {selected.transport}
                    </span>
                  </div>
                  <p>{selected.blurb}</p>
                  <div className="place-intro-actions">
                    {!selected.installed && (
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        onClick={() => setInstalling(selected)}
                      >
                        Connect bots <span aria-hidden>→</span>
                      </button>
                    )}
                    {selected.installed && (
                      <span className="place-connected-count">
                        {selectedConnections.length}{" "}
                        {selectedConnections.length === 1 ? "bot" : "bots"}{" "}
                        connected
                      </span>
                    )}
                  </div>
                </div>
              </section>

              {selected.warning && (
                <aside className="place-warning" role="note">
                  <strong>Before you connect</strong>
                  <p>{selected.warning}</p>
                </aside>
              )}
              {selected.missing_secrets.length > 0 && (
                <div className="place-setup-alert" role="status">
                  <span aria-hidden>!</span>
                  <div>
                    <strong>Finish setup to use this integration</strong>
                    <p>
                      Add {selected.missing_secrets.join(", ")} to the vault.
                      Bots can connect now, but sessions that need these values
                      will wait.
                    </p>
                  </div>
                </div>
              )}

              <section
                className="place-section"
                aria-labelledby="place-bots-title"
              >
                <header className="place-section-heading">
                  <div>
                    <p className="eyebrow">Access</p>
                    <h2 id="place-bots-title">Bots with this connection</h2>
                  </div>
                  <span>
                    {selectedConnections.length} of {bots.length}
                  </span>
                </header>
                {bots.length === 0 ? (
                  <div className="place-inline-empty">
                    <strong>No bots yet</strong>
                    <span>Create a bot first, then connect it here.</span>
                  </div>
                ) : (
                  <ul className="place-connection-list">
                    {bots.map((bot) => {
                      const connected = selectedConnections.some(
                        (item) => item.name === bot.name,
                      );
                      const pending = busy.endsWith(`:${bot.name}`);
                      return (
                        <li key={bot.name}>
                          <div className="place-bot-identity">
                            <BotAvatar name={bot.name} size={34} />
                            <span>
                              <strong>{bot.name}</strong>
                              <small>{bot.engine || "Bot"}</small>
                            </span>
                          </div>
                          {connected ? (
                            <div className="place-connection-state">
                              <span>
                                <i aria-hidden />
                                Connected · asks before using
                              </span>
                              <button
                                type="button"
                                className="mini-ghost"
                                disabled={busy !== ""}
                                onClick={() => setDisconnecting(bot.name)}
                              >
                                Disconnect
                              </button>
                            </div>
                          ) : selected.installed ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-secondary"
                              disabled={busy !== ""}
                              onClick={() => void connectBot(bot.name)}
                            >
                              {pending ? "Connecting…" : "＋ Connect"}
                            </button>
                          ) : (
                            <span className="place-not-connected">
                              Not connected
                            </span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>

              {selected.installed && (
                <section
                  className="place-section"
                  aria-labelledby="place-vault-title"
                >
                  <header className="place-section-heading">
                    <div>
                      <p className="eyebrow">Credentials</p>
                      <h2 id="place-vault-title">Secret vault</h2>
                    </div>
                    <span>{selectedSecrets.length} stored</span>
                  </header>
                  <p className="place-section-copy">
                    Secret values stay in Ari’s vault and are never shown again.
                    Only their names are listed here.
                  </p>
                  <ul className="task-files place-secret-list">
                    {selectedSecrets.map((name) => (
                      <li key={name}>
                        <code>{name}</code>
                        <button
                          type="button"
                          className="mini-ghost"
                          disabled={busy !== ""}
                          onClick={() => void removeSecret(name)}
                        >
                          {busy === `secret:${name}` ? "Removing…" : "Remove"}
                        </button>
                      </li>
                    ))}
                    {selectedSecrets.length === 0 && (
                      <li>
                        <span>No secrets stored yet.</span>
                      </li>
                    )}
                  </ul>
                  <div className="place-secret-form">
                    <label>
                      <span>Secret name</span>
                      <input
                        aria-label="Secret name"
                        value={newSecret.name}
                        onChange={(event) =>
                          setNewSecret((current) => ({
                            ...current,
                            name: event.target.value,
                          }))
                        }
                        placeholder="GITHUB_TOKEN"
                        className="mono"
                      />
                    </label>
                    <label className="place-secret-value">
                      <span>Secret value</span>
                      <input
                        aria-label="Secret value"
                        type="password"
                        value={newSecret.value}
                        onChange={(event) =>
                          setNewSecret((current) => ({
                            ...current,
                            value: event.target.value,
                          }))
                        }
                        placeholder="Paste token — never in chat"
                        autoComplete="new-password"
                      />
                    </label>
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary"
                      disabled={
                        busy !== "" ||
                        !newSecret.name.trim() ||
                        !newSecret.value
                      }
                      onClick={() => void saveSecret()}
                    >
                      {busy === "secret" ? "Saving…" : "Save secret"}
                    </button>
                  </div>
                </section>
              )}

              {!selected.installed && (
                <section
                  className="place-section"
                  aria-labelledby="place-setup-title"
                >
                  <header className="place-section-heading">
                    <div>
                      <p className="eyebrow">Setup</p>
                      <h2 id="place-setup-title">What you’ll need</h2>
                    </div>
                    <span>{selected.config_schema.length} fields</span>
                  </header>
                  <ul className="place-requirements">
                    {selected.config_schema.map((field) => (
                      <li key={field.key}>
                        <span className="place-requirement-check" aria-hidden>
                          {field.secret ? "•" : "↗"}
                        </span>
                        <div>
                          <strong>
                            {field.label}
                            {field.required ? " · required" : " · optional"}
                          </strong>
                          <p>
                            {field.hint ||
                              (field.secret
                                ? "Stored securely in Ari’s vault."
                                : `Used to configure ${selected.name}.`)}
                          </p>
                        </div>
                      </li>
                    ))}
                    {selected.config_schema.length === 0 && (
                      <li>
                        <span className="place-requirement-check" aria-hidden>
                          ✓
                        </span>
                        <div>
                          <strong>Ready to connect</strong>
                          <p>No extra setup fields are needed.</p>
                        </div>
                      </li>
                    )}
                  </ul>
                </section>
              )}
              <p className="place-safety-note">
                <span aria-hidden>◇</span> Connected tools use ask mode. Your
                bot must request approval before using a tool.
              </p>
            </div>
          </div>
        )}
      </div>

      {installing && (
        <InstallDialog
          template={installing}
          bots={bots}
          onClose={() => setInstalling(null)}
          onDone={() => {
            setInstalling(null);
            void refresh();
            void loadSecrets(installing.id);
            showToast(
              "Connected in ask mode — tool use always asks for your approval.",
              false,
            );
          }}
          showToast={showToast}
        />
      )}
      {disconnecting && selected && (
        <Modal
          eyebrow="Plugin Place"
          title={`Disconnect ${selected.name}?`}
          open
          onClose={() => setDisconnecting(null)}
        >
          <div className="modal-form">
            <p className="dialog-copy">
              {disconnecting} will no longer be able to use this integration.
              You can reconnect it at any time. Saved vault secrets stay
              available to other connected bots.
            </p>
            <div className="dialog-actions">
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setDisconnecting(null)}
              >
                Keep connected
              </button>
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={busy !== ""}
                onClick={() => void disconnectBot()}
              >
                {busy.startsWith("disconnect:")
                  ? "Disconnecting…"
                  : "Disconnect bot"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}

function InstallDialog({
  template,
  bots,
  onClose,
  onDone,
  showToast,
}: {
  template: PluginPlaceTemplate;
  bots: Bot[];
  onClose: () => void;
  onDone: () => void;
  showToast: (message: string, isError?: boolean) => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  const toggle = (name: string) =>
    setPicked((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    );

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    if (picked.length === 0) {
      setError("Pick at least one bot.");
      return;
    }
    setStarting(true);
    try {
      const result = (await api.installPlacePlugin({
        template_id: template.id,
        bot_names: picked,
        config: values,
      })) as { missing_secrets?: string[] };
      onDone();
      const missing = result.missing_secrets || [];
      if (missing.length > 0) {
        showToast(
          `Installed — still needs secrets: ${missing.join(", ")}`,
          false,
        );
      }
    } catch (exc) {
      setError((exc as Error).message || "Could not install.");
    } finally {
      setStarting(false);
    }
  };

  return (
    <Modal
      eyebrow="Plugin Place"
      title={`Install ${template.name}`}
      open
      onClose={onClose}
    >
      <form className="modal-form" onSubmit={submit}>
        <p className="dialog-copy">
          Binds onto the chosen bots in ask mode. Secrets go to the vault — type
          tokens below, never in chat.
        </p>
        <fieldset className="place-bots">
          <legend>Bots</legend>
          {bots.length === 0 && (
            <p className="activity-empty">No bots yet — create one first.</p>
          )}
          {bots.map((bot) => (
            <label key={bot.name} className="place-bot-check">
              <input
                type="checkbox"
                checked={picked.includes(bot.name)}
                onChange={() => toggle(bot.name)}
              />
              <span>
                <strong>{bot.name}</strong>
                <small>{bot.engine}</small>
              </span>
            </label>
          ))}
        </fieldset>
        {template.config_schema.map((field) => (
          <label key={field.key}>
            {field.label}
            {field.required ? " (required)" : ""}
            <input
              type={field.secret ? "password" : "text"}
              value={values[field.key] || ""}
              onChange={(event) =>
                setValues((current) => ({
                  ...current,
                  [field.key]: event.target.value,
                }))
              }
              placeholder={field.placeholder || ""}
              autoComplete="off"
            />
            {field.hint && <span className="field-hint">{field.hint}</span>}
          </label>
        ))}
        <p className="form-error" role="alert">
          {error}
        </p>
        <div className="dialog-actions">
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-sm btn-primary"
            disabled={starting || bots.length === 0}
          >
            {starting ? "Installing…" : "Install in ask mode"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
