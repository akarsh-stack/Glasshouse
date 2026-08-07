export function fmtMs(ms: number | undefined | null): string {
  if (ms === undefined || ms === null || Number.isNaN(ms)) return "—";
  if (ms >= 10_000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms >= 100) return `${Math.round(ms)}ms`;
  return `${ms.toFixed(1)}ms`;
}

export function fmtCost(usd: number | undefined | null): string {
  if (usd === undefined || usd === null || Number.isNaN(usd)) return "—";
  return `$${usd.toFixed(4)}`;
}

export function fmtPct(frac: number | undefined | null): string {
  if (frac === undefined || frac === null || Number.isNaN(frac)) return "—";
  return `${(frac * 100).toFixed(1)}%`;
}

export function fmtNum(n: number | undefined | null, digits = 2): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}
