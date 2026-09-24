import { useCallback, useEffect, useMemo, useState } from "react";
import api, { type SetupEngine, type SetupStatus } from "../../api";
import "./setup.css";

type Props = { onContinue: () => void };

export function SetupWizard({ onContinue }: Props) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState<SetupEngine["id"] | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await api.setupStatus());
      setError("");
    } catch (cause) {
      setError((cause as Error).message || "Ari could not check the installed coding engines.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const engines = useMemo(() => status?.engines ?? [], [status]);

  const install = async (engine: SetupEngine["id"]) => {
    setInstalling(engine);
    setMessage("");
    setError("");
    try {
      const result = await api.installEngine(engine);
      setMessage(`${result.label} is installed. Ari found it at ${result.binary}.`);
      await refresh();
    } catch (cause) {
      setError((cause as Error).message || "The installer could not complete.");
    } finally {
      setInstalling(null);
    }
  };

  const copyCommand = async (command: string) => {
    try {
      await navigator.clipboard.writeText(command);
      setMessage(`Copied: ${command}`);
    } catch {
      setMessage(`Run this in Terminal: ${command}`);
    }
  };

  return (
    <main className="setup-page">
      <div className="setup-shell">
        <header className="setup-brand">
          <img src="./brand-mark.svg" alt="" width="34" height="34" />
          <span>Ari</span>
          <span className="setup-brand-rule" />
          <span className="setup-brand-caption">LOCAL AGENT WORKSPACE</span>
        </header>

        <div className="setup-intro">
          <p className="setup-eyebrow">FIRST RUN · THIS MAC</p>
          <h1>Let’s get your workspace ready.</h1>
          <p className="setup-lead">
            Ari is a crew of coding helpers for this Mac. Choose an engine below; Ari will check whether its CLI is already installed.
          </p>
        </div>

        <section className="setup-engines" aria-labelledby="setup-engines-title">
          <div className="setup-section-heading">
            <div>
              <p className="setup-eyebrow">STEP 01</p>
              <h2 id="setup-engines-title">Coding engines</h2>
            </div>
            <button className="setup-quiet-button" type="button" onClick={() => void refresh()} disabled={loading || installing !== null}>
              Check again
            </button>
          </div>

          {loading && <p className="setup-inline-status">Checking this Mac…</p>}
          <div className="setup-engine-list">
            {engines.map((engine) => (
              <article className="setup-engine" key={engine.id}>
                <div className="setup-engine-main">
                  <div className={`setup-engine-indicator ${engine.available ? "is-ready" : ""}`} aria-hidden="true" />
                  <div>
                    <h3>{engine.label}</h3>
                    <p>
                      {engine.available
                        ? engine.version || engine.binary
                        : "Not installed yet"}
                    </p>
                  </div>
                </div>
                {engine.available ? (
                  <span className="setup-ready-label">Ready</span>
                ) : (
                  <button
                    className="setup-install-button"
                    type="button"
                    disabled={loading || installing !== null}
                    onClick={() => void install(engine.id)}
                  >
                    {installing === engine.id ? "Installing…" : "Install CLI"}
                  </button>
                )}
              </article>
            ))}
            {!loading && engines.length === 0 && (
              <p className="setup-inline-status">Ari could not read the engine status. Restart the app and try again.</p>
            )}
          </div>
          <p className="setup-note">
            Installers run only when you press the button. Codex setup uses Node.js and npm.
          </p>
        </section>

        <section className="setup-next" aria-labelledby="setup-next-title">
          <div>
            <p className="setup-eyebrow">STEP 02</p>
            <h2 id="setup-next-title">Sign in to your engine</h2>
            <p>Each engine uses its own account. Sign-in stays with the engine; Ari does not store those credentials.</p>
          </div>
          <div className="setup-command-list">
            <button type="button" onClick={() => void copyCommand("kiro-cli login")}>
              <span>Kiro</span><code>kiro-cli login</code><span aria-hidden="true">Copy</span>
            </button>
            <button type="button" onClick={() => void copyCommand("opencode") }>
              <span>OpenCode</span><code>opencode</code><span aria-hidden="true">Copy</span>
            </button>
            <button type="button" onClick={() => void copyCommand("codex --login")}>
              <span>Codex</span><code>codex --login</code><span aria-hidden="true">Copy</span>
            </button>
          </div>
        </section>

        <section className="setup-phone" aria-labelledby="setup-phone-title">
          <p className="setup-eyebrow">PHONE ACCESS</p>
          <h2 id="setup-phone-title">Use Ari on your iPhone</h2>
          <p>
            Install Tailscale on this Mac and your iPhone, sign in to the same private network, then run the command below in Terminal. Open the HTTPS URL it prints in iPhone Safari and choose Share → Add to Home Screen. Ari stays on this Mac; only devices allowed by your tailnet can reach it.
          </p>
          <button className="setup-tunnel-command" type="button" onClick={() => void copyCommand("tailscale serve --bg 8765")}>
            <code>tailscale serve --bg 8765</code><span>Copy command</span>
          </button>
          <a className="setup-doc-link" href="https://tailscale.com/docs/features/tailscale-serve" target="_blank" rel="noreferrer">
            Tailscale Serve setup and access rules <span aria-hidden="true">↗</span>
          </a>
        </section>

        {(message || error) && (
          <p className={`setup-feedback ${error ? "is-error" : ""}`} role="status">
            {error || message}
          </p>
        )}

        <footer className="setup-footer">
          <span>Your helper crew and history stay on this Mac.</span>
          <button className="setup-continue" type="button" onClick={onContinue}>
            Continue to Ari <span aria-hidden="true">↗</span>
          </button>
        </footer>
      </div>
    </main>
  );
}
