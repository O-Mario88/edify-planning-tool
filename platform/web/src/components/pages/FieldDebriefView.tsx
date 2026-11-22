'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Clock,
  Info,
  Layers,
  Lightbulb,
  Plus,
  Users,
  Zap,
} from 'lucide-react';

import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import type { PagePanel, PageTable } from '@/gen/edify/screens/v1/page_pb';

import { Badge } from '../blocks/Badge';
import {
  AreaLineChart,
  DonutChart,
  EDIFY_BTN_OUTLINE,
  EDIFY_BTN_PRIMARY,
  EmptyStatePanel,
  KpiStatCard,
  PageHeroHeader,
  findAllCharts,
  findAllPanels,
  findAllSegments,
  findAllStrips,
  findFilters,
  resolveActionHref,
  resolveSafeHref,
} from './EdifyDashboardChrome';

const SERIES_COLORS = [
  'var(--edify-navy-900, #073962)',
  'var(--edify-sky-400, #7bbde8)',
  'var(--brand-primary, #0e5da3)',
  'var(--edify-brand-secondary, #ef564b)',
] as const;

const DONUT_COLORS = [
  'var(--edify-navy-900, #073962)',
  'var(--brand-primary, #0e5da3)',
  'var(--edify-teal-600, #4e8ea2)',
  'var(--edify-steel-600, #49769f)',
  'var(--edify-sky-400, #7bbde8)',
  'var(--edify-slate-500, #64748b)',
] as const;

const DEFAULT_ACTIVITY_LEGEND = ['School Visits', 'Cluster Meetings', 'Training', 'Other'] as const;

function panelTexts(panel: PagePanel | undefined): string[] {
  if (!panel) return [];
  const out: string[] = [];
  for (const item of panel.items) {
    if (item.kind.case === 'text') out.push(item.kind.value);
    if (item.kind.case === 'links') {
      for (const l of item.kind.value.links) out.push(l.text);
    }
  }
  return out;
}

