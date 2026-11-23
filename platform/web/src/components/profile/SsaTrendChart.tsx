/*
 * A school's confirmed SSA average by year, on the SSA's own 0 to 10 scale.
 * One series, so the card's title names it and no legend is drawn. A year
 * with no reading is absent from the points, never a zero on the line.
 */
import type { TrendPoint } from '@/lib/schoolProfileView';

interface Frame {
  readonly size: 'wide' | 'narrow';
  readonly width: number;
  readonly height: number;
  readonly left: number;
  readonly right: number;
  readonly top: number;
  readonly bottom: number;
  readonly text: number;
}

/** The wide drawing, and the small one a phone sets beside the GPS card. */
const WIDE: Frame = { size: 'wide', width: 430, height: 156, left: 26, right: 20, top: 24, bottom: 24, text: 10 };
const NARROW: Frame = { size: 'narrow', width: 190, height: 136, left: 16, right: 8, top: 22, bottom: 30, text: 8.5 };
/** Five gridline steps on either scale: 0 to 10 for a score, 0 to 100 for a share. */
const STEPS = [0, 0.2, 0.4, 0.6, 0.8, 1] as const;

function xOf(frame: Frame, index: number, count: number): number {
  const span = frame.width - frame.left - frame.right;
  return count === 1 ? frame.left + span / 2 : frame.left + (index / (count - 1)) * span;
}

interface TrendChartProps {
  readonly points: readonly TrendPoint[];
  /** The top of the scale: 10 for an SSA score, 100 for a share. */
  readonly scaleMax?: number;
  /** Written after each value ("%"). */
  readonly suffix?: string;
  /** What the chart says when there is nothing to draw. */
  readonly empty?: string;
  readonly label?: string;
}

export function SsaTrendChart({ points, scaleMax = 10, suffix = '', empty = 'No confirmed SSA score yet.', label = 'SSA score by year' }: TrendChartProps) {
  if (!points.length) {
    return <p className="py-10 text-center text-[13px] text-[var(--edify-text-muted)]">{empty}</p>;
  }
  const written = (value: number) => (suffix ? `${Math.round(value)}${suffix}` : value.toFixed(2));
  const summary = points.map((point) => `${point.label}: ${written(point.value)}`).join(', ');
  const draw = (frame: Frame) => {
  const { width: WIDTH, height: HEIGHT, left, right, text: fontSize, size } = frame;
  const yOf = (value: number) => frame.top + (1 - value / scaleMax) * (HEIGHT - frame.top - frame.bottom);
  const placed = points.map((point, index) => ({ ...point, x: xOf(frame, index, points.length), y: yOf(point.value) }));
  const fillId = `ssa-trend-fill-${size}`;
  const line = placed.map((point) => `${point.x},${point.y}`).join(' ');
  const first = placed[0]!;
  const last = placed[placed.length - 1]!;
  const area = `${first.x},${yOf(0)} ${line} ${last.x},${yOf(0)}`;
  const calloutX = Math.min(Math.max(last.x - 20, 0), WIDTH - 40);
  return (
    <svg key={size} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`${label}. ${summary}`} className="h-auto w-full" data-chart="ssa-trend" data-chart-size={size}>
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--brand-primary)" stopOpacity="0.18" />
          <stop offset="100%" stopColor="var(--brand-primary)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {STEPS.map((step) => {
        const tick = step * scaleMax;
        return (
          <g key={step}>
            <line x1={left} x2={WIDTH - right + 6} y1={yOf(tick)} y2={yOf(tick)} stroke="var(--edify-border)" strokeWidth="1" />
            <text x={left - 5} y={yOf(tick) + 3} textAnchor="end" fontSize={fontSize} fill="var(--edify-text-muted)">{tick}</text>
          </g>
        );
      })}
      {placed.length > 1 ? <polygon points={area} fill={`url(#${fillId})`} /> : null}
      {placed.length > 1 ? <polyline points={line} fill="none" stroke="var(--brand-primary)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" /> : null}
      {placed.map((point, index) => {
        const isLast = index === placed.length - 1;
        return (
          <g key={point.label}>
            <title>{`${point.label}: ${written(point.value)}`}</title>
            <circle cx={point.x} cy={point.y} r="10" fill="transparent" />
            <circle cx={point.x} cy={point.y} r="4" fill="var(--edify-surface)" stroke="var(--brand-primary)" strokeWidth="2" />
            {isLast ? null : (
              <text x={index === 0 ? point.x + 2 : point.x} y={point.y - 9} textAnchor={index === 0 ? 'start' : 'middle'} fontSize={fontSize + 1} fontWeight="600" fill="var(--edify-text)">{written(point.value)}</text>
            )}
            <text x={point.x} y={HEIGHT - (size === 'narrow' ? 16 : 8)} textAnchor={index === 0 && placed.length > 1 ? 'start' : isLast && placed.length > 1 ? 'end' : 'middle'} fontSize={fontSize} fill="var(--edify-text-muted)">
              {size === 'narrow' ? (
                <>
                  <tspan x={point.x}>{point.label.split(' ')[0]}</tspan>
                  <tspan x={point.x} dy={fontSize + 1}>{point.label.split(' ').slice(1).join(' ')}</tspan>
                </>
              ) : point.label}
            </text>
          </g>
        );
      })}
      <g>
        <rect x={calloutX} y={Math.max(last.y - 28, 2)} width="40" height="18" rx="4" fill="var(--brand-primary)" />
        <text x={calloutX + 20} y={Math.max(last.y - 28, 2) + 13} textAnchor="middle" fontSize="11" fontWeight="700" fill="#ffffff">{written(last.value)}</text>
      </g>
    </svg>
  );
  };
  return (
    <>
      {draw(WIDE)}
      {draw(NARROW)}
    </>
  );
}
