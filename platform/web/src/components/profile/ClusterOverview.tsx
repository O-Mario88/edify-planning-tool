/*
 * The Cluster Profile's Overview cards: SSA over the assessed schools, its
 * histories, each school's readiness, the year's activities and attendance,
 * what needs attention and what to do next. All from Go's page answer.
 */
import { AlertCircle, BarChart3, CalendarCheck, CalendarDays, ChevronRight, CheckCircle2, Clock, Flag, Lightbulb, School, Users, Zap } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';

import type { PageLink, PageMetric, PagePanel, PageRailPart, PageStrip } from '@/gen/edify/screens/v1/page_pb';
import type { ClusterView } from '@/lib/clusterProfileView';
import { resolveHref, withDrawer } from '@/lib/feedPage';

import { ClusterChartTabs } from './ClusterChartTabs';
import { ClusterMembers } from './ClusterMembers';
import { MetricTile, MoreFigures, ProfileCard } from './parts';
import type { Accent } from './parts';

const NOT_ASSESSED = 'Not Assessed';
const RING = 2 * Math.PI * 44;

function Ring({ fraction, figure, caption }: { fraction: number; figure: string; caption: string }) {
  const isWords = figure.length > 6;
  return (
    <div className="relative mx-auto h-[8.5rem] w-[8.5rem] shrink-0" role="img" aria-label={`${figure} ${caption}`.trim()}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="50" cy="50" r="44" fill="none" stroke="var(--edify-surface-muted)" strokeWidth="8" />
        {fraction > 0 ? (
          <circle cx="50" cy="50" r="44" fill="none" stroke="var(--brand-primary)" strokeWidth="8" strokeLinecap="round" strokeDasharray={`${Math.min(fraction, 1) * RING} ${RING}`} />
        ) : null}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center px-3 text-center">
        <span className={`font-bold leading-tight text-[var(--edify-text)] ${isWords ? 'text-[14px]' : 'text-[24px] tabular-nums'}`}>{figure}</span>
        {caption ? <span className="text-[12px] text-[var(--edify-text-muted)]">{caption}</span> : null}
      </div>
    </div>
  );
}

function SsaCard({ part, year, pagePath }: { part: PageRailPart; year: string; pagePath: string }) {
  const score = Number.parseFloat(part.figure);
  const assessed = Number.isFinite(score);
  return (
    <ProfileCard title="SSA Performance" icon={BarChart3} aside={year} block="cluster-ssa" className="h-full">
      <div data-pf="ssa-split">
        <div className="text-center">
          <Ring fraction={assessed ? score / 10 : 0} figure={part.figure} caption={assessed ? '/ 10.00' : ''} />
          <p className="mt-1 text-[12px] font-medium text-[var(--edify-text-muted)]">{part.figureNote}</p>
          <p className="text-[12px] font-semibold text-[var(--edify-text)]">{part.title}</p>
        </div>
        <div>
          <ul className="divide-y divide-[var(--edify-border)] text-[13px]">
            {part.meters.map((meter) => {
              const href = resolveHref(pagePath, meter.href);
              const missing = meter.value === NOT_ASSESSED;
              const body = (
                <>
                  <span className="min-w-0 flex-1 truncate text-[var(--edify-text)]">{meter.label}</span>
                  {missing ? (
                    <span className="shrink-0 rounded-full bg-[var(--edify-danger-light)] px-2 py-0.5 text-[11px] font-semibold text-[var(--edify-danger-text,var(--edify-text))]">{NOT_ASSESSED}</span>
                  ) : (
                    <span className="shrink-0 font-semibold tabular-nums text-[var(--edify-text)]">{meter.value}</span>
                  )}
                </>
              );
              return (
                <li key={meter.label}>
                  {href ? <Link href={href} className="flex items-center gap-2 py-1 hover:underline">{body}</Link> : <span className="flex items-center gap-2 py-1">{body}</span>}
                </li>
              );
            })}
          </ul>
          {part.note ? <p className="mt-1 text-[12px] text-[var(--edify-text-muted)]">{part.note}</p> : null}
        </div>
      </div>
    </ProfileCard>
  );
}

function ReadinessCard({ panel, pagePath }: { panel: PagePanel; pagePath: string }) {
  const meters = panel.items.flatMap((item) => (item.kind.case === 'meter' ? [item.kind.value] : []));
  return (
    <ProfileCard title={panel.title} icon={School} block="cluster-readiness" className="h-full">
      <ul className="max-h-72 space-y-2 overflow-y-auto pr-1" tabIndex={0} aria-label="SSA readiness of each school">
        {meters.map((meter) => {
          const href = resolveHref(pagePath, meter.href);
          const missing = meter.value === NOT_ASSESSED;
          return (
            <li key={meter.label} className="text-[13px]">
              <div className="flex items-baseline justify-between gap-2">
                {href ? <Link href={href} className="min-w-0 truncate font-medium text-[var(--edify-text)] hover:underline">{meter.label}</Link> : <span className="min-w-0 truncate font-medium">{meter.label}</span>}
                <span className={`shrink-0 text-[12px] font-semibold tabular-nums ${missing ? 'text-[var(--edify-danger-text,var(--edify-text))]' : 'text-[var(--edify-text)]'}`}>{meter.value}</span>
              </div>
              <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-[var(--edify-surface-muted)]">
                <span className="block h-full rounded-full bg-[var(--brand-primary)]" style={{ width: `${Math.round(Math.min(Math.max(meter.fraction, 0), 1) * 100)}%` }} />
              </span>
            </li>
          );
        })}
      </ul>
    </ProfileCard>
  );
}

