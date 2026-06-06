// Shared formatters. Consolidates copies that were byte-identical across the
// planning drawers/boards. NOTE: there are deliberately TWO compact UGX variants
// (they round differently and several screens depend on the exact output) plus a
// "full" comma form elsewhere — don't collapse them into one.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Compact UGX, 1-decimal millions: `UGX 1.5M` · `UGX 500K` · `UGX 250`. */
export function formatUgxShort(amount: number): string {
  if (amount >= 1_000_000) return `UGX ${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `UGX ${(amount / 1_000).toFixed(0)}K`;
  return `UGX ${amount}`;
}

/** Compact UGX, precise millions + zero handling: `UGX 0` · `UGX 1.25M` · `UGX 500K`. */
export function formatUgxCompact(amount: number): string {
  if (amount === 0) return "UGX 0";
  if (amount >= 1_000_000) return `UGX ${(amount / 1_000_000).toFixed(amount % 1_000_000 === 0 ? 0 : 2)}M`;
  if (amount >= 1_000) return `UGX ${(amount / 1_000).toFixed(0)}K`;
  return `UGX ${amount}`;
}

/** ISO date → day-first human form: `6 Jun 2026`. Returns the input unchanged if unparseable. */
export function formatHumanDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}
