'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  Clock,
  Columns3,
  Download,
  FileText,
  MoreHorizontal,
  RotateCcw,
  Target,
  XCircle,
} from 'lucide-react';

import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import type { PageRow } from '@/gen/edify/screens/v1/page_pb';

import { Pager } from '../blocks/Pager';
import {
  EDIFY_BTN_OUTLINE,
    EdifyClipboardIllustration,
  EmptyStatePanel,
  KpiStatCard,
  PageHeroHeader,
  findAllLinkTabs,
  findAllPanels,
  findAllTables,
  findFilters,
  resolveSafeHref,
} from './EdifyDashboardChrome';

function initialsOf(name: string): string {
  const parts = name
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length === 0) return 'ED';
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return `${parts[0]![0] ?? ''}${parts[parts.length - 1]![0] ?? ''}`.toUpperCase();
}

function classifyDecision(row: PageRow): {
  status: 'implemented' | 'pending' | 'reversed';
  impact: 'high' | 'medium';
} {
  const joined = row.cells.map((c) => c.text.toLowerCase()).join(' ');
  const isReversed =
    joined.includes('revers') ||
    joined.includes('cancel') ||
    joined.includes('return') ||
    joined.includes('reject') ||
    joined.includes('denied');
  const isPending =
    joined.includes('pending') ||
    joined.includes('open') ||
    joined.includes('submitted') ||
    joined.includes('draft');
  const isHigh =
    joined.includes('critical') ||
    joined.includes('escalat') ||
    joined.includes('budget') ||
    joined.includes('approv') ||
    joined.includes('high') ||
    joined.includes('partner');
  return {
    status: isReversed ? 'reversed' : isPending ? 'pending' : 'implemented',
    impact: isHigh ? 'high' : 'medium',
  };
}

function statusPillStyle(status: 'implemented' | 'pending' | 'reversed'): { label: string; cls: string } {
  if (status === 'reversed') {
    return {
      label: 'Reversed',
      cls: 'bg-[var(--edify-danger-light)] text-[var(--edify-danger-text)] border border-[var(--edify-danger-border)]',
    };
  }
  if (status === 'pending') {
    return {
      label: 'Pending',
      cls: 'bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)] border border-[var(--edify-warning-border)]',
    };
  }
  return {
    label: 'Implemented',
    cls: 'bg-[var(--edify-success-light)] text-[var(--edify-success-text)] border border-[var(--edify-success-border)]',
  };
}

