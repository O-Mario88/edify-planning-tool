/**
 * The Edify Enterprise Design System (docs/migration/177 Stage B): the
 * components the redesigned screens are built from, drawn only with the
 * design system's tokens (platform/design/tokens.json, as --ds-* variables
 * and Tailwind's ds- utilities). Distinct from components/ds, which draws the
 * live system's own markup for the pages kept at parity until each is
 * redesigned.
 *
 * Every interactive part is at least the 44px target; numbers are tabular;
 * colour never carries meaning alone (a status always has its words).
 */
import type { ReactNode } from 'react';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

const TONE: Record<Tone, string> = {
  neutral: 'bg-ds-surface-sunken text-ds-text-muted border-ds-border',
  info: 'bg-ds-info-soft text-ds-info border-ds-info-border',
  success: 'bg-ds-success-soft text-ds-success border-ds-success-border',
  warning: 'bg-ds-warning-soft text-ds-warning border-ds-warning-border',
  danger: 'bg-ds-danger-soft text-ds-danger border-ds-danger-border',
};

/** A status in words, toned: "Overdue", "Waiting on you". */
export function StatusBadge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-ds-pill border px-2 text-ds-caption font-semibold whitespace-nowrap ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}

const BUTTON = {
  primary: 'bg-ds-primary text-ds-primary-ink hover:bg-ds-primary-hover',
  secondary: 'bg-ds-surface text-ds-text border border-ds-border-strong hover:bg-ds-surface-sunken',
  ghost: 'text-ds-primary hover:bg-ds-primary-soft',
};

/** A button or a link drawn as one, at least the 44px target tall. */
export function Button({
  kind = 'primary',
  href,
  children,
  wide = false,
}: {
  kind?: keyof typeof BUTTON;
  href?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const className =
    `inline-flex min-h-[var(--ds-target)] items-center justify-center gap-2 rounded-ds-md px-4 text-ds-control ` +
    `font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ds-focus ${BUTTON[kind]}` +
    (wide ? ' w-full' : '');
  return href ? (
    <a className={className} href={href}>
      {children}
    </a>
  ) : (
    <button type="button" className={className}>
      {children}
    </button>
  );
}

/** A section's heading, with a count and a link to the whole list. */
export function SectionHeader({ title, count, href, linkLabel }: { title: string; count?: number; href?: string; linkLabel?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-1">
      <h2 className="text-ds-lead font-bold text-ds-text">
        {title}
        {count !== undefined ? <span className="ml-2 tabular-nums text-ds-text-subtle font-semibold">{count}</span> : null}
      </h2>
      {href ? (
        <a className="text-ds-body font-semibold text-ds-primary underline-offset-4 hover:underline" href={href}>
          {linkLabel ?? 'View all'}
        </a>
      ) : null}
    </div>
  );
}

/** A raised surface. */
export function Surface({ children, padded = true }: { children: ReactNode; padded?: boolean }) {
  return (
    <section className={`rounded-ds-lg border border-ds-border bg-ds-surface shadow-ds-raised ${padded ? 'p-4' : ''}`}>
      {children}
    </section>
  );
}

/** One figure with what it counts, and its share of a target when it has one. */
export function KpiStat({ label, value, of, hint }: { label: string; value: number; of?: number; hint?: string }) {
  const share = of ? Math.round((value / of) * 100) : null;
  return (
    <div className="min-w-0">
      <p className="text-ds-caption font-semibold text-ds-text-subtle">{label}</p>
      <p className="mt-1 text-ds-figure font-bold tabular-nums text-ds-text">
        {value.toLocaleString('en-UG')}
        {of ? <span className="text-ds-body font-semibold text-ds-text-subtle"> / {of.toLocaleString('en-UG')}</span> : null}
      </p>
      {share !== null ? (
        <div className="mt-2 h-1.5 rounded-ds-pill bg-ds-surface-sunken" role="img" aria-label={`${share}% of target`}>
          <div className="h-1.5 rounded-ds-pill bg-ds-primary" style={{ width: `${Math.min(share, 100)}%` }} />
        </div>
      ) : null}
      {hint ? <p className="mt-1 text-ds-caption text-ds-text-subtle">{hint}</p> : null}
    </div>
  );
}

/** A task: what it is, where, its state, and the one thing to do about it. */
export function TaskRow({
  title,
  context,
  status,
  tone = 'neutral',
  action,
  href,
}: {
  title: string;
  context: string;
  status?: string;
  tone?: Tone;
  action: string;
  href: string;
}) {
  return (
    <li>
      <a
        href={href}
        className="flex min-h-[var(--ds-target)] items-center gap-3 px-4 py-3 hover:bg-ds-surface-sunken focus-visible:outline-2 focus-visible:outline-ds-focus"
      >
        <div className="min-w-0 flex-1">
          <p className="text-ds-body font-semibold text-ds-text">{title}</p>
          <p className="mt-0.5 text-ds-caption text-ds-text-subtle">{context}</p>
          {status ? (
            <p className="mt-1.5">
              <StatusBadge tone={tone}>{status}</StatusBadge>
            </p>
          ) : null}
        </div>
        <span className="shrink-0 text-ds-body font-semibold text-ds-primary">{action}</span>
      </a>
    </li>
  );
}

/** A list of tasks on one surface, divided. */
export function TaskList({ children }: { children: ReactNode }) {
  return (
    <ul className="divide-y divide-ds-border overflow-hidden rounded-ds-lg border border-ds-border bg-ds-surface shadow-ds-raised">
      {children}
    </ul>
  );
}

/** What an empty list says, and what to do instead. */
export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="rounded-ds-lg border border-dashed border-ds-border-strong bg-ds-surface px-4 py-6 text-center">
      <p className="text-ds-body font-bold text-ds-text">{title}</p>
      <p className="mt-1 text-ds-caption text-ds-text-subtle">{body}</p>
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

/** A placeholder the size of what loads into it. */
export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="h-4 animate-pulse rounded-ds-sm bg-ds-surface-sunken" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}

/** Two or three choices that switch a view in place. */
export function Segmented({ items, active }: { items: string[]; active: string }) {
  return (
    <div className="grid rounded-ds-md border border-ds-border bg-ds-surface-sunken p-1" style={{ gridTemplateColumns: `repeat(${items.length}, 1fr)` }} role="tablist">
      {items.map((item) => (
        <span
          key={item}
          role="tab"
          aria-selected={item === active}
          className={`flex min-h-[36px] items-center justify-center rounded-ds-sm text-ds-body font-semibold ${
            item === active ? 'bg-ds-surface text-ds-text shadow-ds-raised' : 'text-ds-text-subtle'
          }`}
        >
          {item}
        </span>
      ))}
    </div>
  );
}
