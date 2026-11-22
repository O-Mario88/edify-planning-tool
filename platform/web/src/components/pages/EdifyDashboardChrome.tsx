'use client';

/*
 * Shared Edify dashboard visual primitives for rich oversight & workflow pages
 * (Escalations, Core School Oversight, Field Debrief, Personal Time Off,
 * Decision Log). Every surface, border, chart series and badge uses official
 * Edify brand CSS tokens (--brand-primary, --edify-navy-900, --edify-success,
 * --edify-warning, --edify-danger, --edify-purple, --edify-teal-600) so light
 * and dark themes stay consistent.
 */
import Link from 'next/link';
import type { ReactNode } from 'react';
import { ChevronRight, Home, Info } from 'lucide-react';

import type {
  PageAction,
  PageBlock,
  PageChart,
  PageFilters,
  PageForm,
  PageLinkTabs,
  PagePanel,
  PageSegments,
  PageStrip,
  PageTable,
} from '@/gen/edify/screens/v1/page_pb';

export type KpiTone = 'brand' | 'info' | 'success' | 'warning' | 'danger' | 'purple' | 'teal';

const KPI_STYLE: Readonly<
  Record<KpiTone, { card: string; iconBg: string; iconColor: string; bar: string; badge: string }>
> = {
  brand: {
    card: 'border-[color-mix(in_srgb,var(--brand-primary)_22%,var(--edify-border))] bg-[linear-gradient(135deg,color-mix(in_srgb,var(--brand-primary)_8%,var(--edify-card-surface)),color-mix(in_srgb,var(--edify-sky-400)_7%,var(--edify-card-surface)))]',
    iconBg: 'bg-[var(--brand-primary-soft)]',
    iconColor: 'text-[var(--brand-primary-text)] dark:text-[var(--edify-sky-400)]',
    bar: 'bg-[var(--brand-primary)]',
    badge: 'bg-[var(--brand-primary-soft)] text-[var(--brand-primary-text)]',
  },
  info: {
    card: 'border-[color-mix(in_srgb,var(--edify-info)_22%,var(--edify-border))] bg-[linear-gradient(135deg,color-mix(in_srgb,var(--edify-info)_8%,var(--edify-card-surface)),var(--edify-card-surface))]',
    iconBg: 'bg-[var(--edify-info-light)]',
    iconColor: 'text-[var(--edify-info-text)] dark:text-[var(--edify-sky-400)]',
    bar: 'bg-[var(--edify-info)]',
    badge: 'bg-[var(--edify-info-light)] text-[var(--edify-info-text)]',
  },
  success: {
    card: 'border-[color-mix(in_srgb,var(--edify-success)_26%,var(--edify-border))] bg-[linear-gradient(135deg,color-mix(in_srgb,var(--edify-success)_9%,var(--edify-card-surface)),var(--edify-card-surface))]',
    iconBg: 'bg-[var(--edify-success-light)]',
    iconColor: 'text-[var(--edify-success-text)]',
    bar: 'bg-[var(--edify-success)]',
    badge: 'bg-[var(--edify-success-light)] text-[var(--edify-success-text)]',
  },
  warning: {
    card: 'border-[color-mix(in_srgb,var(--edify-warning)_28%,var(--edify-border))] bg-[linear-gradient(135deg,color-mix(in_srgb,var(--edify-warning)_10%,var(--edify-card-surface)),var(--edify-card-surface))]',
    iconBg: 'bg-[var(--edify-warning-light)]',
    iconColor: 'text-[var(--edify-warning-text)]',
    bar: 'bg-[var(--edify-warning)]',
    badge: 'bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)]',
  },
  danger: {
    card: 'border-[color-mix(in_srgb,var(--edify-brand-secondary,#ef564b)_26%,var(--edify-border))] bg-[linear-gradient(135deg,color-mix(in_srgb,var(--edify-brand-secondary,#ef564b)_9%,var(--edify-card-surface)),var(--edify-card-surface))]',
    iconBg: 'bg-[var(--edify-danger-light)]',
    iconColor: 'text-[var(--edify-danger-text)]',
    bar: 'bg-[var(--edify-brand-secondary,#ef564b)]',
    badge: 'bg-[var(--edify-danger-light)] text-[var(--edify-danger-text)]',
  },
  purple: {
    card: 'border-[color-mix(in_srgb,var(--edify-purple)_25%,var(--edify-border))] bg-[linear-gradient(135deg,color-mix(in_srgb,var(--edify-purple)_9%,var(--edify-card-surface)),var(--edify-card-surface))]',
    iconBg: 'bg-[var(--edify-purple-light)]',
    iconColor: 'text-[var(--edify-purple-text)]',
    bar: 'bg-[var(--edify-purple)]',
    badge: 'bg-[var(--edify-purple-light)] text-[var(--edify-purple-text)]',
  },
  teal: {
    card: 'border-[color-mix(in_srgb,var(--edify-teal-600,#4e8ea2)_26%,var(--edify-border))] bg-[linear-gradient(135deg,color-mix(in_srgb,var(--edify-teal-600,#4e8ea2)_9%,var(--edify-card-surface)),var(--edify-card-surface))]',
    iconBg: 'bg-[color-mix(in_srgb,var(--edify-teal-600,#4e8ea2)_14%,var(--edify-surface))]',
    iconColor: 'text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-sky-400)]',
    bar: 'bg-[var(--edify-teal-600,#4e8ea2)]',
    badge: 'bg-[color-mix(in_srgb,var(--edify-teal-600,#4e8ea2)_14%,var(--edify-surface))] text-[var(--edify-navy-900,#073962)]',
  },
};

