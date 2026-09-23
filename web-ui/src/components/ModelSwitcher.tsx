import { useEffect, useRef, useState } from "react";
import api from "../api";
import { KIRO_MODELS } from "./dialogs/Dialogs";
import type { Bot } from "../types";

/**
 * Model switcher — change a bot's model mid-conversation.
 *
 * The daemon applies the change to the live session when it can and reports
 * `applied_live`; otherwise it lands on the next run. Works from the chat
 * header (compact pill) and from the Inspect panel's Bot tab.
 */
interface Props {
  bot: Bot | null;
  onSwitch: (model: string) => Promise<boolean> | boolean;
  disabled?: boolean;
  /** Compact renders the header pill; the panel renders a labelled row. */
  variant?: "pill" | "block";
}

export function ModelSwitcher({ bot, onSwitch, disabled = false, variant = "pill" }: Props) {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const engine = (bot?.engine || "kiro").toLowerCase();

  useEffect(() => {
    if (!open || !bot || disabled) return;
    setError("");
    if (engine === "kiro") {
      setModels(KIRO_MODELS.filter((model) => model.id !== "__custom"));
      setLoading(false);
      return;
    }
    if (engine === "codex") {
      setModels([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .engines(engine)
      .then((data) => setModels(data.models || []))
      .catch((exc: Error) => setError(exc.message || "Could not load models"))
      .finally(() => setLoading(false));
  }, [open, bot, engine, disabled]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const current = bot?.model || "Default model";
  const currentId = bot?.model || "";

  const choose = async (model: string) => {
    if (model === currentId) {
      setOpen(false);
      return;
    }
    setPending(model);
    const ok = await onSwitch(model);
    setPending("");
    if (ok) setOpen(false);
  };

  return (
    <div className={`model-switch model-switch--${variant}`} ref={rootRef}>
      <button
        type="button"
        className="model-pill"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled || !bot}
        onClick={() => setOpen((value) => !value)}
        title={disabled ? "Model switching needs a local daemon" : "Switch model mid-conversation"}
      >
        <span className="model-pill__dot" aria-hidden />
        <span className="model-pill__label">{current}</span>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="model-menu" role="listbox" aria-label="Models">
          <p className="model-menu__head">
            {engine} models
            <span>applies immediately</span>
          </p>
          {loading && <p className="model-menu__note">Loading models…</p>}
          {error && <p className="model-menu__note model-menu__note--error">{error}</p>}
          {!loading && !error && models.length === 0 && (
            <p className="model-menu__note">No models reported by this engine.</p>
          )}
          <ul className="model-menu__list">
            {models.map((model) => {
              const active = model.id === currentId;
              return (
                <li key={model.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={active}
                    className={`model-option${active ? " is-active" : ""}`}
                    onClick={() => void choose(model.id)}
                  >
                    <span className="model-option__text">
                      <strong>{model.label || model.id}</strong>
                      <small>{model.id}</small>
                    </span>
                    {pending === model.id ? (
                      <span className="model-option__mark">…</span>
                    ) : active ? (
                      <span className="model-option__mark" aria-hidden>
                        ✓
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
