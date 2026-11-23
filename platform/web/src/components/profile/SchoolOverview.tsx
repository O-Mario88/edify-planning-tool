/*
 * The School Profile's Overview: Performance & Impact, the SSA trend, the GPS
 * card, Operations, Loans & Business Transformation, the best and struggling
 * intervention, Profile Insights and Needs Attention. Each card draws what
 * the gateway answered; a card the reader's role has no data for is absent.
 */
import {
  AlertTriangle,
  Award,
  BarChart3,
  CalendarCheck,
  ChevronRight,
  Coins,
  GraduationCap,
  Landmark,
  LineChart,
  MonitorPlay,
  School,
  Settings2,
  Target,
  TrendingDown,
  TrendingUp,
  Minus,
  Users,
  UsersRound,
  Wallet,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import type { ReactNode } from 'react';

import type { PageBlock, PageRail, PageRailPart, PageTable } from '@/gen/edify/screens/v1/page_pb';
import { resolveHref } from '@/lib/feedPage';
import {
  FINANCE_LEAD,
  FINANCE_STRIP,
  INTERVENTION_TABLE,
  OPERATIONS_LEAD,
  OPERATIONS_STRIP,
  PERFORMANCE_LEAD,
  PERFORMANCE_STRIP,
  leadMetrics,
  stripNamed,
} from '@/lib/schoolProfileView';
import type { TrendPoint } from '@/lib/schoolProfileView';

import { Badge } from '../blocks/Badge';
import { FeedBlocks } from '../page/FeedBlocks';
import { MetricTile, MoreFigures, ProfileCard } from './parts';
import type { Accent } from './parts';
import { SsaTrendChart } from './SsaTrendChart';

const PERFORMANCE_LOOK: readonly (readonly [LucideIcon, Accent])[] = [[Users, 'blue'], [TrendingUp, 'green'], [School, 'violet'], [GraduationCap, 'blue']];
const OPERATIONS_LOOK: readonly (readonly [LucideIcon, Accent])[] = [[CalendarCheck, 'green'], [GraduationCap, 'blue'], [MonitorPlay, 'violet'], [UsersRound, 'amber']];
const FINANCE_LOOK: readonly (readonly [LucideIcon, Accent])[] = [[Landmark, 'blue'], [Wallet, 'blue'], [Coins, 'amber'], [BarChart3, 'violet']];
const PLACED_ELSEWHERE = new Set(['scopeLine', 'facts', 'filters', 'rail']);

function tableNamed(blocks: readonly PageBlock[], title: string): PageTable | undefined {
  for (const block of blocks) {
    if (block.kind.case === 'table' && block.kind.value.title === title) return block.kind.value;
  }
  return undefined;
}

function railOf(blocks: readonly PageBlock[]): PageRail | undefined {
  for (const block of blocks) {
    if (block.kind.case === 'rail') return block.kind.value;
  }
  return undefined;
}

function TrendMark({ word }: { word: string }) {
  const lower = word.toLowerCase();
  const TrendIcon = lower.startsWith('improv') ? TrendingUp : lower.startsWith('declin') ? TrendingDown : Minus;
  const tone = lower.startsWith('improv') ? 'text-[var(--edify-success-text)]' : lower.startsWith('declin') ? 'text-[var(--edify-danger)]' : 'text-[var(--edify-text-muted)]';
  return (
    <span className={`inline-flex items-center gap-1 ${tone}`} title={word}>
      <TrendIcon className="h-4 w-4" aria-hidden="true" />
      <span className="sr-only">{word}</span>
    </span>
  );
}

function InterventionCard({ table, pagePath }: { table: PageTable; pagePath: string }) {
  const at = (name: string) => table.columns.findIndex((column) => column.label === name);
  const [standing, intervention, previous, current, change, trend, chosen, supporting, recommended] =
    ['Standing', 'Intervention', 'Previous', 'Current', 'Change', 'Trend', 'Chosen By', 'Supporting Activities', 'Recommended'].map(at) as [number, number, number, number, number, number, number, number, number];
  const head = 'px-2 py-1.5 text-left text-[12px] font-semibold text-[var(--edify-text-muted)]';
  return (
    <ProfileCard title="Best Performing & Struggling Intervention" icon={Award} aside={table.subtitle} area="interventions" block="intervention-standing">
      {table.rows.length ? (
        <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Best performing and struggling intervention">
          <table className="w-full min-w-[30rem] border-collapse text-[13px]">
            <thead className="bg-[var(--edify-surface-muted)]">
              <tr>
                <th scope="col" className={head}>Standing</th>
                <th scope="col" className={head}>Intervention</th>
                <th scope="col" className={`${head} text-right`}>Previous</th>
                <th scope="col" className={`${head} text-right`}>Current</th>
                <th scope="col" className={`${head} text-right`}>Change</th>
                <th scope="col" className={`${head} text-center`}>Trend</th>
                <th scope="col" data-pf="chosen" className={head}>Chosen By</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--edify-border)]">
              {table.rows.map((row, index) => {
                const cell = (column: number) => row.cells[column];
                const link = resolveHref(pagePath, cell(intervention)?.href ?? '');
                const notes = [cell(recommended)?.text, cell(supporting)?.text ? `Supporting ${cell(supporting)?.text}` : ''].filter(Boolean).join(' · ');
                return (
                  <tr key={index}>
                    <td className="whitespace-nowrap px-2 py-2"><Badge tone={cell(standing)?.tone ?? ''}>{cell(standing)?.text}</Badge></td>
                    <td className="px-2 py-2">
                      {link ? <Link href={link} className="font-semibold text-[var(--edify-text)] hover:underline">{cell(intervention)?.text}</Link> : <span className="font-semibold">{cell(intervention)?.text}</span>}
                      {notes ? <span className="block text-[12px] text-[var(--edify-text-muted)]">{notes}</span> : null}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">{cell(previous)?.text}</td>
                    <td className="px-2 py-2 text-right font-semibold tabular-nums">{cell(current)?.text}</td>
                    <td className={`px-2 py-2 text-right font-semibold tabular-nums ${cell(change)?.tone === 'success' ? 'text-[var(--edify-success-text)]' : cell(change)?.tone === 'danger' ? 'text-[var(--edify-danger)]' : ''}`}>{cell(change)?.text}</td>
                    <td className="px-2 py-2 text-center"><TrendMark word={cell(trend)?.text ?? ''} /></td>
                    <td data-pf="chosen" className="px-2 py-2 text-[12px] text-[var(--edify-text-muted)]">{cell(chosen)?.text}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="py-4 text-center text-[13px] text-[var(--edify-text-muted)]">{table.emptyMessage || 'Not compared yet: this school needs two confirmed SSA scores.'}</p>
      )}
    </ProfileCard>
  );
}

function InsightsCard({ rail, pagePath }: { rail: PageRail; pagePath: string }) {
  const ssa = rail.parts.find((part) => part.key === 'ssa');
  const extra = rail.parts.filter((part) => part.key !== 'ssa' && part.key !== 'attention');
  return (
    <ProfileCard title={rail.title || 'Profile Insights'} icon={Target} aside={rail.subtitle} area="insights" block="rail">
      {ssa?.figure ? (
        <p className="mb-2 flex flex-wrap items-baseline gap-x-2">
          <span className="text-[21px] font-bold tabular-nums text-[var(--edify-text)]">{ssa.figure}</span>
          {ssa.figureNote ? <span className="text-[12px] text-[var(--edify-text-muted)]">{ssa.figureNote}</span> : null}
        </p>
      ) : null}
      {ssa?.note ? <p className="mb-2 text-[13px] text-[var(--edify-text-muted)]">{ssa.note}</p> : null}
      <ul className="space-y-1.5">
        {ssa?.meters.map((meter) => {
          const href = resolveHref(pagePath, meter.href);
          const content = (
            <>
              <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--edify-text)]">{meter.label}</span>
              <span className="h-1.5 w-[32%] shrink-0 overflow-hidden rounded-full bg-[var(--edify-surface-muted)]">
                <span className="block h-full rounded-full bg-[var(--brand-primary)]" style={{ width: `${Math.round(Math.min(Math.max(meter.fraction, 0), 1) * 100)}%` }} />
              </span>
              <span className="w-7 shrink-0 text-right text-[13px] font-semibold tabular-nums text-[var(--edify-text)]">{meter.value}</span>
            </>
          );
          return (
            <li key={meter.label}>
              {href ? <Link href={href} className="flex items-center gap-2 py-0.5 hover:underline">{content}</Link> : <span className="flex items-center gap-2 py-0.5">{content}</span>}
            </li>
          );
        })}
      </ul>
      {extra.map((part) => <RailLinks key={part.key} part={part} pagePath={pagePath} />)}
    </ProfileCard>
  );
}

function RailLinks({ part, pagePath }: { part: PageRailPart; pagePath: string }) {
  if (!part.links.length && !part.title) return null;
  return (
    <div className="mt-3 border-t border-[var(--edify-border)] pt-2">
      {part.title ? <h3 className="text-[13px] font-bold text-[var(--edify-text)]">{part.title}</h3> : null}
      <AttentionLinks part={part} pagePath={pagePath} />
    </div>
  );
}

function AttentionLinks({ part, pagePath }: { part: PageRailPart; pagePath: string }) {
  return (
    <ul className="divide-y divide-[color-mix(in_srgb,var(--edify-warning)_22%,var(--edify-border))]">
      {part.links.map((link) => {
        const href = resolveHref(pagePath, link.href);
        const body = (
          <>
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--edify-warning)]" aria-hidden="true" />
            <span className="min-w-0 flex-1">{link.text}</span>
            {href ? <ChevronRight className="h-4 w-4 shrink-0 text-[var(--edify-text-muted)]" aria-hidden="true" /> : null}
          </>
        );
        return (
          <li key={link.text}>
            {href ? <Link href={href} className="flex items-center gap-2 py-2 text-[13px] font-medium text-[var(--edify-text)] hover:underline">{body}</Link> : <span className="flex items-center gap-2 py-2 text-[13px] font-medium">{body}</span>}
          </li>
        );
      })}
    </ul>
  );
}

