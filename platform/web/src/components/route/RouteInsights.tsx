/*
 * The Smart Route Planner's summary cards: the six figures over the page,
 * the SSA & Coverage tab, and the row under the map (route options, what the
 * optimizer found, what was reported on the road). Every figure is Go's.
 */
import { BarChart3, CheckCircle2, CircleX, Clock, Flag, Gauge, Hourglass, Info, MapPinned, Route, ShieldCheck, Sparkles, TrafficCone, TriangleAlert, Zap } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { hoursMinutes, km } from '@/lib/routePlanner';
import type { SmartOptimizationMode, SmartRouteResultData } from '@/lib/routePlanner';
import { rankOptions, roadSummary, routeInsights, routeKpis, ssaCoverage } from '@/lib/routeView';
import type { RouteOption } from '@/lib/routeView';

const KPI_ICONS: Readonly<Record<string, LucideIcon>> = {
  schools: CheckCircle2,
  distance: Route,
  driving: Clock,
  field: Gauge,
  coverage: ShieldCheck,
  traffic: TrafficCone,
};

export function RouteKpiStrip({ result, plannedStops }: { result: SmartRouteResultData | null; plannedStops: number }) {
  return (
    <section className="sr-kpis" aria-label="Route figures" tabIndex={0}>
      {routeKpis(result, plannedStops).map((kpi) => {
        const KpiIcon = KPI_ICONS[kpi.key] ?? Route;
        return (
          <div key={kpi.key} className="sr-kpi" data-kpi={kpi.key}>
            <span className="sr-kpi__icon"><KpiIcon className="h-5 w-5" aria-hidden="true" /></span>
            <div className="min-w-0">
              <p className="sr-kpi__value">{kpi.value}</p>
              <p className="sr-kpi__label">
                {kpi.label.includes(' Road ') ? (
                  <>
                    <span className="sr-long">{kpi.label}</span>
                    <span className="sr-short">{kpi.label.replace(' Road ', ' ')}</span>
                  </>
                ) : kpi.label}
              </p>
              {kpi.note ? <p className="sr-kpi__note">{kpi.note}</p> : null}
            </div>
          </div>
        );
      })}
    </section>
  );
}

const BAND_WORDS: readonly (readonly [string, string])[] = [
  ['critical', 'Critical SSA'],
  ['high', 'High SSA need'],
  ['missing_ssa', 'SSA needed'],
  ['core', 'Core school'],
  ['routine', 'Routine'],
];