export const EDIFY_BTN_PRIMARY =
  'inline-flex items-center justify-center gap-2 rounded-[10px] bg-[var(--brand-primary)] px-4 py-2 text-[13px] font-semibold text-white shadow-sm transition-colors hover:bg-[var(--brand-primary-hover)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-primary)] disabled:opacity-50';

export const EDIFY_BTN_OUTLINE =
  'inline-flex items-center justify-center gap-2 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-3.5 py-2 text-[13px] font-semibold text-[var(--edify-text)] shadow-xs transition-colors hover:border-[var(--brand-primary-border)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-primary)]';

export function PageHeroHeader({
  eyebrow,
  title,
  description,
  icon,
  actions,
}: {
  readonly eyebrow: string;
  readonly title: string;
  readonly description?: string;
  readonly icon: ReactNode;
  readonly actions?: ReactNode;
}) {
  return (
    <header
      className="relative overflow-hidden rounded-[16px] border border-[color-mix(in_srgb,var(--brand-primary)_16%,var(--edify-border))] px-5 py-4 shadow-[var(--edify-shadow-xs)] sm:px-6 sm:py-5"
      style={{
        background:
          'linear-gradient(112deg, var(--edify-card-surface) 0%, color-mix(in srgb, var(--brand-primary) 5%, var(--edify-card-surface)) 58%, color-mix(in srgb, var(--edify-sky-400, #7bbde8) 16%, var(--edify-card-surface)) 100%)',
      }}
    >
      {/* Subtle Edify geometric wave accent on right */}
      <svg
        aria-hidden="true"
        viewBox="0 0 360 120"
        className="pointer-events-none absolute right-0 top-0 h-full w-[320px] opacity-35 dark:opacity-20"
        preserveAspectRatio="none"
      >
        <path
          d="M120 0 C180 40 240 20 360 0 L360 120 L40 120 C110 85 170 50 120 0 Z"
          fill="var(--brand-primary-soft)"
        />
        <path
          d="M200 0 C250 48 300 32 360 12 L360 120 L140 120 C210 78 240 42 200 0 Z"
          fill="var(--brand-primary)"
          fillOpacity="0.09"
        />
      </svg>

      <div className="relative flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 space-y-2">
          <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--edify-text-muted)]">
            <Link
              href="/home"
              className="inline-flex items-center text-[var(--brand-primary)] hover:underline dark:text-[var(--edify-sky-400)]"
              aria-label="Home"
            >
              <Home className="h-3.5 w-3.5" />
            </Link>
            <ChevronRight className="h-3 w-3 opacity-60" aria-hidden="true" />
            <span className="text-[var(--brand-primary-text)] dark:text-[var(--edify-sky-400)]">{eyebrow}</span>
            <ChevronRight className="h-3 w-3 opacity-60" aria-hidden="true" />
            <span className="font-semibold text-[var(--edify-text)]">{title}</span>
          </nav>

          <div className="flex items-start gap-3.5">
            <div
              className="grid h-11 w-11 shrink-0 place-items-center rounded-[12px] text-white shadow-sm"
              style={{
                background: 'linear-gradient(135deg, var(--edify-navy-900, #073962) 0%, var(--brand-primary, #0e5da3) 100%)',
              }}
              aria-hidden="true"
            >
              {icon}
            </div>
            <div className="min-w-0">
              <h1 className="text-[22px] font-extrabold leading-tight tracking-[-0.02em] text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)] sm:text-[24px]">
                {title}
              </h1>
              {description ? (
                <p className="mt-0.5 text-[13px] font-medium text-[var(--edify-text-muted)]">{description}</p>
              ) : null}
            </div>
          </div>
        </div>

        {actions ? <div className="relative flex shrink-0 flex-wrap items-center gap-2.5">{actions}</div> : null}
      </div>
    </header>
  );
}

