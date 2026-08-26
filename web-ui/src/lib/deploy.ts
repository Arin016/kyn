/** True on static marketing deploys (e.g. Vercel) with no KYN daemon. */
const env = (import.meta as unknown as { env?: Record<string, string | boolean> }).env ?? {};

export const apiBase = String(env.VITE_KYN_API_URL ?? "").replace(/\/$/, "");

const TOKEN_KEY = "kyn_access_token";

function initTokenFromQuery(): void {
  const params = new URLSearchParams(location.search);
  const token = params.get("token");
  if (!token) return;
  sessionStorage.setItem(TOKEN_KEY, token);
  params.delete("token");
  const query = params.toString();
  history.replaceState(
    null,
    "",
    `${location.pathname}${query ? `?${query}` : ""}${location.hash}`,
  );
}

initTokenFromQuery();

export function accessToken(): string | null {
  const stored = sessionStorage.getItem(TOKEN_KEY);
  if (stored) return stored;
  const baked = env.VITE_KYN_ACCESS_TOKEN;
  return baked ? String(baked) : null;
}

export const isMarketingDeploy =
  !apiBase && (env.VITE_MARKETING_ONLY === "true" || env.VERCEL === "1");

export async function backendReachable(): Promise<boolean> {
  if (isMarketingDeploy) return false;
  try {
    const headers = new Headers();
    const token = accessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const res = await fetch(`${apiBase}/api/health`, { method: "GET", headers });
    return res.ok;
  } catch {
    return false;
  }
}