export function RouteSsaTab({ result }: { result: SmartRouteResultData | null }) {
  if (!result || (!result.stops.length && !result.excluded.length)) {
    return <p className="rounded-[12px] border border-dashed border-[var(--edify-border)] py-8 text-center text-[13px] text-[var(--edify-text-muted)]">No schools on this route yet.</p>;
  }
  const coverage = ssaCoverage(result);
  const inBand = (band: string) => result.stops.filter((stop) => (stop.priority?.band ?? 'routine') === band).length;
  const leftOut = (band: string) => result.excluded.filter((school) => (school.priority?.band ?? 'routine') === band).length;
  return (
    <div className="space-y-3 text-[13px]" data-block="ssa-coverage">
      <div className="rounded-[12px] border border-[var(--edify-border)] p-3">
        <p className="text-[12px] font-semibold text-[var(--edify-text-muted)]">SSA Priority Coverage</p>
        <p className="text-[22px] font-bold text-[var(--edify-text)]">{coverage.percent === null ? '—' : `${coverage.percent}%`}</p>
        <p className="text-[12px] text-[var(--edify-text-muted)]">{coverage.total ? `${coverage.reached} of ${coverage.total} priority schools on this route` : 'No priority schools on this day'}</p>
      </div>
      <table className="w-full text-left">
        <caption className="sr-only">Schools by SSA priority</caption>
        <thead>
          <tr className="text-[12px] text-[var(--edify-text-muted)]">
            <th scope="col" className="py-1 font-semibold">Priority</th>
            <th scope="col" className="py-1 text-right font-semibold">On route</th>
            <th scope="col" className="py-1 text-right font-semibold">Left out</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--edify-border)]">
          {BAND_WORDS.map(([band, words]) => (
            <tr key={band}>
              <th scope="row" className="py-1.5 font-medium text-[var(--edify-text)]">{words}</th>
              <td className="py-1.5 text-right font-semibold tabular-nums">{inBand(band)}</td>
              <td className="py-1.5 text-right tabular-nums">{leftOut(band)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="space-y-1.5">
        {result.stops.map((stop) => (
          <li key={stop.school_id} className="rounded-[8px] bg-[var(--edify-surface-muted)] px-2.5 py-1.5">
            <p className="font-semibold text-[var(--edify-text)]">{stop.order}. {stop.school_name}</p>
            <p className="text-[12px] text-[var(--edify-text-muted)]">{stop.priority?.reason || 'Routine visit'}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface RouteBottomRowProps {
  readonly result: SmartRouteResultData | null;
  readonly options: readonly RouteOption[];
  readonly comparing: boolean;
  readonly canCompare: boolean;
  readonly activeMode: SmartOptimizationMode;
  readonly onCompare: () => void;
  readonly onUse: (mode: SmartOptimizationMode) => void;
  /** How many road reports are open, and the door to file one. */
  readonly reportCount: number;
  readonly onReport: () => void;
}

const OPTION_ICONS: Partial<Record<SmartOptimizationMode, LucideIcon>> = { balanced: Sparkles, fastest: Zap, shortest: Route };

function BottomCard({ title, icon: CardIcon, children }: { title: string; icon: LucideIcon; children: ReactNode }) {
  return (
    <section className="sr-card" aria-label={title}>
      <h2 className="mb-2 flex items-center gap-2 text-[15px] font-bold text-[var(--edify-text)]">
        <CardIcon className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" /> {title}
      </h2>
      {children}
    </section>
  );
}

export function RouteBottomRow({ result, options, comparing, canCompare, activeMode, onCompare, onUse, reportCount, onReport }: RouteBottomRowProps) {
  const ranked = rankOptions(options);
  const insights = routeInsights(result);
  const road = roadSummary(result?.road_alerts ?? []);
  const rows: readonly (readonly [string, number, LucideIcon])[] = [['Closed', road.closed, CircleX], ['Delays', road.delay, Hourglass], ['Advisories', road.advisory, TriangleAlert]];
  return (
    <div className="sr-bottom">
      <BottomCard title="Route Options" icon={MapPinned}>
        {ranked.length ? (
          <div className="sr-options">
            {ranked.map((option) => {
              const isActive = option.mode === activeMode;
              const OptionIcon = OPTION_ICONS[option.mode] ?? Route;
              return (
                <button key={option.mode} type="button" onClick={() => onUse(option.mode)} aria-pressed={isActive} className="sr-option" data-active={isActive || undefined}>
                  <span className="sr-option__head">
                    <OptionIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
                    <strong>{option.recommended ? `Recommended (${option.label})` : option.label}</strong>
                    {isActive ? <CheckCircle2 className="ml-auto h-4 w-4 shrink-0" aria-hidden="true" /> : null}
                  </span>
                  <span className="sr-option__road">
                    {option.roadComplete ? `${km(option.meters)} • ${hoursMinutes(option.seconds)}` : 'Road figures unconfirmed'}
                  </span>
                  <span className="sr-option__chips">
                    <span data-tone="good"><ShieldCheck className="h-3 w-3" aria-hidden="true" /> {option.included} school{option.included === 1 ? '' : 's'} · {option.coverage}</span>
                    <span data-tone="plain"><TrafficCone className="h-3 w-3" aria-hidden="true" /> Traffic: {option.traffic}</span>
                    {option.badges.length ? <span data-tone="good">{option.badges.join(' · ')}</span> : null}
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="mb-2 text-[13px] text-[var(--edify-text-muted)]">Compare the balanced, fastest and shortest orders of this day&apos;s schools, from real road figures.</p>
        )}
        <button type="button" onClick={onCompare} disabled={!canCompare || comparing} className="mt-2 inline-flex h-9 items-center gap-1.5 rounded-[8px] border border-[var(--brand-primary)] px-3 text-[13px] font-semibold text-[var(--brand-primary)] disabled:opacity-45">
          <BarChart3 className="h-4 w-4" aria-hidden="true" /> {comparing ? 'Comparing…' : ranked.length ? 'Compare Again' : 'Compare Route Options'}
        </button>
      </BottomCard>
      <BottomCard title="Optimization Insights" icon={Sparkles}>
        {insights.length ? (
          <ul className="space-y-1.5 text-[13px] text-[var(--edify-text)]">
            {insights.map((line) => (
              <li key={line} className="flex items-start gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--edify-success-text)]" aria-hidden="true" /><span>{line}</span></li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-[var(--edify-text-muted)]">Optimize a route to see what was found.</p>
        )}
      </BottomCard>
      <BottomCard title="Road Conditions" icon={TriangleAlert}>
        <dl className="divide-y divide-[var(--edify-border)] text-[13px]">
          {rows.map(([label, count, RowIcon]) => (
            <div key={label} className="flex items-center gap-2 py-1">
              <RowIcon className="h-4 w-4 shrink-0 text-[var(--edify-text-muted)]" aria-hidden="true" />
              <dt className="flex-1 text-[var(--edify-text)]">{label}</dt>
              <dd className="font-semibold tabular-nums">{count} report{count === 1 ? '' : 's'}</dd>
            </div>
          ))}
        </dl>
        {road.unverified ? <p className="mt-1 text-[12px] text-[var(--edify-text-muted)]">{road.unverified} unverified staff report{road.unverified === 1 ? '' : 's'}.</p> : null}
        {road.total ? null : <p className="mt-1 flex items-start gap-1.5 text-[11.5px] text-[var(--edify-text-muted)]"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /> Distances by condition need a live road provider.</p>}
        <button type="button" onClick={onReport} className="mt-2 inline-flex h-8 items-center gap-1.5 rounded-[7px] border border-[var(--edify-border)] px-2.5 text-[12px] font-semibold text-[var(--edify-text)] hover:border-[var(--brand-primary)]">
          <Flag className="h-3.5 w-3.5" aria-hidden="true" /> Report Road Condition ({reportCount})
        </button>
      </BottomCard>
    </div>
  );
}