export function KpiStatCard({
  label,
  value,
  helper,
  tone = 'brand',
  icon,
  info,
  href,
  progress,
  progressLabel,
  deltaBadge,
  watermark,
}: {
  readonly label: string;
  readonly value: string;
  readonly helper?: string;
  readonly tone?: KpiTone;
  readonly icon: ReactNode;
  readonly info?: string;
  readonly href?: string;
  readonly progress?: number;
  readonly progressLabel?: string;
  readonly deltaBadge?: string;
  readonly watermark?: ReactNode;
}) {
  const s = KPI_STYLE[tone];
  const inner = (
    <div
      className={`relative flex h-full flex-col justify-between overflow-hidden rounded-[14px] border p-4 shadow-[var(--edify-shadow-xs)] transition-shadow hover:shadow-[var(--edify-shadow-sm)] ${s.card}`}
    >
      {watermark ? (
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-1 right-2 opacity-[0.12] dark:opacity-[0.14]">
          {watermark}
        </div>
      ) : null}
      <div className="relative flex items-start justify-between gap-2">
        <div className="flex items-start gap-3">
          <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-[10px] ${s.iconBg} ${s.iconColor}`} aria-hidden="true">
            {icon}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-[22px] font-extrabold leading-none tracking-[-0.02em] tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                {value}
              </span>
              {deltaBadge ? (
                <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[11px] font-bold ${s.badge}`}>
                  {deltaBadge}
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-[13px] font-semibold text-[var(--edify-text)]">{label}</p>
            {helper ? <p className="mt-0.5 text-[11.5px] font-medium text-[var(--edify-text-muted)]">{helper}</p> : null}
          </div>
        </div>
        {info ? (
          <span
            title={info}
            aria-label={info}
            className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[var(--edify-text-muted)] opacity-70 hover:opacity-100"
          >
            <Info className="h-3.5 w-3.5" />
          </span>
        ) : null}
      </div>

      {typeof progress === 'number' ? (
        <div className="relative mt-3 flex items-center gap-2.5">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--edify-surface-muted)]">
            <div
              className={`h-full rounded-full transition-all ${s.bar}`}
              style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
            />
          </div>
          {progressLabel ? (
            <span className="shrink-0 text-[11px] font-semibold tabular-nums text-[var(--edify-text-muted)]">
              {progressLabel}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="block h-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-primary)]">
        {inner}
      </Link>
    );
  }
  return inner;
}

export interface DonutSlice {
  readonly label: string;
  readonly value: number;
  readonly color: string;
  readonly detail?: string;
}

