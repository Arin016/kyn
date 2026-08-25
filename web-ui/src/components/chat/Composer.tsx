import { useEffect, useRef } from "react";

interface Props {
  disabled: boolean;
  busy: boolean;
  hint: string;
  mirrorNote: boolean;
  placeholder: string;
  onSubmit: (message: string) => void;
  onStop: () => void;
}

export function Composer({ disabled, busy, hint, mirrorNote, placeholder, onSubmit, onStop }: Props) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const resize = () => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 190)}px`;
  };

  useEffect(() => {
    resize();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && busy) onStop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onStop]);

  return (
    <div className="composer-zone">
      {mirrorNote && <p className="remote-note">Reply from your phone. This view is a live mirror of the remote thread.</p>}
      <form
        ref={formRef}
        onSubmit={(event) => {
          event.preventDefault();
          const value = inputRef.current?.value.trim();
          if (!value || disabled || busy) return;
          onSubmit(value);
          if (inputRef.current) inputRef.current.value = "";
          resize();
        }}
        className="composer-shell"
      >
        <textarea
          ref={inputRef}
          className="composer-textarea"
          rows={1}
          placeholder={placeholder}
          disabled={disabled}
          aria-label="Message your bot"
          onInput={resize}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              formRef.current?.requestSubmit();
            }
          }}
        />
        <div className="composer-footer">
          <span className="composer-hint">{hint}</span>
          {busy ? (
            <button
              type="button"
              className="send-btn stop-mode"
              onClick={onStop}
              aria-label="Stop generating (Esc)"
              title="Stop generating (Esc)"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            </button>
          ) : (
            <button type="submit" className="send-btn" disabled={disabled} aria-label="Send">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
                <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
