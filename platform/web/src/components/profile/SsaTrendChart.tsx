/*
 * A school's confirmed SSA average by year, on the SSA's own 0 to 10 scale.
 * One series, so the card's title names it and no legend is drawn. A year
 * with no reading is absent from the points, never a zero on the line.
 */
import type { TrendPoint } from '@/lib/schoolProfileView';

const WIDTH = 360;
const HEIGHT = 190;
const PLOT = { left: 26, right: 20, top: 26, bottom: 30 } as const;
const SCALE_MAX = 10;
const TICKS = [0, 2, 4, 6, 8, 10] as const;

const yOf = (value: number) => PLOT.top + (1 - value / SCALE_MAX) * (HEIGHT - PLOT.top - PLOT.bottom);

function xOf(index: number, count: number): number {
  const span = WIDTH - PLOT.left - PLOT.right;
  return count === 1 ? PLOT.left + span / 2 : PLOT.left + (index / (count - 1)) * span;
}

export function SsaTrendChart({ points }: { points: readonly TrendPoint[] }) {
  if (!points.length) {
    return <p className="py-10 text-center text-[13px] text-[var(--edify-text-muted)]">No confirmed SSA score yet.</p>;
  }
  const placed = points.map((point, index) => ({ ...point, x: xOf(index, points.length), y: yOf(point.value) }));
  const line = placed.map((point) => `${point.x},${point.y}`).join(' ');
  const first = placed[0]!;
  const last = placed[placed.length - 1]!;
  const area = `${first.x},${yOf(0)} ${line} ${last.x},${yOf(0)}`;
  const summary = points.map((point) => `${point.label}: ${point.value.toFixed(2)}`).join(', ');
  const calloutX = Math.min(Math.max(last.x - 20, 0), WIDTH - 40);
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`SSA score by year. ${summary}`} className="block h-auto w-full" data-chart="ssa-trend">
      <defs>
        <linearGradient id="ssa-trend-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--brand-primary)" stopOpacity="0.18" />
          <stop offset="100%" stopColor="var(--brand-primary)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {TICKS.map((tick) => (
        <g key={tick}>
          <line x1={PLOT.left} x2={WIDTH - PLOT.right + 8} y1={yOf(tick)} y2={yOf(tick)} stroke="var(--edify-border)" strokeWidth="1" />
          <text x={PLOT.left - 6} y={yOf(tick) + 3.5} textAnchor="end" fontSize="10" fill="var(--edify-text-muted)">{tick}</text>
        </g>
      ))}
      {placed.length > 1 ? <polygon points={area} fill="url(#ssa-trend-fill)" /> : null}
      {placed.length > 1 ? <polyline points={line} fill="none" stroke="var(--brand-primary)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" /> : null}
      {placed.map((point, index) => {
        const isLast = index === placed.length - 1;
        return (
          <g key={point.label}>
            <title>{`${point.label}: ${point.value.toFixed(2)}`}</title>
            <circle cx={point.x} cy={point.y} r="10" fill="transparent" />
            <circle cx={point.x} cy={point.y} r="4" fill="var(--edify-surface)" stroke="var(--brand-primary)" strokeWidth="2" />
            {isLast ? null : (
              <text x={index === 0 ? point.x + 2 : point.x} y={point.y - 9} textAnchor={index === 0 ? 'start' : 'middle'} fontSize="11" fontWeight="600" fill="var(--edify-text)">{point.value.toFixed(2)}</text>
            )}
            <text x={point.x} y={HEIGHT - 10} textAnchor={index === 0 && placed.length > 1 ? 'start' : isLast && placed.length > 1 ? 'end' : 'middle'} fontSize="10" fill="var(--edify-text-muted)">
              {point.label}
            </text>
          </g>
        );
      })}
      <g>
        <rect x={calloutX} y={Math.max(last.y - 28, 2)} width="40" height="18" rx="4" fill="var(--brand-primary)" />
        <text x={calloutX + 20} y={Math.max(last.y - 28, 2) + 13} textAnchor="middle" fontSize="11" fontWeight="700" fill="#ffffff">{last.value.toFixed(2)}</text>
      </g>
    </svg>
  );
}