export function DonutChart({
  slices,
  centerValue,
  centerLabel,
  size = 128,
  strokeWidth = 18,
}: {
  readonly slices: readonly DonutSlice[];
  readonly centerValue: string;
  readonly centerLabel: string;
  readonly size?: number;
  readonly strokeWidth?: number;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const total = slices.reduce((sum, s) => sum + Math.max(0, s.value), 0);

  let offset = 0;
  return (
    <div className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" role="img" aria-label={`${centerValue} ${centerLabel}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--edify-surface-muted)"
          strokeWidth={strokeWidth}
        />
        {total > 0
          ? slices
              .filter((s) => s.value > 0)
              .map((slice, idx) => {
                const frac = slice.value / total;
                const dash = frac * circumference;
                const gap = circumference - dash;
                const currentOffset = offset;
                offset += dash;
                return (
                  <circle
                    key={`${slice.label}-${idx}`}
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    stroke={slice.color}
                    strokeWidth={strokeWidth}
                    strokeDasharray={`${dash} ${gap}`}
                    strokeDashoffset={-currentOffset}
                    strokeLinecap="butt"
                  />
                );
              })
          : null}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="text-[20px] font-extrabold leading-tight tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
          {centerValue}
        </span>
        <span className="max-w-[78px] text-[10.5px] font-medium leading-tight text-[var(--edify-text-muted)]">
          {centerLabel}
        </span>
      </div>
    </div>
  );
}

export function AreaLineChart({
  labels,
  series,
  minY = 0,
  maxY,
  height = 148,
}: {
  readonly labels: readonly string[];
  readonly series: readonly { readonly name: string; readonly color: string; readonly values: readonly number[]; readonly fill?: boolean }[];
  readonly minY?: number;
  readonly maxY?: number;
  readonly height?: number;
}) {
  const width = 460;
  const padL = 32;
  const padR = 12;
  const padT = 12;
  const padB = 26;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const allVals = series.flatMap((s) => s.values);
  const computedMax = maxY ?? Math.max(5, ...allVals, minY + 1);
  const span = Math.max(1, computedMax - minY);

  const ticks = 5;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => minY + (span * i) / ticks);

  const count = Math.max(1, labels.length);
  const xOf = (idx: number) => (count === 1 ? padL + plotW / 2 : padL + (idx / (count - 1)) * plotW);
  const yOf = (val: number) => padT + plotH - ((Math.max(minY, Math.min(computedMax, val)) - minY) / span) * plotH;

  const labelStep = Math.max(1, Math.ceil(labels.length / 8));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full overflow-visible" role="img" aria-label="Trend chart">
      {yTicks.map((t, i) => {
        const y = yOf(t);
        return (
          <g key={i}>
            <line
              x1={padL}
              x2={width - padR}
              y1={y}
              y2={y}
              stroke="var(--edify-table-divider)"
              strokeDasharray={i === 0 ? undefined : '2 3'}
            />
            <text
              x={padL - 6}
              y={y + 3.5}
              textAnchor="end"
              fontSize="10"
              fill="var(--edify-text-muted)"
            >
              {Number.isInteger(t) ? t : t.toFixed(1)}
            </text>
          </g>
        );
      })}

      {series.map((s, si) => {
        if (!s.values.length) return null;
        const pts = s.values.map((v, i) => `${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join(' ');
        const areaPath =
          s.fill && s.values.length > 1
            ? `M ${xOf(0).toFixed(1)} ${yOf(s.values[0] ?? minY).toFixed(1)} ${s.values
                .map((v, i) => `L ${xOf(i).toFixed(1)} ${yOf(v).toFixed(1)}`)
                .join(' ')} L ${xOf(s.values.length - 1).toFixed(1)} ${(padT + plotH).toFixed(1)} L ${xOf(0).toFixed(1)} ${(padT + plotH).toFixed(1)} Z`
            : '';
        return (
          <g key={`${s.name}-${si}`}>
            {areaPath ? <path d={areaPath} fill={s.color} fillOpacity="0.14" /> : null}
            <polyline fill="none" stroke={s.color} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" points={pts} />
            {s.values.length <= 16
              ? s.values.map((v, i) => (
                  <circle
                    key={i}
                    cx={xOf(i)}
                    cy={yOf(v)}
                    r="3.2"
                    fill="var(--edify-card-surface)"
                    stroke={s.color}
                    strokeWidth="2"
                  />
                ))
              : null}
          </g>
        );
      })}

      {labels.map((lbl, i) =>
        (i % labelStep === 0 && (labels.length - 1 - i >= labelStep * 0.7 || i === labels.length - 1)) || i === labels.length - 1 ? (
          <text
            key={`${lbl}-${i}`}
            x={xOf(i)}
            y={height - 6}
            textAnchor="middle"
            fontSize="10"
            fill="var(--edify-text-muted)"
          >
            {lbl}
          </text>
        ) : null,
      )}
    </svg>
  );
}

export function MonthlyBarChart({
  labels,
  primary,
  secondary,
  primaryColor = 'var(--brand-primary)',
  secondaryColor = 'var(--edify-sky-400, #7bbde8)',
  height = 140,
}: {
  readonly labels: readonly string[];
  readonly primary: readonly number[];
  readonly secondary?: readonly number[];
  readonly primaryColor?: string;
  readonly secondaryColor?: string;
  readonly height?: number;
}) {
  const width = 340;
  const padL = 26;
  const padR = 8;
  const padT = 10;
  const padB = 22;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const maxVal = Math.max(5, ...primary, ...(secondary ?? []));
  const top = Math.ceil(maxVal / 5) * 5;
  const yTicks = [0, Math.round(top * 0.25), Math.round(top * 0.5), Math.round(top * 0.75), top];
  const slotW = plotW / Math.max(1, labels.length);
  const barW = Math.max(6, Math.min(13, slotW * 0.56));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label="Monthly usage chart">
      {yTicks.map((t, i) => {
        const y = padT + plotH - (t / Math.max(1, top)) * plotH;
        return (
          <g key={i}>
            <line x1={padL} x2={width - padR} y1={y} y2={y} stroke="var(--edify-table-divider)" strokeDasharray={i === 0 ? undefined : '2 3'} />
            <text x={padL - 5} y={y + 3.5} textAnchor="end" fontSize="9.5" fill="var(--edify-text-muted)">
              {t}
            </text>
          </g>
        );
      })}
      {labels.map((lbl, i) => {
        const cx = padL + i * slotW + slotW / 2;
        const pVal = primary[i] ?? 0;
        const sVal = secondary?.[i] ?? 0;
        const pH = (pVal / Math.max(1, top)) * plotH;
        const sH = (sVal / Math.max(1, top)) * plotH;
        return (
          <g key={lbl}>
            {sH > 0 ? (
              <rect
                x={cx - barW / 2}
                y={padT + plotH - pH - sH}
                width={barW}
                height={sH}
                rx="2.5"
                fill={secondaryColor}
              />
            ) : null}
            {pH > 0 ? (
              <rect
                x={cx - barW / 2}
                y={padT + plotH - pH}
                width={barW}
                height={pH}
                rx="2.5"
                fill={primaryColor}
              />
            ) : null}
            <text x={cx} y={height - 6} textAnchor="middle" fontSize="9.5" fill="var(--edify-text-muted)">
              {lbl}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function EdifyClipboardIllustration({ badge = 'upload' }: { readonly badge?: 'upload' | 'check' | 'empty' }) {
  return (
    <svg viewBox="0 0 112 88" className="h-[74px] w-[96px] shrink-0" aria-hidden="true">
      <ellipse cx="52" cy="76" rx="40" ry="8" fill="var(--brand-primary)" fillOpacity="0.1" />
      <path
        d="M22 68 C16 68 12 63 14 57 C16 51 22 50 26 51 C29 44 38 41 46 44 C52 38 66 39 70 48 C77 48 82 54 81 61 C80 66 75 68 70 68 Z"
        fill="var(--brand-primary-soft)"
      />
      <rect x="26" y="14" width="48" height="58" rx="8" fill="var(--edify-card-surface)" stroke="var(--brand-primary-border)" strokeWidth="2" />
      <rect x="38" y="9" width="24" height="10" rx="4" fill="var(--brand-primary)" />
      <rect x="35" y="29" width="30" height="4" rx="2" fill="var(--brand-primary-border)" />
      <rect x="35" y="40" width="24" height="4" rx="2" fill="var(--edify-sky-100, #bdd8e9)" />
      <rect x="35" y="51" width="28" height="4" rx="2" fill="var(--edify-sky-100, #bdd8e9)" />
      {badge === 'upload' ? (
        <>
          <circle cx="76" cy="54" r="15" fill="var(--brand-primary)" />
          <path d="M76 61 V47 M70 53 L76 47 L82 53" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </>
      ) : badge === 'check' ? (
        <>
          <circle cx="76" cy="56" r="13" fill="var(--brand-primary)" />
          <path d="M70 56 L74 60 L82 51" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </>
      ) : null}
    </svg>
  );
}

export function EmptyStatePanel({
  title,
  description,
  action,
  icon = 'clipboard',
}: {
  readonly title: string;
  readonly description?: string;
  readonly action?: ReactNode;
  readonly icon?: 'clipboard' | 'calendar';
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icon === 'calendar' ? (
        <svg viewBox="0 0 84 72" className="mb-3 h-16 w-20" aria-hidden="true">
          <ellipse cx="42" cy="64" rx="28" ry="6" fill="var(--brand-primary)" fillOpacity="0.1" />
          <rect x="16" y="14" width="52" height="44" rx="8" fill="var(--edify-card-surface)" stroke="var(--brand-primary-border)" strokeWidth="2" />
          <path d="M16 26 H68" stroke="var(--brand-primary-border)" strokeWidth="2" />
          <rect x="16" y="14" width="52" height="12" rx="6" fill="var(--brand-primary-soft)" />
          <path d="M34 42 L40 48 L51 36" stroke="var(--brand-primary)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
      ) : (
        <EdifyClipboardIllustration badge="empty" />
      )}
      <h3 className="mt-2 text-[16px] font-bold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">{title}</h3>
      {description ? <p className="mt-1 max-w-md text-[13px] text-[var(--edify-text-muted)]">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

/* ── Block extraction helpers for GetPageResponse ─────────────────────── */

export function findFilters(blocks: readonly PageBlock[]): PageFilters | undefined {
  for (const b of blocks) if (b.kind.case === 'filters') return b.kind.value;
  return undefined;
}

export function findAllStrips(blocks: readonly PageBlock[]): PageStrip[] {
  const out: PageStrip[] = [];
  for (const b of blocks) if (b.kind.case === 'strip') out.push(b.kind.value);
  return out;
}

export function findAllLinkTabs(blocks: readonly PageBlock[]): PageLinkTabs[] {
  const out: PageLinkTabs[] = [];
  for (const b of blocks) if (b.kind.case === 'linkTabs') out.push(b.kind.value);
  return out;
}

export function findAllTables(blocks: readonly PageBlock[]): PageTable[] {
  const out: PageTable[] = [];
  for (const b of blocks) if (b.kind.case === 'table') out.push(b.kind.value);
  return out;
}

export function findAllPanels(blocks: readonly PageBlock[]): PagePanel[] {
  const out: PagePanel[] = [];
  for (const b of blocks) if (b.kind.case === 'panel') out.push(b.kind.value);
  return out;
}

export function findAllCharts(blocks: readonly PageBlock[]): PageChart[] {
  const out: PageChart[] = [];
  for (const b of blocks) if (b.kind.case === 'chart') out.push(b.kind.value);
  return out;
}

export function findAllSegments(blocks: readonly PageBlock[]): PageSegments[] {
  const out: PageSegments[] = [];
  for (const b of blocks) if (b.kind.case === 'segments') out.push(b.kind.value);
  return out;
}

export function findForm(blocks: readonly PageBlock[]): PageForm | undefined {
  for (const b of blocks) if (b.kind.case === 'form') return b.kind.value;
  return undefined;
}

export function parseLeadingNumber(text: string): number {
  const m = text.replace(/,/g, '').match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : 0;
}

export function resolveSafeHref(pagePath: string, href: string): string {
  const value = href.trim();
  if (!value) return '';
  if (value.startsWith('?')) return `${pagePath}${value}`;
  if (value.startsWith('#')) return value;
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return '';
  return value;
}

export function resolveActionHref(action: PageAction, pagePath: string, drawerHref: string): string {
  if (action.drawer) return drawerHref;
  return resolveSafeHref(pagePath, action.href) || drawerHref;
}
