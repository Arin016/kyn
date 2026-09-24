/**
 * Theme store — matte graphite dark mode is the default; light mode remains available.
 *
 * The attribute is `data-ari-theme`, deliberately namespaced so host shells,
 * extensions, or anything else writing `data-theme` on <html> cannot repaint
 * the app out from under us.
 */
export type Theme = "light" | "dark";

const STORAGE_KEY = "ari-theme";
export const THEME_ATTRIBUTE = "data-ari-theme";

export function readTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY) || window.localStorage.getItem("kyn-theme");
    if (stored === "dark" || stored === "light") return stored;
  } catch {
    /* storage blocked — fall through to the default */
  }
  return "dark";
}

export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute(THEME_ATTRIBUTE, theme);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "dark" ? "#1b1c1e" : "#f4f5f6");
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
