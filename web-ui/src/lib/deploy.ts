/** True on static marketing deploys (e.g. Vercel) with no KYN daemon. */
const env = (import.meta as unknown as { env?: Record<string, string | boolean> }).env ?? {};

export const apiBase = String(env.VITE_KYN_API_URL ?? "").replace(/\/$/, "");

const TOKEN_KEY = "kyn_access_token";

function marketingHost(): boolean {
  if (typeof location === "undefined") return false;
  return /\.vercel\.app$/i.test(location.hostname);
}

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

const marketingFlag = env.VITE_MARKETING_ONLY;
export const isMarketingDeploy =
  !apiBase &&
  (marketingFlag === "true" ||
    marketingFlag === true ||
    (env.PROD === true && marketingHost()));

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
