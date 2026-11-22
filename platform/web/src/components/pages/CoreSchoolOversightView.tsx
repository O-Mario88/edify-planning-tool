'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Fragment, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Award,
  BarChart3,
  Building2,
  Calendar,
  Columns3,
  Download,
  Eye,
  GraduationCap,
  LayoutGrid,
  Lightbulb,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Scale,
  Shield,
  TrendingUp,
  Users,
  X,
} from 'lucide-react';

import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import type { PageBlock, PageRow } from '@/gen/edify/screens/v1/page_pb';

import { Pager } from '../blocks/Pager';
import { FeedBlocks } from '../page/FeedBlocks';
import {
  AreaLineChart,
  DonutChart,
  EDIFY_BTN_OUTLINE,
  EDIFY_BTN_PRIMARY,
  EmptyStatePanel,
  KpiStatCard,
  PageHeroHeader,
  findAllLinkTabs,
  findAllStrips,
  findAllTables,
  findFilters,
  parseLeadingNumber,
  resolveActionHref,
  resolveSafeHref,
} from './EdifyDashboardChrome';

const COMPACT_COL_INDICES = [0, 1, 3, 2, 6, 9, 13, 19] as const;
const COMPACT_COL_LABELS = ['School', 'School ID', 'District', 'Core Type', 'Latest SSA', 'Trajectory', 'Package', 'Champion'] as const;

function parseScore(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed || trimmed === '—' || trimmed === '-') return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

function ssaPillClass(score: number | null): string {
  if (score === null) return 'bg-[var(--edify-surface-muted)] text-[var(--edify-text-muted)]';
  if (score >= 7.5) return 'bg-[var(--edify-success-light)] text-[var(--edify-success-text)] border border-[var(--edify-success-border)]';
  if (score >= 7.0) return 'bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)] border border-[var(--edify-warning-border)]';
  if (score >= 5.0) return 'bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)] border border-[var(--edify-warning-border)]';
  return 'bg-[var(--edify-danger-light)] text-[var(--edify-danger-text)] border border-[var(--edify-danger-border)]';
}

function statusPillClass(text: string): string {
  const low = text.toLowerCase();
  if (low.includes('improv') || low.includes('complete') || low.includes('delivered') || low === 'ready' || low.includes('potential')) {
    return 'bg-[var(--edify-success-light)] text-[var(--edify-success-text)] border border-[var(--edify-success-border)]';
  }
  if (low.includes('declin') || low.includes('no package') || low.includes('critical')) {
    return 'bg-[var(--edify-danger-light)] text-[var(--edify-danger-text)] border border-[var(--edify-danger-border)]';
  }
  if (low.includes('progress') || low.includes('partial') || low.includes('watch')) {
    return 'bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)] border border-[var(--edify-warning-border)]';
  }
  return 'bg-[var(--edify-surface-muted)] text-[var(--edify-text-muted)] border border-[var(--edify-border)]';
}

function tabIcon(label: string) {
  const low = label.toLowerCase();
  if (low.includes('school') && !low.includes('visit') && !low.includes('train')) return LayoutGrid;
  if (low.includes('group')) return Users;
  if (low.includes('attention')) return AlertTriangle;
  if (low.includes('recommend')) return Lightbulb;
  if (low.includes('champion')) return Award;
  if (low.includes('visit')) return Calendar;
  if (low.includes('train')) return GraduationCap;
  return LayoutGrid;
}