interface SchoolOverviewProps {
  readonly blocks: readonly PageBlock[];
  readonly trend: readonly TrendPoint[];
  readonly year: string;
  readonly pagePath: string;
  readonly drawerHref: string;
  /** The Location & GPS card. */
  readonly location: ReactNode;
}

export function SchoolOverview({ blocks, trend, year, pagePath, drawerHref, location }: SchoolOverviewProps) {
  const performance = stripNamed(blocks, PERFORMANCE_STRIP);
  const operations = stripNamed(blocks, OPERATIONS_STRIP);
  const finance = stripNamed(blocks, FINANCE_STRIP);
  const table = tableNamed(blocks, INTERVENTION_TABLE);
  const rail = railOf(blocks);
  const attention = rail?.parts.find((part) => part.key === 'attention');
  const perf = leadMetrics(performance, PERFORMANCE_LEAD);
  const ops = leadMetrics(operations, OPERATIONS_LEAD);
  const fin = leadMetrics(finance, FINANCE_LEAD);
  const filters = blocks.filter((block) => block.kind.case === 'filters');
  const placed = new Set<unknown>([performance, operations, finance, table]);
  const others = blocks.filter((block) => !PLACED_ELSEWHERE.has(block.kind.case ?? '') && !placed.has(block.kind.value));
  const trendRange = trend.length > 1 ? `${trend[0]!.label} – ${trend[trend.length - 1]!.label}` : trend[0]?.label ?? '';
  const feed = { pagePath, drawerHref, selectable: false, clearFilters: false };
  return (
    <div className="space-y-3">
      {filters.length ? <FeedBlocks blocks={filters} {...feed} /> : null}
      <div data-pf="overview" data-layout="school-overview">
        <div data-pf="overview-main">
          {performance ? (
            <ProfileCard title="Performance & Impact" icon={BarChart3} aside={year} area="performance" block="performance">
              <div data-pf="tiles">
                {perf.lead.map((metric, index) => <MetricTile key={metric.label} metric={metric} icon={PERFORMANCE_LOOK[index]![0]} accent={PERFORMANCE_LOOK[index]![1]} pagePath={pagePath} />)}
              </div>
              <MoreFigures metrics={perf.more} pagePath={pagePath} />
            </ProfileCard>
          ) : null}
          <ProfileCard title="SSA Score Trend" icon={LineChart} aside={trendRange} area="trend" block="ssa-trend">
            <SsaTrendChart points={trend} />
          </ProfileCard>
          {operations ? (
            <ProfileCard title="Operations" icon={Settings2} aside="In the plan" area="operations" alone={!finance} block="operations">
              <div data-pf="tile-rows">
                {ops.lead.map((metric, index) => <MetricTile key={metric.label} metric={metric} icon={OPERATIONS_LOOK[index]![0]} accent={OPERATIONS_LOOK[index]![1]} pagePath={pagePath} rowOnPhone />)}
              </div>
              <MoreFigures metrics={ops.more} pagePath={pagePath} />
            </ProfileCard>
          ) : null}
          {finance ? (
            <ProfileCard title="Loans & Business Transformation" icon={Landmark} area="finance" block="finance">
              <div data-pf="tile-rows">
                {fin.lead.map((metric, index) => <MetricTile key={metric.label} metric={metric} icon={FINANCE_LOOK[index]![0]} accent={FINANCE_LOOK[index]![1]} pagePath={pagePath} rowOnPhone />)}
              </div>
              <MoreFigures metrics={fin.more} pagePath={pagePath} />
            </ProfileCard>
          ) : null}
          {table ? <InterventionCard table={table} pagePath={pagePath} /> : null}
          {rail ? <InsightsCard rail={rail} pagePath={pagePath} /> : null}
          {attention?.links.length ? (
            <section
              data-block="needs-attention"
              data-pf-card="attention"
              aria-label="Needs Attention"
              className="card min-w-0 border-[color-mix(in_srgb,var(--edify-warning)_35%,var(--edify-border))] bg-[color-mix(in_srgb,var(--edify-warning)_7%,var(--edify-surface))] p-4"
            >
              <h2 className="mb-1 flex items-center gap-2 text-[16px] font-bold text-[var(--edify-text)]">
                <AlertTriangle className="h-[18px] w-[18px] text-[var(--edify-warning-text)]" aria-hidden="true" />
                {attention.title || 'Needs Attention'}
              </h2>
              <AttentionLinks part={attention} pagePath={pagePath} />
            </section>
          ) : null}
        </div>
        <div data-pf-card="location">{location}</div>
      </div>
      {others.length ? <FeedBlocks blocks={others} {...feed} /> : null}
    </div>
  );
}
