/*
 * The Cluster Profile's Overview cards: SSA over the assessed schools, its
 * histories, each school's readiness, the year's activities and attendance,
 * what needs attention and what to do next. All from Go's page answer.
 */
import { AlertCircle, ArrowRight, BarChart3, BookOpen, Building2, CalendarCheck, CalendarDays, ChevronRight, CheckCircle2, Clock, Coins, Cross, Flag, GraduationCap, HeartHandshake, Landmark, Lightbulb, School, Target, UserRoundCheck, Users, Zap } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';

import type { PageFilter, PageLink, PageMetric, PagePanel, PageRailPart, PageStrip } from '@/gen/edify/screens/v1/page_pb';
import type { ClusterView } from '@/lib/clusterProfileView';
import { resolveHref, withDrawer } from '@/lib/feedPage';

import { CardFilters } from './CardFilters';
import { ClusterChartTabs } from './ClusterChartTabs';
import { ClusterMembers } from './ClusterMembers';
import { MetricTile, MoreFigures, ProfileCard } from './parts';
import type { Accent } from './parts';

const NOT_ASSESSED = 'Not Assessed';
const RING = 2 * Math.PI * 44;

function Ring({ fraction, figure, caption, small = false }: { fraction: number; figure: string; caption: string; small?: boolean }) {
  const isWords = figure.length > 6;
  return (
    <div data-pf="ring" data-small={small || undefined} role="img" aria-label={`${figure} ${caption}`.trim()}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="50" cy="50" r="44" fill="none" stroke="var(--edify-surface-muted)" strokeWidth="9" />
        {fraction > 0 ? (
          <circle cx="50" cy="50" r="44" fill="none" stroke="var(--brand-primary)" strokeWidth="9" strokeLinecap="round" strokeDasharray={`${Math.min(fraction, 1) * RING} ${RING}`} />
        ) : null}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center px-2 text-center">
        <span className={`font-bold leading-tight text-[var(--edify-text)] ${isWords ? 'text-[13px]' : small ? 'text-[16px] tabular-nums' : 'text-[26px] tabular-nums'}`}>{figure}</span>
        {caption ? <span className="text-[12px] text-[var(--edify-text-muted)]">{caption}</span> : null}
      </div>
    </div>
  );
}

const DOMAIN_ICONS: Readonly<Record<string, LucideIcon>> = {
  'Christlike Behaviour': HeartHandshake,
  'Exposure to the Word of God': Cross,
  'Financial Health': Coins,
  Leadership: UserRoundCheck,
  'Government Requirements': Landmark,
  'Learning Environment': BookOpen,
  "Teacher's Environment": GraduationCap,
  Enrolment: Users,
};

function DomainName({ label, href }: { label: string; href: string }) {
  const DomainIcon = DOMAIN_ICONS[label] ?? Building2;
  const name = (
    <>
      <DomainIcon className="h-3.5 w-3.5 shrink-0 text-[var(--brand-primary)]" aria-hidden="true" />
      {label}
    </>
  );
  return href ? <Link href={href} data-pf="domain-name" className="hover:underline">{name}</Link> : <span data-pf="domain-name">{name}</span>;
}

/** The small picture beside a recommended action, chosen by what the action is. */
function actionIcon(words: string): LucideIcon {
  const lower = words.toLowerCase();
  if (lower.includes('ssa')) return CalendarCheck;
  if (lower.includes('meeting')) return Users;
  if (lower.includes('training')) return GraduationCap;
  return Target;
}

