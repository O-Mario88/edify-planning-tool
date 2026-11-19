/*
 * The design system's progress meter (templates/components/meter.html): a
 * track with the planned share under the done share, the figure beside it
 * and a line under it, toned by how it stands.
 */
import type { CSSProperties } from 'react';

export interface MeterProps {
  /** Done, 0 to 100; null when nothing is measured. */
  readonly done: number | null;
  /** Planned, 0 to 100, drawn under done. */
  readonly planned?: number | null;
  /** The figure beside the track ("62%"). */
  readonly value: string;
  /** The line under it ("12 done · 7 planned · of 20 visits"). */
  readonly meta?: string;
  /** success, warning or danger. */
  readonly tone?: string;
  /** What a screen reader hears. */
  readonly label: string;
}

const width = (value: number): CSSProperties => ({ inlineSize: `${Math.max(0, Math.min(100, value))}%` });

export function Meter({ done, planned = null, value, meta, tone, label }: MeterProps) {
  return (
    <div className="edify-meter" data-tone={tone || undefined} role="img" aria-label={label}>
      <span className="edify-meter__track" aria-hidden="true">
        {planned !== null ? <span className="edify-meter__planned" style={width(Math.max(planned, done ?? 0))} /> : null}
        {done !== null ? <span className="edify-meter__done" style={width(done)} /> : null}
      </span>
      <span className="edify-meter__value">{value}</span>
      {meta ? <span className="edify-meter__meta">{meta}</span> : null}
    </div>
  );
}

/** A small figure tile (the dashboards' .admin-mini): label, figure, line under it, toned. */
export function MiniTile({ label, value, helper, tone }: { label: string; value: string; helper?: string; tone?: string }) {
  return (
    <article className="admin-mini" data-tone={tone || undefined}>
      <span>{label}</span>
      <strong>{value}</strong>
      {helper ? <small>{helper}</small> : null}
    </article>
  );
}
