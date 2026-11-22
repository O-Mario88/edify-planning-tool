'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  ClipboardList,
  Clock,
  Filter,
  Layers,
  Send,
  User,
  Users,
  X,
  XCircle,
} from 'lucide-react';

import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import type { PageBlock, PageRow, PageTable } from '@/gen/edify/screens/v1/page_pb';

import { Badge } from '../blocks/Badge';
import {
  EDIFY_BTN_OUTLINE,
  EDIFY_BTN_PRIMARY,
  EdifyClipboardIllustration,
  EmptyStatePanel,
  KpiStatCard,
  PageHeroHeader,
  findForm,
  resolveSafeHref,
} from './EdifyDashboardChrome';

interface Bucket {
  readonly key: string;
  readonly label: string;
  readonly columns: readonly string[];
  readonly rows: readonly PageRow[];
  readonly emptyText: string;
}

function classifyStatus(row: PageRow): 'open' | 'review' | 'resolved' | 'returned' {
  const joined = row.cells.map((c) => c.text.toLowerCase()).join(' ');
  if (joined.includes('return') || joined.includes('more info') || joined.includes('clarif')) return 'returned';
  if (joined.includes('resolv') || joined.includes('approv') || joined.includes('closed') || joined.includes('decided')) return 'resolved';
  if (joined.includes('review') || joined.includes('pending') || joined.includes('progress') || joined.includes('await')) return 'review';
  return 'open';
}

function extractBuckets(blocks: readonly PageBlock[]): Bucket[] {
  const buckets: Bucket[] = [];
  let currentHeading = '';
  for (const block of blocks) {
    if (block.kind.case === 'section') {
      currentHeading = block.kind.value;
    } else if (block.kind.case === 'table') {
      const t: PageTable = block.kind.value;
      const title = t.title || currentHeading || 'Escalations';
      buckets.push({
        key: title.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
        label: title,
        columns: t.columns.map((c) => c.label),
        rows: t.rows,
        emptyText: t.emptyMessage || 'No escalations in this view.',
      });
      currentHeading = '';
    } else if (block.kind.case === 'empty') {
      const title = currentHeading || 'Raised by You';
      buckets.push({
        key: title.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
        label: title,
        columns: [],
        rows: [],
        emptyText: block.kind.value,
      });
      currentHeading = '';
    }
  }
  return buckets;
}

const DEFAULT_COLUMNS = [
  '#',
  'Date Raised',
  'Subject / Issue',
  'Category',
  'School / Cluster',
  'Status',
  'Programme Lead Action',
  'Last Update',
  'Actions',
] as const;