const ACTIVITY_LOOK: readonly (readonly [LucideIcon, Accent])[] = [[CalendarDays, 'blue'], [CheckCircle2, 'green'], [Clock, 'violet'], [Flag, 'amber']];

function ActivityCard({ strip, pagePath }: { strip: PageStrip; pagePath: string }) {
  return (
    <ProfileCard title="Cluster Activities" icon={CalendarCheck} block="cluster-activities" className="h-full">
      <div data-pf="tiles">
        {strip.metrics.map((metric, index) => {
          const [icon, accent] = ACTIVITY_LOOK[index % ACTIVITY_LOOK.length]!;
          return <MetricTile key={metric.label} metric={metric} icon={icon} accent={accent} pagePath={pagePath} />;
        })}
      </div>
    </ProfileCard>
  );
}

function AttendanceCard({ strip, pagePath }: { strip: PageStrip; pagePath: string }) {
  const rate = strip.metrics.find((metric) => metric.label === 'Attendance Rate');
  const others: readonly PageMetric[] = strip.metrics.filter((metric) => metric.label !== 'Attendance Rate');
  const percent = Number.parseFloat(rate?.value ?? '');
  return (
    <ProfileCard title="Meeting Attendance" icon={Users} block="cluster-attendance" className="h-full">
      <div data-pf="ssa-split">
        <div className="text-center">
          <Ring fraction={Number.isFinite(percent) ? percent / 100 : 0} figure={rate?.value || '—'} caption="attendance" />
          {rate?.helper ? <p className="mt-1 text-[12px] text-[var(--edify-text-muted)]">{rate.helper}</p> : null}
        </div>
        <div><MoreFigures metrics={others} pagePath={pagePath} /></div>
      </div>
    </ProfileCard>
  );
}

function linkHref(link: PageLink, pagePath: string): string {
  return link.drawer ? withDrawer('', link.href) : resolveHref(pagePath, link.href);
}

function LinksCard({ panel, icon, pagePath, block }: { panel: PagePanel; icon: LucideIcon; pagePath: string; block: string }) {
  return (
    <ProfileCard title={panel.title} icon={icon} block={block} className="h-full">
      <div className="text-[13px]">
        {panel.items.map((item, index) =>
          item.kind.case === 'links' ? (
            <ul key={index} className="divide-y divide-[var(--edify-border)]">
              {item.kind.value.links.map((link) => {
                const href = linkHref(link, pagePath);
                const body = (
                  <>
                    <AlertCircle className="h-4 w-4 shrink-0 text-[var(--edify-warning-text)]" aria-hidden="true" />
                    <span className="min-w-0 flex-1">{link.text}</span>
                    {href ? <ChevronRight className="h-4 w-4 shrink-0 text-[var(--edify-text-muted)]" aria-hidden="true" /> : null}
                  </>
                );
                if (!href) return <li key={link.text} className="flex items-start gap-2 py-2">{body}</li>;
                return (
                  <li key={link.text}>
                    {link.drawer ? (
                      <a href={href} className="flex items-start gap-2 py-2 font-medium text-[var(--edify-text)] hover:underline">{body}</a>
                    ) : (
                      <Link href={href} className="flex items-start gap-2 py-2 font-medium text-[var(--edify-text)] hover:underline">{body}</Link>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : item.kind.case === 'text' ? (
            <p key={index} className="py-2 text-[var(--edify-text-muted)]">{item.kind.value}</p>
          ) : null,
        )}
      </div>
    </ProfileCard>
  );
}

interface ClusterOverviewProps {
  readonly view: ClusterView;
  readonly pagePath: string;
  readonly drawerHref: string;
  readonly selectable: boolean;
}

export function ClusterOverview({ view, pagePath, drawerHref, selectable }: ClusterOverviewProps) {
  return (
    <div data-pf="cluster-grid" data-layout="cluster-overview">
      {view.ssa ? <div data-pf-area="ssa"><SsaCard part={view.ssa} year={view.ssaYear} pagePath={pagePath} /></div> : null}
      {view.charts.length ? <div data-pf-area="chart"><ClusterChartTabs charts={view.charts} /></div> : null}
      {view.readiness ? <div data-pf-area="readiness"><ReadinessCard panel={view.readiness} pagePath={pagePath} /></div> : null}
      {view.activities ? <div data-pf-area="activity"><ActivityCard strip={view.activities} pagePath={pagePath} /></div> : null}
      {view.attendance ? <div data-pf-area="attendance"><AttendanceCard strip={view.attendance} pagePath={pagePath} /></div> : null}
      {view.insights ? <div data-pf-area="insights"><LinksCard panel={view.insights} icon={Lightbulb} pagePath={pagePath} block="cluster-insights" /></div> : null}
      {view.members ? <div data-pf-area="members"><ClusterMembers table={view.members} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} /></div> : null}
      {view.recommended ? <div data-pf-area="recommended"><LinksCard panel={view.recommended} icon={Zap} pagePath={pagePath} block="cluster-recommended" /></div> : null}
    </div>
  );
}
