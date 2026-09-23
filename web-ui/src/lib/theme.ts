/**
 * Theme store — light (paper) is the default, dark is "black mode".
 *
 * The attribute is `data-kyn-theme`, deliberately namespaced so host shells,
 * extensions, or anything else writing `data-theme` on <html> cannot repaint
 * the app out from under us.
 */
export type Theme = "light" | "dark";

const STORAGE_KEY = "kyn-theme";
export const THEME_ATTRIBUTE = "data-kyn-theme";

export function readTheme(): Theme {
  if (typeof window === "undefined") return "light";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "light") return stored;
  } catch {
    /* storage blocked — fall through to the default */
  }
  return "light";
}

export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute(THEME_ATTRIBUTE, theme);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "dark" ? "#060806" : "#f4f7f3");
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* ignore quota / private-mode failures */
  }
}

export function toggleTheme(): Theme {
  const next: Theme = readTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}