export function DecisionLogView({
  answer,
  pagePath,
}: {
  readonly answer: GetPageResponse;
  readonly pagePath: string;
}) {
  const router = useRouter();
  const panels = findAllPanels(answer.blocks);
  const filters = findFilters(answer.blocks);
  const linkTabsList = findAllLinkTabs(answer.blocks);
  const tables = findAllTables(answer.blocks);

  const contextPanel = panels[0];
  const groupTabs = linkTabsList[0];
  const mainTable = tables[0];
  const allRows = useMemo(() => mainTable?.rows ?? [], [mainTable]);

  // Extract the 4 context metadata fields from Go's context panel
  const contextFields = useMemo(() => {
    const out: { label: string; value: string }[] = [];
    for (const item of contextPanel?.items ?? []) {
      if (item.kind.case === 'fields') {
        for (const f of item.kind.value.facts) out.push({ label: f.label, value: f.value });
      } else if (item.kind.case === 'rows') {
        for (const r of item.kind.value.rows) out.push({ label: r.label, value: r.value });
      }
    }
    if (out.length > 0) return out.slice(0, 4);
    return [
      { label: 'Decision frame', value: 'What was decided, by whom, on what record, and with what stated reason?' },
      { label: 'Evidence', value: 'Tamper-evident audit chain' },
      { label: 'Freshness', value: 'Selected lookback window' },
      { label: 'Confidence', value: 'Verified hash chain' },
    ];
  }, [contextPanel]);

  const [typeFilter, setTypeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [authorFilter, setAuthorFilter] = useState('all');
  const [impactFilter, setImpactFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showFullReason, setShowFullReason] = useState(false);

  // Discover distinct Decision Types & Authors from the Go rows
  const { typeOptions, authorOptions } = useMemo(() => {
    const types = new Set<string>();
    const authors = new Set<string>();
    for (const row of allRows) {
      const grp = row.cells[1]?.text.trim();
      const who = row.cells[3]?.text.trim();
      if (grp && grp !== '—') types.add(grp);
      if (who && who !== '—') authors.add(who);
    }
    return {
      typeOptions: Array.from(types).sort(),
      authorOptions: Array.from(authors).sort(),
    };
  }, [allRows]);

  const filteredRows = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return allRows.filter((row) => {
      const cls = classifyDecision(row);
      if (typeFilter !== 'all' && (row.cells[1]?.text.trim() ?? '') !== typeFilter) return false;
      if (authorFilter !== 'all' && (row.cells[3]?.text.trim() ?? '') !== authorFilter) return false;
      if (statusFilter !== 'all' && cls.status !== statusFilter) return false;
      if (impactFilter !== 'all' && cls.impact !== impactFilter) return false;
      if (q && !row.cells.some((c) => c.text.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [allRows, authorFilter, impactFilter, searchQuery, statusFilter, typeFilter]);

  const stats = useMemo(() => {
    const total = filteredRows.length;
    let implemented = 0;
    let pending = 0;
    let reversed = 0;
    let highImpact = 0;
    for (const row of filteredRows) {
      const c = classifyDecision(row);
      if (c.status === 'implemented') implemented += 1;
      else if (c.status === 'pending') pending += 1;
      else reversed += 1;
      if (c.impact === 'high') highImpact += 1;
    }
    const pct = (n: number) => (total > 0 ? Math.round((n / total) * 100) : 0);
    return {
      total,
      implemented,
      pending,
      reversed,
      highImpact,
      implPct: pct(implemented),
      pendPct: pct(pending),
      revPct: pct(reversed),
      highPct: pct(highImpact),
    };
  }, [filteredRows]);

  const periodFilter = filters?.filters.find((f) => f.name === 'days') ?? filters?.filters[0];

  function handlePeriodChange(value: string) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filters?.hidden ?? {})) {
      if (v) params.set(k, v);
    }
    if (periodFilter) params.set(periodFilter.name, value);
    const qs = params.toString();
    router.push(qs ? `${pagePath}?${qs}` : pagePath);
  }

  function handleClearFilters() {
    setTypeFilter('all');
    setStatusFilter('all');
    setAuthorFilter('all');
    setImpactFilter('all');
    setSearchQuery('');
  }

  function handleExportCsv() {
    const cols = mainTable?.columns.map((c) => c.label) ?? ['Date', 'Decision', 'Record', 'Author', 'Status', 'Reason'];
    const header = cols.map((c) => `"${c.replace(/"/g, '""')}"`).join(',');
    const body = filteredRows
      .map((r) => r.cells.map((c) => `"${c.text.replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const blob = new Blob([`${header}\n${body}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'decision-log.csv';
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-[1440px] space-y-4 px-4 pb-20 pt-4 sm:px-6 lg:pb-10" data-page={pagePath}>
      <PageHeroHeader
        eyebrow={answer.header?.eyebrow || 'Oversight'}
        title={answer.header?.title || 'Decision Log'}
        description={
          answer.header?.description ||
          'Track and review key decisions made, including the context, evidence, and impact.'
        }
        icon={<FileText className="h-5 w-5" />}
        actions={
          <>
            <button type="button" onClick={handleExportCsv} className={EDIFY_BTN_OUTLINE}>
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Export Report</span>
            </button>
          </>
        }
      />

      {/* Data Context Banner Card */}
      <section
        aria-label="Data context"
        className="relative overflow-hidden rounded-[16px] border border-[color-mix(in_srgb,var(--brand-primary)_20%,var(--edify-border))] px-5 py-4 shadow-[var(--edify-shadow-xs)]"
        style={{
          background:
            'linear-gradient(108deg, color-mix(in srgb, var(--brand-primary) 7%, var(--edify-card-surface)) 0%, color-mix(in srgb, var(--edify-sky-400, #7bbde8) 12%, var(--edify-card-surface)) 65%, var(--edify-card-surface) 100%)',
        }}
      >
        <div className="flex flex-col items-start justify-between gap-4 lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-1 items-start gap-3.5">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-[10px] bg-[var(--brand-primary-soft)] text-[var(--brand-primary-text)]">
              <Target className="h-5 w-5" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1 space-y-2.5">
              <h2 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                {contextPanel?.title || 'Data context · selected lookback window'}
              </h2>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
                {contextFields.map((f) => (
                  <div key={f.label} className="min-w-0">
                    <dt className="text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text)]">
                      {f.label}
                    </dt>
                    <dd className="text-[12px] leading-snug text-[var(--edify-text-muted)]">{f.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
          <div className="max-lg:hidden shrink-0">
            <EdifyClipboardIllustration badge="check" />
          </div>
        </div>
      </section>

      {/* Filter Bar Card */}
      <section
        aria-label="Decision filters"
        className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-3.5 shadow-[var(--edify-shadow-xs)]"
      >
        <div className="flex flex-wrap items-end gap-3">
          {periodFilter ? (
            <label className="min-w-[150px] flex-1 space-y-1">
              <span className="block text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                Period
              </span>
              <div className="relative">
                <select
                  name={periodFilter.name}
                  value={periodFilter.value}
                  onChange={(e) => handlePeriodChange(e.target.value)}
                  className="h-9 w-full rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] pr-3 text-[12.5px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none"
                >
                  {periodFilter.options.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            </label>
          ) : null}

          <label className="min-w-[140px] flex-1 space-y-1">
            <span className="block text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
              Decision Type
            </span>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="h-9 w-full rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[12.5px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none"
            >
              <option value="all">All Types</option>
              {typeOptions.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>

          <label className="min-w-[140px] flex-1 space-y-1">
            <span className="block text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
              Status
            </span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="h-9 w-full rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[12.5px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none"
            >
              <option value="all">All Statuses</option>
              <option value="implemented">Implemented</option>
              <option value="pending">Pending</option>
              <option value="reversed">Reversed</option>
            </select>
          </label>

          <label className="min-w-[140px] flex-1 space-y-1">
            <span className="block text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
              Author
            </span>
            <div className="relative">
              <select
                value={authorFilter}
                onChange={(e) => setAuthorFilter(e.target.value)}
                className="h-9 w-full rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] pr-3 text-[12.5px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none"
              >
                <option value="all">All Authors</option>
                {authorOptions.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
          </label>

          <label className="min-w-[140px] flex-1 space-y-1">
            <span className="block text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
              Impact
            </span>
            <div className="relative">
              <select
                value={impactFilter}
                onChange={(e) => setImpactFilter(e.target.value)}
                className="h-9 w-full rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] pr-3 text-[12.5px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none"
              >
                <option value="all">All Impact Levels</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
              </select>
            </div>
          </label>

          <button type="button" onClick={handleClearFilters} className={`${EDIFY_BTN_OUTLINE} h-9 shrink-0`}>
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Clear Filters</span>
          </button>
        </div>
      </section>

      {/* 5 KPI Progress Cards */}
      <section aria-label="Decision summary metrics" className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-5">
        <KpiStatCard
          label="Total Decisions"
          value={String(stats.total)}
          helper={periodFilter?.options.find((o) => o.value === periodFilter.value)?.label || 'Selected window'}
          tone="brand"
          icon={<FileText className="h-5 w-5" />}
        />
        <KpiStatCard
          label="Implemented"
          value={String(stats.implemented)}
          tone="success"
          icon={<CheckCircle2 className="h-5 w-5" />}
          progress={stats.implPct}
          progressLabel={`${stats.implPct}%`}
        />
        <KpiStatCard
          label="Pending"
          value={String(stats.pending)}
          tone="warning"
          icon={<Clock className="h-5 w-5" />}
          progress={stats.pendPct}
          progressLabel={`${stats.pendPct}%`}
        />
        <KpiStatCard
          label="Reversed"
          value={String(stats.reversed)}
          tone="purple"
          icon={<XCircle className="h-5 w-5" />}
          progress={stats.revPct}
          progressLabel={`${stats.revPct}%`}
        />
        <KpiStatCard
          label="High Impact"
          value={String(stats.highImpact)}
          tone="danger"
          icon={<AlertCircle className="h-5 w-5" />}
          progress={stats.highPct}
          progressLabel={`${stats.highPct}%`}
        />
      </section>

      {/* Decision Table Card */}
      <section className="overflow-hidden rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-xs)]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--edify-table-divider)] px-4 py-3 sm:px-5">
          {/* Group Link Tabs */}
          <nav aria-label="Decision groups" className="flex flex-wrap items-center gap-1">
            {(groupTabs?.tabs ?? [{ label: `All Decisions (${stats.total})`, href: pagePath, active: true }]).map(
              (tab) => {
                const href = resolveSafeHref(pagePath, tab.href) || pagePath;
                return (
                  <Link
                    key={tab.label}
                    href={href}
                    aria-current={tab.active ? 'page' : undefined}
                    className={`rounded-[9px] px-3 py-1.5 text-[12.5px] font-semibold transition-colors ${
                      tab.active
                        ? 'bg-[var(--brand-primary)] text-white shadow-xs'
                        : 'text-[var(--edify-text-muted)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)]'
                    }`}
                  >
                    {tab.label}
                  </Link>
                );
              },
            )}
          </nav>

          <div className="flex flex-wrap items-center gap-2">
            <label className="relative">
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search decisions..."
                className="h-9 w-52 rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] pr-3 text-[12.5px] text-[var(--edify-text)] placeholder:text-[var(--edify-text-muted)] focus:border-[var(--brand-primary)] focus:outline-none sm:w-64"
              />
            </label>
            <button
              type="button"
              onClick={() => setShowFullReason((v) => !v)}
              className={EDIFY_BTN_OUTLINE}
              aria-pressed={showFullReason}
            >
              <Columns3 className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Columns</span>
            </button>
          </div>
        </div>

        {filteredRows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-[12.5px]">
              <thead>
                <tr className="border-b border-[var(--edify-table-divider)] bg-[color-mix(in_srgb,var(--brand-primary)_4%,var(--edify-surface))]">
                  <th className="whitespace-nowrap px-4 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                    Date
                  </th>
                  <th className="whitespace-nowrap px-4 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                    Decision Title
                  </th>
                  <th className="whitespace-nowrap px-4 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                    Context / Record
                  </th>
                  <th className="whitespace-nowrap px-4 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                    Decision / Reason
                  </th>
                  <th className="whitespace-nowrap px-4 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                    Author
                  </th>
                  <th className="whitespace-nowrap px-4 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                    Impact
                  </th>
                  <th className="whitespace-nowrap px-4 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                    Status
                  </th>
                  <th className="whitespace-nowrap px-4 py-2.5 text-right text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--edify-table-divider)]">
                {filteredRows.map((row, idx) => {
                  const dateText = row.cells[0]?.text || '—';
                  const groupOrAction = row.cells[1]?.text || 'Decision';
                  const recordCell = row.cells[2];
                  const authorText = row.cells[3]?.text || 'System';
                  const extraCols = row.cells.slice(4).map((c) => c.text).filter(Boolean);
                  const reasonText = extraCols.join(' · ') || 'Recorded in verified audit chain';
                  const cls = classifyDecision(row);
                  const st = statusPillStyle(cls.status);
                  const recordHref = resolveSafeHref(pagePath, recordCell?.href ?? '');
                  return (
                    <tr
                      key={idx}
                      className="transition-colors hover:bg-[color-mix(in_srgb,var(--brand-primary)_4%,transparent)]"
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-[var(--edify-text-muted)]">
                        <div className="inline-flex items-center gap-1.5">
                          <Calendar className="h-3.5 w-3.5 text-[var(--brand-primary)] opacity-75" aria-hidden="true" />
                          <span className="font-semibold text-[var(--edify-text)]">{dateText}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <p className="font-bold text-[var(--brand-primary-text)] dark:text-[var(--edify-sky-400)]">
                          {groupOrAction}
                        </p>
                        {recordCell?.text ? (
                          <span className="mt-0.5 inline-block rounded bg-[var(--edify-surface-muted)] px-1.5 py-0.5 text-[10.5px] font-semibold text-[var(--edify-text-muted)]">
                            {recordCell.text.slice(0, 28)}
                          </span>
                        ) : null}
                      </td>
                      <td className="max-w-[220px] px-4 py-3 text-[var(--edify-text)]">
                        {recordHref ? (
                          <Link
                            href={recordHref}
                            className="font-medium text-[var(--brand-primary-text)] hover:underline"
                          >
                            {recordCell?.text || '—'}
                          </Link>
                        ) : (
                          <span className="line-clamp-2">{recordCell?.text || '—'}</span>
                        )}
                      </td>
                      <td className="max-w-[260px] px-4 py-3 text-[var(--edify-text-muted)]">
                        <span className={showFullReason ? '' : 'line-clamp-2'}>{reasonText}</span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="inline-flex items-center gap-2">
                          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[var(--brand-primary)] text-[10.5px] font-bold text-white">
                            {initialsOf(authorText)}
                          </span>
                          <span className="font-medium text-[var(--edify-text)]">{authorText}</span>
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold ${
                            cls.impact === 'high'
                              ? 'bg-[var(--edify-success-light)] text-[var(--edify-success-text)] border border-[var(--edify-success-border)]'
                              : 'bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)] border border-[var(--edify-warning-border)]'
                          }`}
                        >
                          {cls.impact === 'high' ? 'High' : 'Medium'}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold ${st.cls}`}>
                          {st.label}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => setShowFullReason((v) => !v)}
                          aria-label="Toggle full decision details"
                          className="grid ml-auto h-7 w-7 place-items-center rounded-lg text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)]"
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyStatePanel
            title="No decisions recorded for these filters"
            description={
              mainTable?.emptyMessage ||
              'Try expanding the lookback window or clearing your active filters.'
            }
          />
        )}

        {mainTable?.pager ? (
          <Pager
            pager={{
              ...mainTable.pager,
              pages: mainTable.pager.pages.map((p) => ({
                ...p,
                href: resolveSafeHref(pagePath, p.href),
              })),
            }}
          />
        ) : null}

        {mainTable?.footnote ? (
          <div className="border-t border-[var(--edify-table-divider)] bg-[var(--edify-surface)] px-4 py-2.5 text-[11.5px] font-medium text-[var(--edify-text-muted)]">
            {mainTable.footnote}
          </div>
        ) : null}
      </section>
    </div>
  );
}