export function FieldDebriefView({
  answer,
  pagePath,
  drawerHref,
}: {
  readonly answer: GetPageResponse;
  readonly pagePath: string;
  readonly drawerHref: string;
}) {
  const router = useRouter();
  const filters = findFilters(answer.blocks);
  const strips = findAllStrips(answer.blocks);
  const charts = findAllCharts(answer.blocks);
  const panels = findAllPanels(answer.blocks);
  const segmentsList = findAllSegments(answer.blocks);

  const mainStrip = strips[0];
  const metrics = mainStrip?.metrics ?? [];
  const topFour = [
    metrics[0] ?? { label: 'Debriefs Submitted', value: '0', helper: '' },
    metrics[1] ?? { label: 'Activities Completed', value: '0', helper: '' },
    metrics[2] ?? { label: 'Partially Completed', value: '0', helper: '' },
    metrics[3] ?? { label: 'Unsuccessful / Cancelled', value: '0', helper: '' },
  ];
  const extraMetrics = metrics.slice(4);

  const trendChart = charts.find((c) => /trend/i.test(c.title));
  const activityChart = charts.find((c) => /activity type/i.test(c.title));
  const actionCenterPanel = panels.find((p) => /action center/i.test(p.title));
  const challengesPanel = panels.find((p) => /challenge/i.test(p.title));
  const recentPanel = panels.find((p) => /recent activity/i.test(p.title));
  const peerPanel = panels.find((p) => /peer solutions/i.test(p.title));

  const actionRows = (() => {
    const out: { label: string; value: string }[] = [];
    for (const item of actionCenterPanel?.items ?? []) {
      if (item.kind.case === 'rows') {
        for (const r of item.kind.value.rows) out.push({ label: r.label, value: r.value });
      }
    }
    return out.length
      ? out
      : [
          { label: 'Debriefs Requiring My Action', value: '0' },
          { label: 'Escalations to Review', value: '0' },
          { label: 'Clarifications Requested', value: '0' },
          { label: 'Overdue Actions', value: '0' },
          { label: 'Open Commitments', value: '0' },
        ];
  })();

  const actionCenterHref = (() => {
    for (const item of actionCenterPanel?.items ?? []) {
      if (item.kind.case === 'links' && item.kind.value.links[0]) {
        return resolveSafeHref(pagePath, item.kind.value.links[0].href) || '/debriefs?tab=escalated';
      }
    }
    return '/debriefs?tab=escalated';
  })();

  const donutEntries = (() => {
    if (activityChart && activityChart.categories.length > 0) {
      const vals = activityChart.series[0]?.values ?? [];
      return activityChart.categories.map((cat, idx) => ({
        label: cat,
        value: vals[idx] ?? 0,
        color: DONUT_COLORS[idx % DONUT_COLORS.length]!,
      }));
    }
    return DEFAULT_ACTIVITY_LEGEND.map((cat, idx) => ({
      label: cat,
      value: 0,
      color: DONUT_COLORS[idx % DONUT_COLORS.length]!,
    }));
  })();

  const totalActivities = donutEntries.reduce((s, d) => s + d.value, 0);

  const debriefSegments = segmentsList[0]?.segments ?? [];
  const defaultSegIdx = Math.max(
    0,
    debriefSegments.findIndex((s) => s.active),
  );
  const [activeSegIdx, setActiveSegIdx] = useState(defaultSegIdx);
  const [contextOpen, setContextOpen] = useState(false);

  const activeSegment = debriefSegments[activeSegIdx] ?? debriefSegments[0];
  const activeTable: PageTable | undefined = (() => {
    for (const b of activeSegment?.blocks ?? []) {
      if (b.kind.case === 'table') return b.kind.value;
    }
    return undefined;
  })();

  // Notice Go emits a 1-cell placeholder row when empty ("No Field Debriefs match these filters.")
  const isPlaceholderEmptyRow =
    activeTable &&
    activeTable.rows.length === 1 &&
    activeTable.rows[0]!.cells.length === 1 &&
    activeTable.columns.length > 1;
  const realRows = isPlaceholderEmptyRow ? [] : activeTable?.rows ?? [];
  const emptyTableText = isPlaceholderEmptyRow
    ? activeTable?.rows[0]?.cells[0]?.text || 'No field debriefs match these filters.'
    : activeTable?.emptyMessage || 'No field debriefs match these filters.';

  const trendCategories = trendChart?.categories ?? [];
  const trendWindow =
    trendCategories.length >= 2
      ? `${trendCategories[0]} – ${trendCategories[trendCategories.length - 1]}`
      : trendCategories[0] ?? 'Selected period';

  function handleFilterChange(name: string, value: string) {
    const params = new URLSearchParams();
    for (const f of filters?.filters ?? []) {
      const nextVal = f.name === name ? value : f.value;
      if (nextVal) params.set(f.name, nextVal);
    }
    const qs = params.toString();
    router.push(qs ? `${pagePath}?${qs}` : pagePath);
  }

  const headerActions = answer.header?.actions ?? [];
  const weeklyAct = headerActions.find((a) => /weekly/i.test(a.label));
  const submitAct = headerActions.find((a) => a.primary || /new|submit/i.test(a.label));


  return (
    <div className="mx-auto max-w-[1440px] space-y-4 px-4 pb-20 pt-4 sm:px-6 lg:pb-10" data-page={pagePath}>
      <PageHeroHeader
        eyebrow={answer.header?.eyebrow || 'My Work'}
        title={answer.header?.title || 'Field Debrief Dashboard'}
        description={
          answer.header?.description ||
          'Real-time field intelligence from your team and partners to drive action and improve impact.'
        }
        icon={<ClipboardList className="h-5 w-5" />}
        actions={
          <>
            <Link
              href={weeklyAct ? resolveActionHref(weeklyAct, pagePath, drawerHref) : '/debriefs/weekly-report'}
              className={EDIFY_BTN_OUTLINE}
            >
              <BarChart3 className="h-3.5 w-3.5 text-[var(--brand-primary)]" aria-hidden="true" />
              <span>{weeklyAct?.label || 'Weekly Report'}</span>
            </Link>
            <Link
              href={submitAct ? resolveActionHref(submitAct, pagePath, drawerHref) : '/debriefs/submit'}
              className={EDIFY_BTN_PRIMARY}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              <span>{submitAct?.label || 'New Field Debrief'}</span>
            </Link>
          </>
        }
      />

      {/* 4-Column Filter Bar */}
      {filters && filters.filters.length > 0 ? (
        <section
          aria-label="Debrief filters"
          className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-3.5 shadow-[var(--edify-shadow-xs)]"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {filters.filters.map((f) => {
              return (
                <label key={f.name} className="space-y-1">
                  <span className="block text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                    {f.caption || f.label}
                  </span>
                  <div className="relative">
                    <select
                      name={f.name}
                      value={f.value}
                      onChange={(e) => handleFilterChange(f.name, e.target.value)}
                      className="h-9 w-full rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] pr-3 text-[12.5px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none"
                    >
                      {f.options.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </label>
              );
            })}
          </div>
        </section>
      ) : null}

      {/* 4 KPI Stat Cards */}
      <section aria-label="Debrief summary metrics" className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
        <KpiStatCard
          label={topFour[0]!.label}
          value={topFour[0]!.value}
          helper={topFour[0]!.helper || undefined}
          tone="brand"
          icon={<ClipboardList className="h-5 w-5" />}
        />
        <KpiStatCard
          label={topFour[1]!.label}
          value={topFour[1]!.value}
          helper={topFour[1]!.helper || undefined}
          tone="success"
          icon={<CheckCircle2 className="h-5 w-5" />}
        />
        <KpiStatCard
          label={topFour[2]!.label}
          value={topFour[2]!.value}
          helper={topFour[2]!.helper || undefined}
          tone="teal"
          icon={<Layers className="h-5 w-5" />}
        />
        <KpiStatCard
          label={topFour[3]!.label}
          value={topFour[3]!.value}
          helper={topFour[3]!.helper || undefined}
          tone="danger"
          icon={<AlertTriangle className="h-5 w-5" />}
        />
      </section>

      {/* 3-Column Analytics + Side Context & Action Center */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Trend Chart */}
        <section className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)] lg:col-span-6">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
              <h2 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                Debrief Trend Over Time
              </h2>
            </div>
            <div className="inline-flex items-center gap-1.5 rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-2.5 py-1 text-[11.5px] font-semibold text-[var(--edify-text)]">
              <Calendar className="h-3 w-3 text-[var(--brand-primary)]" aria-hidden="true" />
              <span>{trendWindow}</span>
            </div>
          </div>

          <AreaLineChart
            minY={0}
            height={160}
            labels={trendCategories.length ? trendCategories : ['Day 1', 'Day 7', 'Day 14', 'Day 21', 'Day 30']}
            series={(trendChart?.series ?? []).map((s, idx) => ({
              name: s.name,
              color: SERIES_COLORS[idx % SERIES_COLORS.length]!,
              values: s.values,
              fill: idx === 0,
            }))}
          />

          <div className="mt-2 flex flex-wrap items-center justify-center gap-4 text-[11.5px] font-semibold text-[var(--edify-text-muted)]">
            {['Submitted', 'Completed', 'Action Required', 'Critical'].map((name, idx) => (
              <span key={name} className="inline-flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-[3px]"
                  style={{ backgroundColor: SERIES_COLORS[idx % SERIES_COLORS.length] }}
                />
                {name}
              </span>
            ))}
          </div>
        </section>

        {/* Debriefs by Activity Type Donut */}
        <section className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)] lg:col-span-3">
          <div className="mb-3 flex items-center gap-2">
            <Activity className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
            <h2 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
              Debriefs by Activity Type
            </h2>
          </div>

          <div className="flex flex-col items-center gap-4">
            <DonutChart
              size={116}
              strokeWidth={16}
              centerValue={String(totalActivities)}
              centerLabel="Total Activities"
              slices={donutEntries}
            />
            <ul className="w-full flex-1 space-y-2 text-[12px]">
              {donutEntries.slice(0, 5).map((entry) => {
                const share = totalActivities > 0 ? Math.round((entry.value / totalActivities) * 100) : 0;
                return (
                  <li key={entry.label} className="flex items-center justify-between gap-2">
                    <span className="inline-flex min-w-0 items-center gap-1.5 font-medium text-[var(--edify-text)]">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                        style={{ backgroundColor: entry.color }}
                      />
                      <span className="truncate">{entry.label}</span>
                    </span>
                    <span className="shrink-0 font-bold tabular-nums text-[var(--edify-text-muted)]">
                      {entry.value} ({share}%)
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </section>

        {/* Right Side Column: Debrief Context + Action Center */}
        <div className="flex flex-col gap-4 lg:col-span-3">
          <section className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-3.5 shadow-[var(--edify-shadow-xs)]">
            <button
              type="button"
              onClick={() => setContextOpen((v) => !v)}
              aria-expanded={contextOpen}
              className="flex w-full items-center justify-between gap-2 text-left"
            >
              <span className="inline-flex items-center gap-2 text-[13.5px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                <Info className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                Debrief Context
              </span>
              {contextOpen ? (
                <ChevronUp className="h-4 w-4 text-[var(--edify-text-muted)]" />
              ) : (
                <ChevronDown className="h-4 w-4 text-[var(--edify-text-muted)]" />
              )}
            </button>
            <div className="mt-2 rounded-[8px] bg-[var(--brand-primary-soft)] px-3 py-1.5 text-[12px] font-semibold text-[var(--brand-primary-text)]">
              All figures ({topFour[0]!.value})
            </div>
            {contextOpen && extraMetrics.length > 0 ? (
              <dl className="mt-2.5 space-y-1.5 border-t border-[var(--edify-table-divider)] pt-2.5 text-[12px]">
                {extraMetrics.map((m) => (
                  <div key={m.label} className="flex items-center justify-between gap-2">
                    <dt className="text-[var(--edify-text-muted)]">{m.label}</dt>
                    <dd className="font-bold tabular-nums text-[var(--edify-text)]">{m.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </section>

          <section className="flex-1 rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)]">
            <div className="mb-3 flex items-center gap-2">
              <Zap className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
              <h2 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                Action Center
              </h2>
            </div>
            <ul className="space-y-2 text-[12.5px]">
              {actionRows.map((row) => (
                <li key={row.label} className="flex items-center justify-between gap-2">
                  <span className="text-[var(--edify-text-muted)]">{row.label}</span>
                  <span className="font-extrabold tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                    {row.value}
                  </span>
                </li>
              ))}
            </ul>
            <Link
              href={actionCenterHref}
              className="mt-3.5 flex w-full items-center justify-center rounded-[10px] border border-[var(--brand-primary-border)] bg-[var(--brand-primary-soft)] px-3 py-2 text-[12.5px] font-bold text-[var(--brand-primary-text)] transition-colors hover:bg-[var(--brand-primary)] hover:text-white"
            >
              View Action Center →
            </Link>
          </section>
        </div>
      </div>

      {/* Team & Partner Debriefs Table Card */}
      <section className="overflow-hidden rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-xs)]">
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--edify-table-divider)] px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
            <h2 className="text-[14.5px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
              Team &amp; Partner Debriefs
            </h2>
          </div>

          <div role="tablist" aria-label="Debrief categories" className="flex flex-wrap items-center gap-1">
            {debriefSegments.map((seg, idx) => {
              const active = idx === activeSegIdx;
              return (
                <button
                  key={seg.label}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setActiveSegIdx(idx)}
                  className={`rounded-[8px] px-3 py-1.5 text-[12.5px] font-semibold transition-colors ${
                    active
                      ? 'bg-[var(--brand-primary)] text-white shadow-xs'
                      : 'text-[var(--edify-text-muted)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)]'
                  }`}
                >
                  {seg.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[12.5px]">
            <thead>
              <tr className="border-b border-[var(--edify-table-divider)] bg-[color-mix(in_srgb,var(--brand-primary)_4%,var(--edify-surface))]">
                {(
                  activeTable?.columns.map((c) => c.label) ?? [
                    'Date',
                    'Submitted By',
                    'Role',
                    'Activity Type',
                    'School ID',
                    'School / Cluster / Partner',
                    'Status',
                    'Debrief Title',
                    'Action Required',
                    'Risk Level',
                  ]
                ).map((col) => (
                  <th
                    key={col}
                    className="whitespace-nowrap px-3.5 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            {realRows.length > 0 ? (
              <tbody className="divide-y divide-[var(--edify-table-divider)]">
                {realRows.map((row, rIdx) => (
                  <tr
                    key={rIdx}
                    className="transition-colors hover:bg-[color-mix(in_srgb,var(--brand-primary)_4%,transparent)]"
                  >
                    {row.cells.map((cell, cIdx) => {
                      const href = resolveSafeHref(pagePath, cell.href);
                      return (
                        <td key={cIdx} className="whitespace-nowrap px-3.5 py-2.5 text-[var(--edify-text)]">
                          {cell.badge ? (
                            <Badge tone={cell.tone}>{cell.text}</Badge>
                          ) : href ? (
                            <Link
                              href={href}
                              className="font-semibold text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-sky-400)]"
                            >
                              {cell.text}
                            </Link>
                          ) : (
                            cell.text || '—'
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            ) : null}
          </table>
        </div>

        {realRows.length === 0 ? (
          <EmptyStatePanel
            title={emptyTableText}
            description="Adjust your filters or select a different period."
          />
        ) : null}
      </section>

      {/* 3-Column Bottom Insight Cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <section className="relative overflow-hidden rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)]">
          <div className="mb-2 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
            <h3 className="text-[13.5px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
              Top Challenges Reported
            </h3>
          </div>
          <div className="space-y-1.5 text-[12.5px] text-[var(--edify-text-muted)]">
            {panelTexts(challengesPanel).length ? (
              panelTexts(challengesPanel).map((line, i) => <p key={i}>{line}</p>)
            ) : (
              <p>No challenges reported this period.</p>
            )}
          </div>
        </section>

        <section className="relative overflow-hidden rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)]">
          <div className="mb-2 flex items-center gap-2">
            <Clock className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
            <h3 className="text-[13.5px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
              Recent Activity
            </h3>
          </div>
          <div className="space-y-1.5 text-[12.5px] text-[var(--edify-text-muted)]">
            {panelTexts(recentPanel).length ? (
              panelTexts(recentPanel).map((line, i) => <p key={i}>{line}</p>)
            ) : (
              <p>No recent activity.</p>
            )}
          </div>
        </section>

        <section className="relative overflow-hidden rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)]">
          <div className="mb-2 flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
            <h3 className="text-[13.5px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
              Recent Peer Solutions
            </h3>
          </div>
          <div className="space-y-1.5 text-[12.5px] text-[var(--edify-text-muted)]">
            {panelTexts(peerPanel).length ? (
              panelTexts(peerPanel).map((line, i) => <p key={i}>{line}</p>)
            ) : (
              <p>No peer solutions yet this period.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
