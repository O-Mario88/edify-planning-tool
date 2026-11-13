/**
 * Which of a strip's figures are in view, as the existing web counts them
 * (static/js/kpi-strips.js): in first-cell widths, so "1–8 of 10" reads the
 * same there and here; and the thumb of the track under the strip. Null while
 * every figure fits (no rail is drawn then) or nothing is measured yet.
 */
export function stripRange({
  count,
  cell,
  width,
  scrollLeft,
  scrollWidth,
}: {
  count: number;
  cell: number;
  width: number;
  scrollLeft: number;
  scrollWidth: number;
}): { overflow: true; start: number; end: number; thumbWidth: number; thumbOffset: number } | null {
  if (!width || !cell || count < 1 || scrollWidth <= width + 2) return null;
  const left = Math.abs(scrollLeft);
  const start = Math.min(count, Math.round(left / cell) + 1);
  const end = Math.min(count, start + Math.round(width / cell) - 1);
  return { overflow: true, start, end, thumbWidth: Math.min(1, width / scrollWidth), thumbOffset: left / width };
}