export function EscalationsView({
  answer,
  pagePath,
  drawerHref,
}: {
  readonly answer: GetPageResponse;
  readonly pagePath: string;
  readonly drawerHref: string;
}) {
  const form = findForm(answer.blocks);
  const buckets = useMemo(() => extractBuckets(answer.blocks), [answer.blocks]);

  const raisedBucket = useMemo(
    () => buckets.find((b) => /raised by you/i.test(b.label)),
    [buckets],
  );
  const teamBuckets = useMemo(
    () => buckets.filter((b) => b !== raisedBucket && !/recently decided/i.test(b.label)),
    [buckets, raisedBucket],
  );
  const decidedBucket = useMemo(
    () => buckets.find((b) => /recently decided/i.test(b.label)),
    [buckets],
  );

  const allRows = useMemo(() => {
    const out: { row: PageRow; columns: readonly string[]; bucketLabel: string }[] = [];
    for (const b of buckets) {
      for (const r of b.rows) {
        out.push({ row: r, columns: b.columns, bucketLabel: b.label });
      }
    }
    return out;
  }, [buckets]);

  const counts = useMemo(() => {
    let open = 0;
    let inReview = 0;
    let resolved = 0;
    let returned = 0;
    for (const item of allRows) {
      const st = classifyStatus(item.row);
      if (item.bucketLabel.toLowerCase().includes('decided') || st === 'resolved') resolved += 1;
      else if (st === 'returned') returned += 1;
      else if (item.bucketLabel.toLowerCase().includes('await') || st === 'review') inReview += 1;
      else open += 1;
    }
    return { open, inReview, resolved, returned };
  }, [allRows]);

  const tabs = useMemo(() => {
    const raisedRows = raisedBucket?.rows ?? [];
    const teamRows = teamBuckets.flatMap((b) => b.rows);
    const teamLabel =
      teamBuckets.length === 1 && /awaiting/i.test(teamBuckets[0]?.label ?? '')
        ? 'Awaiting Decision'
        : 'Team Escalations';
    return [
      {
        id: 'raised',
        label: 'Raised by You',
        count: raisedRows.length,
        icon: User,
        columns: raisedBucket?.columns.length ? raisedBucket.columns : DEFAULT_COLUMNS,
        rows: raisedRows,
        emptyText: raisedBucket?.emptyText || 'Nothing is currently escalated to your lead.',
      },
      {
        id: 'team',
        label: teamLabel,
        count: teamRows.length,
        icon: Users,
        columns: teamBuckets[0]?.columns.length ? teamBuckets[0].columns : DEFAULT_COLUMNS,
        rows: teamRows,
        emptyText: teamBuckets[0]?.emptyText || 'No team escalations awaiting action right now.',
      },
      {
        id: 'all',
        label: 'All Escalations',
        count: allRows.length,
        icon: Layers,
        columns: buckets.find((b) => b.columns.length)?.columns ?? DEFAULT_COLUMNS,
        rows: allRows.map((x) => x.row),
        emptyText: decidedBucket?.emptyText || 'No escalations recorded in this period.',
      },
    ];
  }, [allRows, buckets, decidedBucket, raisedBucket, teamBuckets]);

  const [activeTab, setActiveTab] = useState<string>('raised');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showFilterMenu, setShowFilterMenu] = useState(false);
  const [showRaisePanel, setShowRaisePanel] = useState(false);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  const currentTab = tabs.find((t) => t.id === activeTab) ?? tabs[0]!;
  const visibleRows = useMemo(() => {
    if (statusFilter === 'all') return currentTab.rows;
    return currentTab.rows.filter((r) => classifyStatus(r) === statusFilter);
  }, [currentTab.rows, statusFilter]);

  const headerTitle = answer.header?.title || 'Escalations';
  const headerDesc =
    answer.header?.description ||
    'Decisions above your authority, routed to your Programme Lead for review and action.';
  const eyebrow = answer.header?.eyebrow || 'Leadership';
  const raiseTitle = form?.title || 'Escalate an issue to your supervisor';
  const raiseText =
    form?.text ||
    'Use this when something is blocking your schools that you cannot clear yourself — a partner not delivering, a cluster you cannot cover, or a decision your lead has to make.';
  const raiseCta = form?.submitLabel || 'Raise a New Escalation';

  const hasCustomColumns = currentTab.columns !== DEFAULT_COLUMNS && currentTab.rows.length > 0;
  const displayColumns = hasCustomColumns ? ['#', ...currentTab.columns] : DEFAULT_COLUMNS;

  return (
    <div className="mx-auto max-w-[1440px] space-y-4 px-4 pb-20 pt-4 sm:px-6 lg:pb-10" data-page={pagePath}>
      <PageHeroHeader
        eyebrow={eyebrow}
        title={headerTitle}
        description={headerDesc}
        icon={<AlertTriangle className="h-5 w-5" />}
      />

      {/* Hero Escalate Callout Banner */}
      <section
        aria-label={raiseTitle}
        className="relative overflow-hidden rounded-[16px] border border-[color-mix(in_srgb,var(--brand-primary)_22%,var(--edify-border))] px-5 py-4 shadow-[var(--edify-shadow-xs)] sm:px-6 sm:py-5"
        style={{
          background:
            'linear-gradient(108deg, color-mix(in srgb, var(--brand-primary) 9%, var(--edify-card-surface)) 0%, color-mix(in srgb, var(--edify-sky-400, #7bbde8) 14%, var(--edify-card-surface)) 65%, color-mix(in srgb, var(--brand-primary) 5%, var(--edify-card-surface)) 100%)',
        }}
      >
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div className="max-w-2xl space-y-2">
            <h2 className="text-[17px] font-extrabold tracking-[-0.015em] text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
              {raiseTitle}
            </h2>
            <p className="text-[13px] leading-relaxed text-[var(--edify-text-muted)]">{raiseText}</p>
            <div className="pt-1">
              {form ? (
                <button
                  type="button"
                  onClick={() => setShowRaisePanel((prev) => !prev)}
                  className={EDIFY_BTN_PRIMARY}
                >
                  <Send className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>{raiseCta}</span>
                </button>
              ) : (
                <a href={drawerHref} className={EDIFY_BTN_OUTLINE}>
                  <Send className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Open Escalations Queue</span>
                </a>
              )}
            </div>
          </div>

          <div className="max-sm:hidden pr-2">
            <EdifyClipboardIllustration badge="upload" />
          </div>
        </div>

        {/* Inline Raise Escalation Drawer Panel when toggled */}
        {showRaisePanel && form ? (
          <div className="mt-4 rounded-[12px] border border-[var(--brand-primary-border)] bg-[var(--edify-card-surface)] p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between gap-2 border-b border-[var(--edify-border)] pb-2.5">
              <div>
                <h3 className="text-[14px] font-bold text-[var(--edify-text)]">{form.title}</h3>
                <p className="text-[12px] text-[var(--edify-text-muted)]">
                  Complete the fields below or open the full escalation drawer to attach school and cluster context.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowRaisePanel(false)}
                className="rounded-lg p-1.5 text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)]"
                aria-label="Close escalation form"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {form.items.map((item, idx) => {
                if (item.kind.case !== 'field') return null;
                const f = item.kind.value;
                return (
                  <div key={`${f.name}-${idx}`} className={f.kind === 'textarea' ? 'sm:col-span-2' : ''}>
                    <label className="mb-1 block text-[12px] font-semibold text-[var(--edify-text)]">
                      {f.label}
                      {f.required ? <span className="ml-0.5 text-[var(--edify-danger)]">*</span> : null}
                    </label>
                    {f.kind === 'select' ? (
                      <select
                        name={f.name}
                        defaultValue={f.value}
                        className="w-full rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 py-2 text-[13px] text-[var(--edify-text)]"
                      >
                        {f.options.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    ) : f.kind === 'textarea' ? (
                      <textarea
                        name={f.name}
                        rows={3}
                        defaultValue={f.value}
                        placeholder={f.placeholder || f.help}
                        className="w-full rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 py-2 text-[13px] text-[var(--edify-text)]"
                      />
                    ) : (
                      <input
                        type="text"
                        name={f.name}
                        defaultValue={f.value}
                        placeholder={f.placeholder || f.help}
                        className="w-full rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 py-2 text-[13px] text-[var(--edify-text)]"
                      />
                    )}
                    {f.help ? <p className="mt-1 text-[11px] text-[var(--edify-text-muted)]">{f.help}</p> : null}
                  </div>
                );
              })}
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
              <button type="button" onClick={() => setShowRaisePanel(false)} className={EDIFY_BTN_OUTLINE}>
                Cancel
              </button>
              <a href={drawerHref} className={EDIFY_BTN_PRIMARY}>
                <Send className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{raiseCta}</span>
              </a>
            </div>
          </div>
        ) : null}
      </section>

      {/* 4 KPI Stat Cards */}
      <section aria-label="Escalation summary" className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
        <KpiStatCard
          label="Open Escalations"
          value={String(counts.open)}
          tone="brand"
          icon={<ClipboardList className="h-5 w-5" />}
        />
        <KpiStatCard
          label="In Review"
          value={String(counts.inReview)}
          tone="warning"
          icon={<Clock className="h-5 w-5" />}
        />
        <KpiStatCard
          label="Resolved"
          value={String(counts.resolved)}
          tone="success"
          icon={<CheckCircle2 className="h-5 w-5" />}
        />
        <KpiStatCard
          label="Returned / More Info"
          value={String(counts.returned)}
          tone="danger"
          icon={<XCircle className="h-5 w-5" />}
        />
      </section>

      {/* Tabs + Right Filter Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Escalation views" className="flex flex-wrap items-center gap-1.5">
          {tabs.map((tab) => {
            const IconComp = tab.icon;
            const active = tab.id === currentTab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => {
                  setActiveTab(tab.id);
                  setExpandedRow(null);
                }}
                className={`inline-flex items-center gap-2 rounded-[10px] px-3.5 py-2 text-[13px] font-semibold transition-colors ${
                  active
                    ? 'bg-[var(--brand-primary)] text-white shadow-xs'
                    : 'border border-transparent bg-[var(--edify-card-surface)] text-[var(--edify-text-muted)] hover:border-[var(--brand-primary-border)] hover:text-[var(--brand-primary-text)]'
                }`}
              >
                <IconComp className="h-4 w-4" aria-hidden="true" />
                <span>
                  {tab.label}
                  {tab.id === 'raised' || tab.count > 0 ? ` (${tab.count})` : ''}
                </span>
              </button>
            );
          })}
        </div>

        <div className="relative flex flex-wrap items-center gap-2">
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowFilterMenu((v) => !v)}
              className={EDIFY_BTN_OUTLINE}
              aria-expanded={showFilterMenu}
            >
              <Filter className="h-3.5 w-3.5" aria-hidden="true" />
              <span>{statusFilter === 'all' ? 'Filter' : `Status: ${statusFilter}`}</span>
            </button>
            {showFilterMenu ? (
              <div className="absolute right-0 z-20 mt-1.5 w-48 rounded-[12px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-1.5 shadow-lg">
                {[
                  { id: 'all', label: 'All statuses' },
                  { id: 'open', label: 'Open Escalations' },
                  { id: 'review', label: 'In Review' },
                  { id: 'resolved', label: 'Resolved' },
                  { id: 'returned', label: 'Returned / More Info' },
                ].map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => {
                      setStatusFilter(opt.id);
                      setShowFilterMenu(false);
                    }}
                    className={`flex w-full items-center rounded-[8px] px-2.5 py-1.5 text-left text-[12.5px] font-medium ${
                      statusFilter === opt.id
                        ? 'bg-[var(--brand-primary-soft)] font-semibold text-[var(--brand-primary-text)]'
                        : 'text-[var(--edify-text)] hover:bg-[var(--edify-surface-muted)]'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <div className="inline-flex items-center gap-2 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-3.5 py-2 text-[13px] font-semibold text-[var(--edify-text)] shadow-xs">
            <Calendar className="h-3.5 w-3.5 text-[var(--brand-primary)]" aria-hidden="true" />
            <span>This Financial Year (FY 2027)</span>
          </div>
        </div>
      </div>

      {/* Escalations Table Card */}
      <section className="overflow-hidden rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-xs)]">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[13px]">
            <thead>
              <tr className="border-b border-[var(--edify-table-divider)] bg-[color-mix(in_srgb,var(--brand-primary)_4%,var(--edify-surface))]">
                {displayColumns.map((col, idx) => (
                  <th
                    key={`${col}-${idx}`}
                    className="whitespace-nowrap px-4 py-3 text-[12px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            {visibleRows.length > 0 ? (
              <tbody className="divide-y divide-[var(--edify-table-divider)]">
                {visibleRows.map((row, rowIndex) => {
                  const hasDetail = row.details.length > 0 || row.detailBlocks.length > 0;
                  const isOpen = expandedRow === rowIndex;
                  return (
                    <tr
                      key={rowIndex}
                      onClick={hasDetail ? () => setExpandedRow(isOpen ? null : rowIndex) : undefined}
                      className={`transition-colors hover:bg-[color-mix(in_srgb,var(--brand-primary)_4%,transparent)] ${
                        hasDetail ? 'cursor-pointer' : ''
                      }`}
                    >
                      <td className="whitespace-nowrap px-4 py-3 font-semibold tabular-nums text-[var(--edify-text-muted)]">
                        {rowIndex + 1}
                      </td>
                      {row.cells.map((cell, ci) => {
                        const href = resolveSafeHref(pagePath, cell.href);
                        return (
                          <td key={ci} className="px-4 py-3 align-middle text-[var(--edify-text)]">
                            {cell.badge ? (
                              <Badge tone={cell.tone}>{cell.text}</Badge>
                            ) : href ? (
                              <Link
                                href={href}
                                onClick={(e) => e.stopPropagation()}
                                className="font-semibold text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-sky-400)]"
                              >
                                {cell.text}
                              </Link>
                            ) : cell.actions.length > 0 ? (
                              <div className="flex flex-wrap items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                                {cell.actions.map((act, ai) => (
                                  <a
                                    key={ai}
                                    href={act.drawer ? drawerHref : resolveSafeHref(pagePath, act.href) || drawerHref}
                                    className="rounded-md border border-[var(--brand-primary-border)] bg-[var(--brand-primary-soft)] px-2.5 py-1 text-[12px] font-semibold text-[var(--brand-primary-text)] hover:bg-[var(--brand-primary)] hover:text-white"
                                  >
                                    {act.label}
                                  </a>
                                ))}
                              </div>
                            ) : (
                              <span className={cell.strong ? 'font-semibold' : ''}>{cell.text || '—'}</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            ) : null}
          </table>
        </div>

        {visibleRows.length === 0 ? (
          <EmptyStatePanel
            title="No escalations yet"
            description={currentTab.emptyText}
            action={
              form ? (
                <button
                  type="button"
                  onClick={() => setShowRaisePanel(true)}
                  className="inline-flex items-center gap-2 rounded-[10px] border border-[var(--brand-primary)] bg-[var(--edify-card-surface)] px-4 py-2 text-[13px] font-semibold text-[var(--brand-primary-text)] transition-colors hover:bg-[var(--brand-primary-soft)] dark:text-[var(--edify-sky-400)]"
                >
                  <Send className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Raise a New Escalation</span>
                </button>
              ) : undefined
            }
          />
        ) : null}
      </section>
    </div>
  );
}
