// Shared UGX / percent formatters for the budget dashboards.

export function fmtUgx(n: number): string {
  return `UGX ${Math.round(n).toLocaleString()}`;
}

/** Compact: UGX 2.84B / UGX 520M / UGX 370K. */
export function fmtUgxShort(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `UGX ${(n / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `UGX ${Math.round(n / 1_000_000)}M`;
  if (abs >= 1_000) return `UGX ${Math.round(n / 1_000)}K`;
  return `UGX ${Math.round(n)}`;
}

export function fmtPct(n: number): string {
  return `${n.toFixed(1)}%`;
}
