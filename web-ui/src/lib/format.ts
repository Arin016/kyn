export function csv(value: string | null | undefined): string[] {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseEnvReferences(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  String(raw || "")
    .split(/\n|,/)
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const split = line.indexOf("=");
      if (split < 1) throw new Error("Environment references must use NAME=env:SOURCE.");
      result[line.slice(0, split).trim()] = line.slice(split + 1).trim();
    });
  return result;
}

export function shortTime(value: string | Date | undefined): string {
  const date = value ? new Date(value) : new Date();
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function fullTime(value: string | undefined): string {
  if (!value) return "";
  return new Date(value).toLocaleString([], { dateStyle: "short", timeStyle: "short" });
}

export function truncate(text: string, limit: number): string {
  const flat = String(text || "").replaceAll("\n", " ");
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}