export function CoreSchoolOversightView({
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
  const linkTabsList = findAllLinkTabs(answer.blocks);
  const tables = findAllTables(answer.blocks);

  const primaryStrip = strips[0];
  const mainTabs = linkTabsList[0];
  const activeTabLabel = mainTabs?.tabs.find((t) => t.active)?.label ?? 'Schools';
  const isSchoolsTab = activeTabLabel.toLowerCase() === 'schools';

  const metricsMap = useMemo(() => {
    const map = new Map<string, { value: string; helper: string; href: string }>();
    for (const m of primaryStrip?.metrics ?? []) {
      map.set(m.label.toLowerCase(), { value: m.value, helper: m.helper, href: m.href });
    }
    return map;
  }, [primaryStrip]);

  const coreSchoolsCount = metricsMap.get('core schools')?.value ?? '0';
  const currentSsaVal = metricsMap.get('current-year ssa')?.value ?? '0 of 0';
  const comparedVal = metricsMap.get('compared')?.value ?? '0 of 0';
  const improvedVal = metricsMap.get('improved')?.value ?? '0';
  const improvedHelper = metricsMap.get('improved')?.helper ?? 'Of 0 compared';
  const declinedNum = parseLeadingNumber(metricsMap.get('declined')?.value ?? '0');
  const avgSsaRaw = metricsMap.get('average ssa')?.value ?? '—';
  const avgChangeRaw = metricsMap.get('average ssa change')?.value ?? '—';
  const needAttentionNum = parseLeadingNumber(metricsMap.get('need attention')?.value ?? '0');

  const schoolsTable = isSchoolsTab ? tables[0] : undefined;
  const rows = useMemo(() => schoolsTable?.rows ?? [], [schoolsTable]);

  // Compute live SSA distribution & attention counts from real Go table rows
  const ssaStats = useMemo(() => {
    let onTrack = 0;
    let watch = 0;
    let critical = 0;
    let noPackage = 0;
    const scoreValues: number[] = [];

    for (const row of rows) {
      const score = parseScore(row.cells[6]?.text ?? '');
      if (score !== null) {
        scoreValues.push(score);
        if (score >= 7.5) onTrack += 1;
        else if (score >= 7.0) watch += 1;
        else critical += 1;
      }
      const pkg = (row.cells[13]?.text ?? '').toLowerCase();
      if (pkg.includes('no plan') || pkg.includes('no package') || pkg === '—') noPackage += 1;
    }

    const assessedTotal = onTrack + watch + critical;
    const totalShown = rows.length;
    const sorted = [...scoreValues].sort((a, b) => a - b);
    // Bucket sorted scores across 10 decile points for a genuine distribution trend line
    const buckets: number[] = [];
    if (sorted.length > 0) {
      const nBuckets = Math.min(10, sorted.length);
      for (let i = 0; i < nBuckets; i += 1) {
        const start = Math.floor((i * sorted.length) / nBuckets);
        const end = Math.max(start + 1, Math.floor(((i + 1) * sorted.length) / nBuckets));
        const slice = sorted.slice(start, end);
        const avg = slice.reduce((a, b) => a + b, 0) / slice.length;
        buckets.push(Number(avg.toFixed(1)));
      }
    }

    return {
      onTrack,
      watch,
      critical,
      noPackage,
      assessedTotal,
      totalShown,
      trendPoints: buckets,
    };
  }, [rows]);

  const [searchQuery, setSearchQuery] = useState('');
  const [showAllCols, setShowAllCols] = useState(false);
  const [showMoreMetrics, setShowMoreMetrics] = useState(false);
  const [selectedRows, setSelectedRows] = useState<Set<number>>(() => new Set());
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const filteredRows = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => r.cells.some((c) => c.text.toLowerCase().includes(q)));
  }, [rows, searchQuery]);

  // Filter change handler submits GET query cleanly
  function handleFilterChange(name: string, value: string) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filters?.hidden ?? {})) {
      if (v) params.set(k, v);
    }
    for (const f of filters?.filters ?? []) {
      const nextVal = f.name === name ? value : f.value;
      if (nextVal) params.set(f.name, nextVal);
    }
    const qs = params.toString();
    router.push(qs ? `${pagePath}?${qs}` : pagePath);
  }

  function handleExportCsv() {
    if (!schoolsTable || !schoolsTable.rows.length) return;
    const header = schoolsTable.columns.map((c) => `"${c.label.replace(/"/g, '""')}"`).join(',');
    const body = filteredRows
      .map((r) => r.cells.map((c) => `"${c.text.replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const blob = new Blob([`${header}\n${body}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `core-school-oversight-${activeTabLabel.toLowerCase().replace(/\s+/g, '-')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Blocks belonging to non-Schools tabs (everything after the first LinkTabs block)
  const nonSchoolTabBlocks = useMemo(() => {
    const idx = answer.blocks.findIndex((b) => b.kind.case === 'linkTabs');
    if (idx < 0) return [] as PageBlock[];
    return answer.blocks.slice(idx + 1);
  }, [answer.blocks]);

  const fyOption = filters?.filters.find((f) => f.name === 'fy');
  const currentFyLabel = fyOption?.options.find((o) => o.value === fyOption.value)?.label ?? 'FY 2027';

  const pct = (part: number, whole: number) => (whole > 0 ? `${((part / whole) * 100).toFixed(1)}%` : '0.0%');

  const headerActions = answer.header?.actions ?? [];
  const primaryHeaderAction = headerActions.find((a) => a.primary);

  const toggleSelect = (idx: number) => {
    setSelectedRows((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <div className="mx-auto max-w-[1440px] space-y-4 px-4 pb-20 pt-4 sm:px-6 lg:pb-10" data-page={pagePath}>
      <PageHeroHeader
        eyebrow={answer.header?.eyebrow || 'Oversight'}
        title={answer.header?.title || 'Core School Oversight'}
        description={
          answer.header?.description ||
          `Are the Core schools improving, is the package delivered, are schools taking part, and which need action: ${currentFyLabel} against the year before.`
        }
        icon={<Shield className="h-5 w-5" />}
        actions={
          <>
            <button type="button" onClick={handleExportCsv} className={EDIFY_BTN_OUTLINE}>
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Export</span>
            </button>
            {primaryHeaderAction ? (
              <a
                href={resolveActionHref(primaryHeaderAction, pagePath, drawerHref)}
                className={EDIFY_BTN_PRIMARY}
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{primaryHeaderAction.label}</span>
              </a>
            ) : (
              <Link href="/core-schools" className={EDIFY_BTN_PRIMARY}>
                <Building2 className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Core Schools</span>
              </Link>
            )}
          </>
        }
      />

      {/* Inline Filter Bar Card */}
      {filters && filters.filters.length > 0 ? (
        <section
          aria-label="Filters"
          className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-3.5 shadow-[var(--edify-shadow-xs)]"
        >
          <div className="flex flex-wrap items-end gap-2.5">
            {filters.filters.map((f) => (
              <label key={f.name} className="min-w-[138px] flex-1 space-y-1">
                <span className="block text-[11px] font-bold uppercase tracking-[0.03em] text-[var(--edify-text-muted)]">
                  {f.caption || f.label}
                </span>
                <select
                  name={f.name}
                  value={f.value}
                  onChange={(e) => handleFilterChange(f.name, e.target.value)}
                  className="h-9 w-full rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-2.5 text-[12.5px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none"
                >
                  {f.options.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <Link
              href={pagePath}
              title="Reset filters"
              aria-label="Reset filters"
              className="grid h-9 w-9 shrink-0 place-items-center rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] text-[var(--edify-text-muted)] hover:border-[var(--brand-primary-border)] hover:text-[var(--brand-primary-text)]"
            >
              <X className="h-4 w-4" />
            </Link>
          </div>
        </section>
      ) : null}

      {/* Performance Overview Heading + 4 KPI Cards */}
      <section aria-label="Performance Overview" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
            <h2 className="text-[15px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
              Performance Overview
            </h2>
            {(primaryStrip?.metrics.length ?? 0) > 4 ? (
              <button
                type="button"
                onClick={() => setShowMoreMetrics((v) => !v)}
                className="ml-1 rounded-full border border-[var(--brand-primary-border)] bg-[var(--brand-primary-soft)] px-2.5 py-0.5 text-[11px] font-bold text-[var(--brand-primary-text)] hover:bg-[var(--brand-primary)] hover:text-white"
              >
                {showMoreMetrics ? 'Hide extra metrics' : `+${(primaryStrip?.metrics.length ?? 4) - 4} more metrics`}
              </button>
            ) : null}
          </div>
          <div className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-[var(--edify-text-muted)]">
            <span>{currentFyLabel} · Live Go metrics</span>
            <RefreshCw className="h-3 w-3 opacity-70" aria-hidden="true" />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
          <KpiStatCard
            label="Core Schools"
            value={coreSchoolsCount}
            helper={metricsMap.get('core schools')?.helper}
            tone="brand"
            info="Total Core Schools inside your active scope and filters"
            icon={<Building2 className="h-5 w-5" />}
            watermark={<Building2 className="h-14 w-14 text-[var(--brand-primary)]" />}
          />
          <KpiStatCard
            label="Current-Year SSA"
            value={currentSsaVal}
            helper={metricsMap.get('current-year ssa')?.helper}
            tone="info"
            info="Core schools with a confirmed SSA score in the selected fiscal year"
            icon={<BarChart3 className="h-5 w-5" />}
          />
          <KpiStatCard
            label="Compared"
            value={comparedVal}
            helper={metricsMap.get('compared')?.helper}
            tone="purple"
            info="Schools with confirmed SSA scores in both the current and prior fiscal years"
            href={resolveSafeHref(pagePath, metricsMap.get('compared')?.href ?? '') || undefined}
            icon={<Scale className="h-5 w-5" />}
          />
          <KpiStatCard
            label="Improved"
            value={improvedVal}
            helper={improvedHelper}
            tone="success"
            info="Compared Core schools whose SSA score improved over the prior year"
            href={resolveSafeHref(pagePath, metricsMap.get('improved')?.href ?? '') || undefined}
            icon={<TrendingUp className="h-5 w-5" />}
          />
        </div>

        {/* Optional expandable extra Go strip metrics (Package Complete, Attendance, Enrolment, etc.) */}
        {showMoreMetrics && primaryStrip ? (
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            {primaryStrip.metrics.slice(4).map((m) => (
              <div
                key={m.label}
                className="rounded-[12px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-3.5 py-2.5"
              >
                <p className="text-[11px] font-semibold text-[var(--edify-text-muted)]">{m.label}</p>
                <p className="mt-0.5 text-[16px] font-extrabold tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                  {m.value}
                </p>
                {m.helper ? <p className="text-[11px] text-[var(--edify-text-muted)]">{m.helper}</p> : null}
              </div>
            ))}
          </div>
        ) : null}
      </section>

      {/* Main Oversight Tabs */}
      {mainTabs && mainTabs.tabs.length > 0 ? (
        <nav
          aria-label="Oversight views"
          className="flex items-center gap-1 overflow-x-auto rounded-[12px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-1.5 shadow-[var(--edify-shadow-xs)]"
        >
          {mainTabs.tabs.map((tab) => {
            const IconComp = tabIcon(tab.label);
            const isAttention = tab.label.toLowerCase() === 'attention';
            const href = resolveSafeHref(pagePath, tab.href) || pagePath;
            return (
              <Link
                key={tab.label}
                href={href}
                aria-current={tab.active ? 'page' : undefined}
                className={`inline-flex shrink-0 items-center gap-2 rounded-[9px] px-3.5 py-2 text-[13px] font-semibold transition-colors ${
                  tab.active
                    ? 'bg-[var(--brand-primary)] text-white shadow-xs'
                    : 'text-[var(--edify-text-muted)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)]'
                }`}
              >
                <IconComp className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{tab.label}</span>
                {isAttention && needAttentionNum > 0 ? (
                  <span
                    className={`rounded-full px-1.5 py-0.5 text-[11px] font-bold leading-none ${
                      tab.active
                        ? 'bg-white/20 text-white'
                        : 'bg-[var(--edify-brand-secondary,#ef564b)] text-white'
                    }`}
                  >
                    {needAttentionNum}
                  </span>
                ) : null}
              </Link>
            );
          })}
        </nav>
      ) : null}

      {/* Schools Tab: 3-Column Analytics Row + Compact/Full Core Schools Table */}
      {isSchoolsTab ? (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            {/* SSA Status Donut Card */}
            <section className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)] lg:col-span-4">
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                  <h3 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                    SSA Status
                  </h3>
                </div>
                <span className="text-[11px] font-medium text-[var(--edify-text-muted)]">
                  {ssaStats.totalShown} shown
                </span>
              </div>
              <div className="flex items-center gap-4">
                <DonutChart
                  size={126}
                  strokeWidth={17}
                  centerValue={String(ssaStats.assessedTotal || ssaStats.totalShown)}
                  centerLabel="Schools"
                  slices={[
                    { label: 'On Track', value: ssaStats.onTrack, color: 'var(--edify-success)' },
                    { label: 'Watch', value: ssaStats.watch, color: 'var(--edify-warning)' },
                    { label: 'Critical', value: ssaStats.critical, color: 'var(--edify-brand-secondary, #ef564b)' },
                  ]}
                />
                <ul className="flex-1 space-y-2 text-[12px]">
                  <li className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-semibold text-[var(--edify-text)]">
                      <span className="h-2.5 w-2.5 rounded-[3px] bg-[var(--edify-success)]" />
                      On Track (≥ 7.5)
                    </span>
                    <span className="font-bold tabular-nums text-[var(--edify-text)]">
                      {ssaStats.onTrack}{' '}
                      <span className="font-normal text-[var(--edify-text-muted)]">
                        ({pct(ssaStats.onTrack, ssaStats.assessedTotal)})
                      </span>
                    </span>
                  </li>
                  <li className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-semibold text-[var(--edify-text)]">
                      <span className="h-2.5 w-2.5 rounded-[3px] bg-[var(--edify-warning)]" />
                      Watch (7.0 – 7.4)
                    </span>
                    <span className="font-bold tabular-nums text-[var(--edify-text)]">
                      {ssaStats.watch}{' '}
                      <span className="font-normal text-[var(--edify-text-muted)]">
                        ({pct(ssaStats.watch, ssaStats.assessedTotal)})
                      </span>
                    </span>
                  </li>
                  <li className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-semibold text-[var(--edify-text)]">
                      <span className="h-2.5 w-2.5 rounded-[3px] bg-[var(--edify-brand-secondary,#ef564b)]" />
                      Critical (&lt; 7.0)
                    </span>
                    <span className="font-bold tabular-nums text-[var(--edify-text)]">
                      {ssaStats.critical}{' '}
                      <span className="font-normal text-[var(--edify-text-muted)]">
                        ({pct(ssaStats.critical, ssaStats.assessedTotal)})
                      </span>
                    </span>
                  </li>
                </ul>
              </div>
            </section>

            {/* SSA Trend / Distribution Card */}
            <section className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)] lg:col-span-5">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                  SSA Distribution (Core Schools)
                </h3>
                <span className="text-[11px] font-medium text-[var(--edify-text-muted)]">{currentFyLabel}</span>
              </div>
              <div className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-center">
                <div className="min-w-0 flex-1">
                  <AreaLineChart
                    minY={0}
                    maxY={10}
                    height={138}
                    labels={
                      ssaStats.trendPoints.length > 0
                        ? ssaStats.trendPoints.map((_, idx) => `D${idx + 1}`)
                        : ['Oct', 'Dec', 'Feb', 'Apr', 'Jun', 'Sep']
                    }
                    series={[
                      {
                        name: 'Latest SSA',
                        color: 'var(--brand-primary)',
                        values: ssaStats.trendPoints.length > 0 ? ssaStats.trendPoints : [0, 0, 0, 0, 0, 0],
                        fill: true,
                      },
                    ]}
                  />
                </div>
                <div className="flex shrink-0 flex-row gap-2 sm:w-[118px] sm:flex-col">
                  <div className="flex-1 rounded-[10px] border border-[color-mix(in_srgb,var(--brand-primary)_22%,var(--edify-border))] bg-[var(--brand-primary-soft)] px-3 py-2">
                    <p className="text-[19px] font-extrabold leading-tight tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-sky-400)]">
                      {avgSsaRaw}
                    </p>
                    <p className="text-[10.5px] font-semibold text-[var(--brand-primary-text)]">Latest Avg SSA</p>
                  </div>
                  <div className="flex-1 rounded-[10px] border border-[var(--edify-success-border)] bg-[var(--edify-success-light)] px-3 py-2">
                    <p className="text-[15px] font-extrabold leading-tight tabular-nums text-[var(--edify-success-text)]">
                      {avgChangeRaw}
                    </p>
                    <p className="text-[10.5px] font-semibold text-[var(--edify-success-text)] opacity-90">
                      vs. last year
                    </p>
                  </div>
                </div>
              </div>
            </section>

            {/* Attention Summary Card */}
            <section className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)] lg:col-span-3">
              <div className="mb-3 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-[var(--edify-brand-secondary,#ef564b)]" aria-hidden="true" />
                <h3 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                  Attention Summary
                </h3>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between rounded-[10px] border border-[color-mix(in_srgb,var(--brand-primary)_18%,var(--edify-border))] bg-[var(--brand-primary-soft)] px-3.5 py-2.5">
                  <span className="text-[12.5px] font-semibold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                    SSA Declined
                  </span>
                  <span className="text-[14px] font-extrabold tabular-nums text-[var(--brand-primary-text)]">
                    {declinedNum}
                  </span>
                </div>
                <div className="flex items-center justify-between rounded-[10px] border border-[var(--edify-danger-border)] bg-[var(--edify-danger-light)] px-3.5 py-2.5">
                  <span className="text-[12.5px] font-semibold text-[var(--edify-danger-text)]">
                    Critical SSA Area
                  </span>
                  <span className="text-[14px] font-extrabold tabular-nums text-[var(--edify-danger-text)]">
                    {ssaStats.critical}
                  </span>
                </div>
                <div className="flex items-center justify-between rounded-[10px] border border-[var(--edify-warning-border)] bg-[var(--edify-warning-light)] px-3.5 py-2.5">
                  <span className="text-[12.5px] font-semibold text-[var(--edify-warning-text)]">
                    Need Attention
                  </span>
                  <span className="text-[14px] font-extrabold tabular-nums text-[var(--edify-warning-text)]">
                    {needAttentionNum}
                  </span>
                </div>
              </div>
            </section>
          </div>

          {/* Core Schools Table Card */}
          <section className="overflow-hidden rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-xs)]">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--edify-table-divider)] px-4 py-3.5 sm:px-5">
              <div className="flex items-center gap-2">
                <Building2 className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                <h3 className="text-[15px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                  Core Schools ({coreSchoolsCount})
                </h3>
                {selectedRows.size > 0 ? (
                  <span className="rounded-full bg-[var(--brand-primary-soft)] px-2 py-0.5 text-[11.5px] font-bold text-[var(--brand-primary-text)]">
                    {selectedRows.size} selected
                  </span>
                ) : null}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <label className="relative">
                  <input
                    type="search"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search schools..."
                    className="h-9 w-52 rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] pr-3 text-[12.5px] text-[var(--edify-text)] placeholder:text-[var(--edify-text-muted)] focus:border-[var(--brand-primary)] focus:outline-none sm:w-64"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => setShowAllCols((v) => !v)}
                  className={EDIFY_BTN_OUTLINE}
                  aria-pressed={showAllCols}
                >
                  <Columns3 className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>{showAllCols ? 'Compact Columns' : 'Columns'}</span>
                </button>
              </div>
            </div>

            {filteredRows.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-left text-[13px]">
                  <thead>
                    <tr className="border-b border-[var(--edify-table-divider)] bg-[color-mix(in_srgb,var(--brand-primary)_4%,var(--edify-surface))]">
                      <th className="w-10 px-3 py-2.5">
                        <input
                          type="checkbox"
                          aria-label="Select all visible schools"
                          checked={selectedRows.size > 0 && selectedRows.size === filteredRows.length}
                          onChange={(e) => {
                            if (e.target.checked) setSelectedRows(new Set(filteredRows.map((_, i) => i)));
                            else setSelectedRows(new Set());
                          }}
                          className="h-4 w-4 rounded border-[var(--edify-border)] accent-[var(--brand-primary)]"
                        />
                      </th>
                      {(showAllCols
                        ? (schoolsTable?.columns ?? []).map((c) => c.label)
                        : [...COMPACT_COL_LABELS]
                      ).map((label) => (
                        <th
                          key={label}
                          className="whitespace-nowrap px-3 py-2.5 text-[12px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]"
                        >
                          {label}
                        </th>
                      ))}
                      <th className="whitespace-nowrap px-3 py-2.5 text-right text-[12px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--edify-table-divider)]">
                    {filteredRows.map((row: PageRow, idx: number) => {
                      const isExpanded = expandedRow === idx;
                      const schoolCell = row.cells[0];
                      const schoolHref = resolveSafeHref(pagePath, schoolCell?.href ?? '');
                      const colIndices = showAllCols
                        ? row.cells.map((_, i) => i)
                        : [...COMPACT_COL_INDICES];
                      return (
                        <Fragment key={idx}>
                          <tr
                            onClick={() => setExpandedRow(isExpanded ? null : idx)}
                            className="cursor-pointer transition-colors hover:bg-[color-mix(in_srgb,var(--brand-primary)_4%,transparent)]"
                          >
                            <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="checkbox"
                                aria-label={`Select ${schoolCell?.text ?? 'school'}`}
                                checked={selectedRows.has(idx)}
                                onChange={() => toggleSelect(idx)}
                                className="h-4 w-4 rounded border-[var(--edify-border)] accent-[var(--brand-primary)]"
                              />
                            </td>
                            {colIndices.map((ci) => {
                              const cell = row.cells[ci];
                              const text = cell?.text || '—';
                              const href = resolveSafeHref(pagePath, cell?.href ?? '');
                              if (ci === 0) {
                                return (
                                  <td key={ci} className="max-w-[260px] truncate px-3 py-2.5 font-semibold">
                                    {href ? (
                                      <Link
                                        href={href}
                                        onClick={(e) => e.stopPropagation()}
                                        className="text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-sky-400)]"
                                      >
                                        {text}
                                      </Link>
                                    ) : (
                                      text
                                    )}
                                  </td>
                                );
                              }
                              if (ci === 6) {
                                const sc = parseScore(text);
                                return (
                                  <td key={ci} className="whitespace-nowrap px-3 py-2.5">
                                    <span
                                      className={`inline-flex min-w-[44px] items-center justify-center rounded-full px-2.5 py-0.5 text-[12px] font-bold tabular-nums ${ssaPillClass(sc)}`}
                                    >
                                      {text}
                                    </span>
                                  </td>
                                );
                              }
                              if (ci === 9 || ci === 13 || ci === 19) {
                                return (
                                  <td key={ci} className="whitespace-nowrap px-3 py-2.5">
                                    <span
                                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold ${statusPillClass(text)}`}
                                    >
                                      {text}
                                    </span>
                                  </td>
                                );
                              }
                              return (
                                <td key={ci} className="whitespace-nowrap px-3 py-2.5 text-[var(--edify-text)]">
                                  {href ? (
                                    <Link
                                      href={href}
                                      onClick={(e) => e.stopPropagation()}
                                      className="font-medium text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-sky-400)]"
                                    >
                                      {text}
                                    </Link>
                                  ) : (
                                    text
                                  )}
                                </td>
                              );
                            })}
                            <td className="whitespace-nowrap px-3 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                              <div className="inline-flex items-center justify-end gap-1.5">
                                {schoolHref ? (
                                  <Link
                                    href={schoolHref}
                                    title={`Open ${schoolCell?.text}`}
                                    aria-label={`Open ${schoolCell?.text}`}
                                    className="grid h-7 w-7 place-items-center rounded-lg text-[var(--brand-primary)] hover:bg-[var(--brand-primary-soft)]"
                                  >
                                    <Eye className="h-4 w-4" />
                                  </Link>
                                ) : null}
                                <button
                                  type="button"
                                  onClick={() => setExpandedRow(isExpanded ? null : idx)}
                                  aria-label={`Toggle details for ${schoolCell?.text}`}
                                  aria-expanded={isExpanded}
                                  className="grid h-7 w-7 place-items-center rounded-lg text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)]"
                                >
                                  <MoreHorizontal className="h-4 w-4" />
                                </button>
                              </div>
                            </td>
                          </tr>
                          {isExpanded ? (
                            <tr className="bg-[color-mix(in_srgb,var(--brand-primary)_3%,var(--edify-surface))]">
                              <td colSpan={colIndices.length + 2} className="px-5 py-3.5">
                                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[12px] sm:grid-cols-4 lg:grid-cols-6">
                                  {(schoolsTable?.columns ?? []).map((col, ci) => {
                                    const val = row.cells[ci]?.text || '—';
                                    const cHref = resolveSafeHref(pagePath, row.cells[ci]?.href ?? '');
                                    return (
                                      <div key={col.label} className="min-w-0">
                                        <dt className="text-[11px] font-semibold text-[var(--edify-text-muted)]">
                                          {col.label}
                                        </dt>
                                        <dd className="truncate font-semibold text-[var(--edify-text)]">
                                          {cHref ? (
                                            <Link href={cHref} className="text-[var(--brand-primary-text)] hover:underline">
                                              {val}
                                            </Link>
                                          ) : (
                                            val
                                          )}
                                        </dd>
                                      </div>
                                    );
                                  })}
                                </dl>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyStatePanel
                title="No Core Schools match these filters"
                description={schoolsTable?.emptyMessage || 'Try broadening your filters or choosing a different fiscal year.'}
              />
            )}

            {schoolsTable?.pager ? (
              <Pager
                pager={{
                  ...schoolsTable.pager,
                  pages: schoolsTable.pager.pages.map((p) => ({
                    ...p,
                    href: resolveSafeHref(pagePath, p.href),
                  })),
                }}
              />
            ) : null}
          </section>
        </>
      ) : (
        /* Non-Schools tabs (Groups, Attention, Recommendations, Champion Readiness, Visits, Trainings) */
        <div className="space-y-4">
          <FeedBlocks
            blocks={nonSchoolTabBlocks}
            pagePath={pagePath}
            drawerHref={drawerHref}
            selectable={false}
          />
        </div>
      )}
    </div>
  );
}