function SsaCard({ part, year, filters, pagePath }: { part: PageRailPart; year: string; filters: readonly PageFilter[]; pagePath: string }) {
  const score = Number.parseFloat(part.figure);
  const assessed = Number.isFinite(score);
  return (
    <ProfileCard title="SSA Performance (Cluster)" icon={BarChart3} aside={filters.length ? <CardFilters filters={filters} /> : year} block="cluster-ssa" className="h-full">
      <div data-pf="ssa-split">
        <div className="text-center">
          <Ring fraction={assessed ? score / 10 : 0} figure={part.figure} caption={assessed ? '/ 10.00' : ''} />
          <p className="mt-1 text-[12px] font-medium text-[var(--edify-text-muted)]">{part.figureNote}</p>
          <p className="text-[12px] font-semibold text-[var(--edify-text)]">{part.title}</p>
        </div>
        <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="SSA domains">
          <table data-pf="domain-table">
            <thead>
              <tr>
                <th scope="col">SSA Domain</th>
                <th scope="col" data-num="">Cluster Avg.</th>
                <th scope="col" data-num="">Status</th>
              </tr>
            </thead>
            <tbody>
              {part.meters.map((meter) => {
                const href = resolveHref(pagePath, meter.href);
                const missing = meter.value === NOT_ASSESSED;
                return (
                  <tr key={meter.label}>
                    <td><DomainName label={meter.label} href={href} /></td>
                    <td data-num="" className="font-semibold tabular-nums">{missing ? '—' : meter.value}</td>
                    <td data-num=""><span data-pf="status-chip" data-state={missing ? 'none' : 'done'}>{missing ? NOT_ASSESSED : 'Assessed'}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {part.note ? <p className="mt-1 text-[11.5px] text-[var(--edify-text-muted)]">{part.note}</p> : null}
        </div>
      </div>
    </ProfileCard>
  );
}

function ReadinessCard({ panel, pagePath }: { panel: PagePanel; pagePath: string }) {
  const meters = panel.items.flatMap((item) => (item.kind.case === 'meter' ? [item.kind.value] : []));
  const notAssessed = meters.filter((meter) => meter.value === NOT_ASSESSED).length;
  return (
    <ProfileCard title={panel.title} icon={School} block="cluster-readiness" className="h-full">
      <ul data-pf="readiness-list" tabIndex={0} aria-label="SSA readiness of each school">
        {meters.map((meter) => {
          const href = resolveHref(pagePath, meter.href);
          const missing = meter.value === NOT_ASSESSED;
          return (
            <li key={`${meter.label}-${meter.href}`}>
              {href ? <Link href={href} title={meter.label} className="min-w-0 font-medium text-[var(--edify-text)] hover:underline">{meter.label}</Link> : <span title={meter.label} className="min-w-0 font-medium">{meter.label}</span>}
              <span className="block h-2 overflow-hidden rounded-full bg-[var(--edify-surface-muted)]">
                <span className="block h-full rounded-full bg-[var(--brand-primary)]" style={{ width: `${Math.round(Math.min(Math.max(meter.fraction, 0), 1) * 100)}%` }} />
              </span>
              <span data-missing={missing || undefined} className="text-right text-[12px] font-semibold tabular-nums">{missing ? 'Not Assessed' : meter.value}</span>
            </li>
          );
        })}
      </ul>
      <p data-pf="legend">
        <span><i data-state="done" aria-hidden="true" /> Assessed ({meters.length - notAssessed})</span>
        <span><i data-state="none" aria-hidden="true" /> Not Assessed ({notAssessed})</span>
      </p>
    </ProfileCard>
  );
}

const ACTIVITY_LOOK: readonly (readonly [LucideIcon, Accent])[] = [[CalendarDays, 'blue'], [CheckCircle2, 'green'], [Clock, 'violet'], [Flag, 'amber']];

function ViewAll({ href, words }: { href: string; words: string }) {
  return (
    <Link href={href} data-pf="view-all">
      {words} <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
    </Link>
  );
}

function ActivityCard({ strip, pagePath, yearQuery }: { strip: PageStrip; pagePath: string; yearQuery: string }) {
  return (
    <ProfileCard title="Cluster Activities" icon={CalendarCheck} aside={<ViewAll href={`${pagePath}?tab=activities${yearQuery}`} words="View All" />} block="cluster-activities" className="h-full">
      <div data-pf="tiles" data-compact="">
        {strip.metrics.map((metric, index) => {
          const [icon, accent] = ACTIVITY_LOOK[index % ACTIVITY_LOOK.length]!;
          return <MetricTile key={metric.label} metric={metric} icon={icon} accent={accent} pagePath={pagePath} />;
        })}
      </div>
    </ProfileCard>
  );
}

const ATTENDANCE_LEAD = ['Meetings Held', 'Schools Represented', 'Teachers Attended'] as const;

function AttendanceCard({ strip, pagePath, yearQuery }: { strip: PageStrip; pagePath: string; yearQuery: string }) {
  const rate = strip.metrics.find((metric) => metric.label === 'Attendance Rate');
  const lead = ATTENDANCE_LEAD.flatMap((label) => strip.metrics.filter((metric) => metric.label === label));
  const others: readonly PageMetric[] = strip.metrics.filter((metric) => metric !== rate && !lead.includes(metric));
  const percent = Number.parseFloat(rate?.value ?? '');
  return (
    <ProfileCard
      title="Meeting Attendance"
      icon={Users}
      aside={<span data-pf="aside-row"><ViewAll href={`${pagePath}?tab=attendance${yearQuery}`} words="View Attendance Records" /><MoreFigures metrics={others} pagePath={pagePath} /></span>}
      block="cluster-attendance"
      className="h-full"
    >
      <div data-pf="attendance-row">
        <Ring small fraction={Number.isFinite(percent) ? percent / 100 : 0} figure={rate?.value || '—'} caption="" />
        <div data-pf="attendance-words">
          <strong>Meeting Attendance</strong>
          <span>{rate?.helper || 'No meetings recorded this year'}</span>
        </div>
        {lead.map((metric) => (
          <div key={metric.label} data-pf="attendance-stat">
            <strong>{metric.value}</strong>
            <span>{metric.label}</span>
          </div>
        ))}
      </div>
    </ProfileCard>
  );
}

function linkHref(link: PageLink, pagePath: string): string {
  return link.drawer ? withDrawer('', link.href) : resolveHref(pagePath, link.href);
}

function LinksCard({ panel, title, icon, pagePath, block, varied = false }: { panel: PagePanel; title?: string; icon: LucideIcon; pagePath: string; block: string; varied?: boolean }) {
  return (
    <ProfileCard title={title ?? panel.title} icon={icon} block={block} className="h-full">
      <div className="text-[13px]">
        {panel.items.map((item, index) =>
          item.kind.case === 'links' ? (
            <ul key={index} data-pf="link-list" tabIndex={0} aria-label={`${title ?? panel.title} list`} className="divide-y divide-[var(--edify-border)]">
              {item.kind.value.links.map((link) => {
                const href = linkHref(link, pagePath);
                const LineIcon = varied ? actionIcon(link.text) : AlertCircle;
                const body = (
                  <>
                    <LineIcon className={`h-4 w-4 shrink-0 ${varied ? 'text-[var(--brand-primary)]' : 'text-[var(--edify-warning-text)]'}`} aria-hidden="true" />
                    <span className="min-w-0 flex-1">{link.text}</span>
                    {href ? <ChevronRight className="h-4 w-4 shrink-0 text-[var(--edify-text-muted)]" aria-hidden="true" /> : null}
                  </>
                );
                if (!href) return <li key={link.text} className="flex items-start gap-2 py-1.5">{body}</li>;
                return (
                  <li key={link.text}>
                    {link.drawer ? (
                      <a href={href} className="flex items-start gap-2 py-1.5 font-medium text-[var(--edify-text)] hover:underline">{body}</a>
                    ) : (
                      <Link href={href} className="flex items-start gap-2 py-1.5 font-medium text-[var(--edify-text)] hover:underline">{body}</Link>
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
  readonly filters: readonly PageFilter[];
  readonly pagePath: string;
  readonly drawerHref: string;
  readonly selectable: boolean;
}

export function ClusterOverview({ view, filters, pagePath, drawerHref, selectable }: ClusterOverviewProps) {
  const year = filters.find((filter) => filter.name === 'fy')?.value;
  const yearQuery = year ? `&fy=${encodeURIComponent(year)}` : '';
  return (
    <div data-pf="cluster-grid" data-layout="cluster-overview">
      {view.ssa ? <div data-pf-area="ssa"><SsaCard part={view.ssa} year={view.ssaYear} filters={filters} pagePath={pagePath} /></div> : null}
      {view.charts.length ? <div data-pf-area="chart"><ClusterChartTabs charts={view.charts} /></div> : null}
      {view.readiness ? <div data-pf-area="readiness"><ReadinessCard panel={view.readiness} pagePath={pagePath} /></div> : null}
      {view.activities ? <div data-pf-area="activity"><ActivityCard strip={view.activities} pagePath={pagePath} yearQuery={yearQuery} /></div> : null}
      {view.attendance ? <div data-pf-area="attendance"><AttendanceCard strip={view.attendance} pagePath={pagePath} yearQuery={yearQuery} /></div> : null}
      {view.insights ? <div data-pf-area="insights"><LinksCard panel={view.insights} title={view.ssaYear ? `Cluster Insights — ${view.ssaYear}` : undefined} icon={Lightbulb} pagePath={pagePath} block="cluster-insights" /></div> : null}
      {view.members ? <div data-pf-area="members"><ClusterMembers table={view.members} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} /></div> : null}
      {view.recommended ? <div data-pf-area="recommended"><LinksCard panel={view.recommended} icon={Zap} pagePath={pagePath} block="cluster-recommended" varied /></div> : null}
    </div>
  );
}
