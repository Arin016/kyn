import React from "react";

interface Props {
  value: string;
  hint: string;
  mirrorNote: boolean;
  placeholder: string;
  busy: boolean;
  disabled: boolean;
  sendHot?: boolean;
}

/** Controlled composer for Remotion — same chrome as production Composer. */
export const DemoComposer: React.FC<Props> = ({
  value,
  hint,
  mirrorNote,
  placeholder,
  busy,
  disabled,
  sendHot = false,
}) => {
  return (
    <div className="composer-zone">
      {mirrorNote ? (
        <p className="remote-note">Reply from your phone. This view is a live mirror of the remote thread.</p>
      ) : (
        <div className="composer-shell" data-demo-composer>
          <textarea
            className="composer-textarea"
            rows={value.split("\n").length || 1}
            value={value}
            placeholder={placeholder}
            disabled={disabled}
            readOnly
            aria-label="Message your bot"
            style={{ height: Math.min(24 + value.split("\n").length * 24, 140) }}
          />
          <div className="composer-footer">
            <span className="composer-hint">{hint}</span>
            {busy ? (
              <button type="button" className="send-btn stop-mode" aria-label="Stop">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              </button>
            ) : (
              <button
                type="button"
                className="send-btn"
                disabled={disabled || !value}
                aria-label="Send"
                style={
                  sendHot
                    ? {
                        boxShadow: "0 0 0 4px rgba(176,139,255,0.35)",
                        transform: "scale(1.06)",
                      }
                    : undefined
                }
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
                  <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
