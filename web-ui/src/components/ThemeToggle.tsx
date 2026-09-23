import { useEffect, useState } from "react";
import { applyTheme, readTheme, type Theme } from "../lib/theme";

const MoonIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden>
    <path
      d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const SunIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden>
    <circle cx="12" cy="12" r="4" />
    <path
      d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"
      strokeLinecap="round"
    />
  </svg>
);

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  // Sync with whatever the pre-paint script already applied.
  useEffect(() => {
    const current = readTheme();
    setTheme(current);
    applyTheme(current);
  }, []);

  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      className="theme-toggle"
      aria-pressed={theme === "dark"}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      onClick={() => {
        applyTheme(next);
        setTheme(next);
      }}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      <span>{next === "dark" ? "Dark" : "Light"}</span>
    </button>
  );
}
