/** KYN console is dark-only. */
export type Theme = "dark";

export function useTheme(): [Theme, () => void] {
  return ["dark", () => {}];
}
