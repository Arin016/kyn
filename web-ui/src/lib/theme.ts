import { useCallback, useState } from "react";

export type Theme = "light" | "dark";

function initialTheme(): Theme {
  const current = document.documentElement.dataset.theme;
  return current === "light" ? "light" : "dark";
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try {
        localStorage.setItem("kyn-theme", next);
      } catch {
        /* storage unavailable */
      }
      return next;
    });
  }, []);

  return [theme, toggle];
}
