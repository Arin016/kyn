import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

/**
 * Shared pickers — the panel never asks for a comma-separated list of tools,
 * senders or arguments in a bare text box.
 */

export interface Option<T extends string> {
  value: T;
  label: string;
  hint?: string;
  disabled?: boolean;
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  label,
  size = "md",
  disabled = false,
}: {
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
  label?: string;
  size?: "sm" | "md";
  disabled?: boolean;
}) {
  return (
    <div
      className={`seg seg--${size}`}
      role="radiogroup"
      aria-label={label}
      data-disabled={disabled ? "true" : undefined}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          className="seg-option"
          data-active={option.value === value ? "true" : undefined}
          disabled={disabled || option.disabled}
          title={option.hint}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function ToggleSwitch({
  checked,
  onChange,
  label,
  hint,
  disabled = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="switch-row"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="switch-copy">
        <span className="switch-label">{label}</span>
        {hint ? <span className="switch-hint">{hint}</span> : null}
      </span>
      <span className={`switch${checked ? " is-on" : ""}`} aria-hidden>
        <span className="switch-knob" />
      </span>
    </button>
  );
}

export function NumberStepper({
  value,
  onChange,
  min = 0,
  max = 999,
  step = 1,
  label,
  hint,
  suffix,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  label: string;
  hint?: string;
  suffix?: string;
}) {
  const clamp = (next: number) => Math.min(max, Math.max(min, Math.round(next)));
  return (
    <div className="stepper-field">
      <span className="stepper-label">{label}</span>
      <div className="stepper">
        <button
          type="button"
          className="stepper-btn"
          aria-label={`Decrease ${label}`}
          onClick={() => onChange(clamp(value - step))}
          disabled={value <= min}
        >
          −
        </button>
        <input
          className="stepper-value"
          type="number"
          inputMode="numeric"
          value={value}
          min={min}
          max={max}
          step={step}
          aria-label={label}
          onChange={(event) => onChange(clamp(Number(event.target.value || 0)))}
        />
        <button
          type="button"
          className="stepper-btn"
          aria-label={`Increase ${label}`}
          onClick={() => onChange(clamp(value + step))}
          disabled={value >= max}
        >
          +
        </button>
      </div>
      <span className="stepper-hint">{hint || (suffix ? `0 means unlimited · ${suffix}` : "0 means unlimited")}</span>
    </div>
  );
}

export function TilePicker<T extends string>({
  value,
  options,
  onChange,
  label,
  columns = 3,
}: {
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
  label?: string;
  columns?: number;
}) {
  return (
    <div
      className="tile-grid"
      role="radiogroup"
      aria-label={label}
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          className="tile"
          data-active={option.value === value ? "true" : undefined}
          disabled={option.disabled}
          onClick={() => onChange(option.value)}
        >
          <span className="tile-label">{option.label}</span>
          {option.hint ? <span className="tile-hint">{option.hint}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function TagInput({
  value,
  onChange,
  suggestions = [],
  placeholder,
  label,
  hint,
  mono = false,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
  label?: string;
  hint?: string;
  mono?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  const add = (raw: string) => {
    const items = raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (items.length === 0) return;
    const next = [...value];
    for (const item of items) if (!next.includes(item)) next.push(item);
    onChange(next);
    setDraft("");
  };

  const matches = suggestions
    .filter((item) => !value.includes(item))
    .filter((item) => (draft ? item.toLowerCase().includes(draft.toLowerCase()) : true))
    .slice(0, 6);

  return (
    <div className="tag-field" ref={rootRef}>
      {label ? <span className="field-label">{label}</span> : null}
      <div className={`tag-input${mono ? " tag-input--mono" : ""}`}>
        {value.map((item) => (
          <span key={item} className="tag-chip">
            {item}
            <button
              type="button"
              aria-label={`Remove ${item}`}
              onClick={() => onChange(value.filter((entry) => entry !== item))}
            >
              ×
            </button>
          </span>
        ))}
        <input
          value={draft}
          placeholder={value.length === 0 ? placeholder : ""}
          aria-label={label || "Add value"}
          onChange={(event) => {
            setDraft(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              add(draft);
            }
            if (event.key === "Backspace" && !draft && value.length > 0) {
              onChange(value.slice(0, -1));
            }
            if (event.key === "Escape") setOpen(false);
          }}
          onBlur={() => {
            if (draft.trim()) add(draft);
          }}
        />
      </div>
      {open && matches.length > 0 && (
        <div className="tag-suggest" role="listbox">
          {matches.map((item) => (
            <button key={item} type="button" role="option" aria-selected={false} onClick={() => add(item)}>
              {item}
            </button>
          ))}
        </div>
      )}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  );
}

export interface KeyValueRow {
  key: string;
  value: string;
}

export function KeyValueRows({
  value,
  onChange,
  label,
  keyPlaceholder = "KEY",
  valuePlaceholder = "value",
  hint,
  addLabel = "Add row",
}: {
  value: KeyValueRow[];
  onChange: (rows: KeyValueRow[]) => void;
  label?: string;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  hint?: string;
  addLabel?: string;
}) {
  const update = (index: number, patch: Partial<KeyValueRow>) =>
    onChange(value.map((row, position) => (position === index ? { ...row, ...patch } : row)));

  return (
    <div className="kv-field">
      {label ? <span className="field-label">{label}</span> : null}
      {value.map((row, index) => (
        <div className="kv-row" key={`${index}-${row.key}`}>
          <input
            className="kv-key"
            value={row.key}
            placeholder={keyPlaceholder}
            aria-label={`${label || "Entry"} name ${index + 1}`}
            onChange={(event) => update(index, { key: event.target.value })}
          />
          <input
            className="kv-value"
            value={row.value}
            placeholder={valuePlaceholder}
            aria-label={`${label || "Entry"} value ${index + 1}`}
            onChange={(event) => update(index, { value: event.target.value })}
          />
          <button
            type="button"
            className="kv-remove"
            aria-label={`Remove ${row.key || `entry ${index + 1}`}`}
            onClick={() => onChange(value.filter((_, position) => position !== index))}
          >
            ×
          </button>
        </div>
      ))}
      <button type="button" className="kv-add" onClick={() => onChange([...value, { key: "", value: "" }])}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
          <path d="M12 5v14M5 12h14" strokeLinecap="round" />
        </svg>
        {addLabel}
      </button>
      {hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  );
}

export function FieldGroup({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="field-group">
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  );
}
