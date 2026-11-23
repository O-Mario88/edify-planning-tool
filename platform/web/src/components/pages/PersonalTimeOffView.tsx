'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, useTransition } from 'react';
import { EdifyDatePicker } from '@/components/ui/EdifyDatePicker';
import {
  Baby,
  BarChart3,
  BriefcaseMedical,
  Calendar,
  CalendarDays,
  CheckCircle2,
  Clock,
  Layers,
  PieChart,
  Plus,
  RefreshCw,
  ShieldCheck,
  User,
  Users,
  X,
} from 'lucide-react';

import { submitLeaveRequestAction } from '@/app/(app)/personal-time-off/actions';
import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import type { PageBlock, PageTable } from '@/gen/edify/screens/v1/page_pb';

import { Badge } from '../blocks/Badge';
import { FeedBlocks } from '../page/FeedBlocks';
import {
  DonutChart,
  EDIFY_BTN_OUTLINE,
  EDIFY_BTN_PRIMARY,
  EmptyStatePanel,
  KpiStatCard,
  MonthlyBarChart,
  PageHeroHeader,
  findAllLinkTabs,
  findAllPanels,
  findAllSegments,
  findAllStrips,
  parseLeadingNumber,
  resolveSafeHref,
} from './EdifyDashboardChrome';

const FY_MONTHS = ['Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep'] as const;

function parseAllocationHelper(helper: string): { allocated: number; used: number } {
  const ofMatch = helper.match(/of\s+(\d+(?:\.\d+)?)/i);
  const usedMatch = helper.match(/(\d+(?:\.\d+)?)\s+used/i);
  const usedColon = helper.match(/used:\s*(\d+(?:\.\d+)?)/i);
  const allocColon = helper.match(/allocated:\s*(\d+(?:\.\d+)?)/i);
  return {
    allocated: Number(allocColon?.[1] ?? ofMatch?.[1] ?? 0),
    used: Number(usedColon?.[1] ?? usedMatch?.[1] ?? 0),
  };
}

function monthIndexFromDateText(text: string): number {
  const low = text.toLowerCase();
  const names = ['oct', 'nov', 'dec', 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep'];
  for (let i = 0; i < names.length; i += 1) {
    if (low.includes(names[i]!)) return i;
  }
  const iso = text.match(/\d{4}-(\d{2})-\d{2}/);
  if (iso) {
    const m = Number(iso[1]);
    if (m >= 1 && m <= 12) return (m + 2) % 12; // Oct=10 -> 0
  }
  return -1;
}

const BALANCE_STYLES = [
  { tone: 'brand' as const, icon: CalendarDays },
  { tone: 'success' as const, icon: BriefcaseMedical },
  { tone: 'purple' as const, icon: Baby },
  { tone: 'warning' as const, icon: User },
] as const;

export function PersonalTimeOffView({
  answer,
  pagePath,
  drawerHref,
}: {
  readonly answer: GetPageResponse;
  readonly pagePath: string;
  readonly drawerHref: string;
}) {
  const linkTabsList = findAllLinkTabs(answer.blocks);
  const strips = findAllStrips(answer.blocks);
  const segmentsList = findAllSegments(answer.blocks);
  const panels = findAllPanels(answer.blocks);

  const mainTabs = linkTabsList[0];
  const activeTabLabel = mainTabs?.tabs.find((t) => t.active)?.label ?? 'My Leave';
  const isMyLeaveTab = /my leave/i.test(activeTabLabel) || !mainTabs;

  const overviewStrip = strips[0];
  const balanceStrip = strips[1];

  const overviewMetrics = overviewStrip?.metrics ?? [];
  const kpiAvailable = overviewMetrics[0] ?? { label: 'Days Available', value: '0', helper: 'Used: 0 · Allocated: 0' };
  const kpiPending = overviewMetrics[1] ?? { label: 'Pending Requests', value: '0', helper: '' };
  const kpiTeamAway = overviewMetrics[2] ?? { label: 'Team Away Today', value: '0', helper: '' };
  const kpiHandovers = overviewMetrics[3] ?? { label: 'Active Handovers', value: '0', helper: '' };

  // Compute real Annual Allocation & Used / Remaining for Donut Chart
  const portfolio = (() => {
    const availableNum = parseLeadingNumber(kpiAvailable.value);
    const fromHelper = parseAllocationHelper(kpiAvailable.helper);
    let allocated = fromHelper.allocated;
    let used = fromHelper.used;
    if (allocated === 0 && balanceStrip && balanceStrip.metrics.length > 0) {
      for (const m of balanceStrip.metrics) {
        const parsed = parseAllocationHelper(m.helper);
        allocated += parsed.allocated || parseLeadingNumber(m.value);
        used += parsed.used;
      }
    }
    if (allocated === 0) allocated = availableNum + used;
    const remaining = Math.max(0, allocated - used);
    const usedPct = allocated > 0 ? Math.round((used / allocated) * 100) : 0;
    const remPct = allocated > 0 ? 100 - usedPct : 0;
    return { allocated, used, remaining, usedPct, remPct };
  })();

  const leaveSegments = segmentsList[0]?.segments ?? [];
  const defaultSegIdx = Math.max(
    0,
    leaveSegments.findIndex((s) => s.active),
  );
  const [activeSegIdx, setActiveSegIdx] = useState(defaultSegIdx);
  const activeSeg = leaveSegments[activeSegIdx] ?? leaveSegments[0];

  const activeTable: PageTable | undefined = (() => {
    for (const b of activeSeg?.blocks ?? []) {
      if (b.kind.case === 'table') return b.kind.value;
    }
    return undefined;
  })();

  // Compute monthly leave usage bars from real Go leave rows (All segment)
  const monthlyUsage = (() => {
    const taken = Array<number>(12).fill(0);
    const planned = Array<number>(12).fill(0);
    const allSeg = leaveSegments.find((s) => /all/i.test(s.label)) ?? leaveSegments[0];
    let tbl: PageTable | undefined;
    for (const b of allSeg?.blocks ?? []) {
      if (b.kind.case === 'table') {
        tbl = b.kind.value;
        break;
      }
    }
    for (const row of tbl?.rows ?? []) {
      const startText = row.cells[1]?.text || row.cells[0]?.text || '';
      const durText = row.cells.find((c) => /day/i.test(c.text) || /^\d+(\.\d+)?$/.test(c.text.trim()))?.text ?? '1';
      const statusText = row.cells.map((c) => c.text.toLowerCase()).join(' ');
      const mIdx = monthIndexFromDateText(startText);
      const days = Math.max(1, parseLeadingNumber(durText));
      if (mIdx >= 0 && mIdx < 12) {
        if (statusText.includes('approv') || statusText.includes('pending') || statusText.includes('upcoming')) {
          planned[mIdx] = (planned[mIdx] ?? 0) + days;
        } else {
          taken[mIdx] = (taken[mIdx] ?? 0) + days;
        }
      }
    }
    return { taken, planned };
  })();

  // Policy link from Go panels if present
  const policyHref = (() => {
    for (const p of panels) {
      for (const item of p.items) {
        if (item.kind.case === 'links') {
          const found = item.kind.value.links.find((l) => /polic/i.test(l.text));
          if (found) return resolveSafeHref(pagePath, found.href);
        }
      }
    }
    return '/leave/policies';
  })();

  const router = useRouter();
  const [showRequestForm, setShowRequestForm] = useState(false);
  const [requestNotice, setRequestNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [isPending, startTransition] = useTransition();

  const requestAction = answer.header?.actions.find((a) => a.primary) ?? answer.header?.actions[0];

  function handleLeaveSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    const values: Record<string, string> = {};
    for (const [k, v] of fd.entries()) {
      if (typeof v === 'string') values[k] = v;
    }
    setRequestNotice(null);
    startTransition(async () => {
      const res = await submitLeaveRequestAction(values);
      setRequestNotice({ ok: res.ok, text: res.message });
      if (res.ok) {
        setShowRequestForm(false);
        router.refresh();
      }
    });
  }

  const nonMyLeaveBlocks = (() => {
    const idx = answer.blocks.findIndex((b) => b.kind.case === 'linkTabs');
    if (idx < 0) return [] as PageBlock[];
    return answer.blocks.slice(idx + 1);
  })();

  const tabIcon = (label: string) => {
    const low = label.toLowerCase();
    if (low.includes('coverage')) return Users;
    if (low.includes('holiday') || low.includes('blackout')) return CalendarDays;
    return User;
  };

  const realRows = activeTable?.rows ?? [];

  return (
    <div className="mx-auto max-w-[1440px] space-y-4 px-4 pb-20 pt-4 sm:px-6 lg:pb-10" data-page={pagePath}>
      <PageHeroHeader
        eyebrow={answer.header?.eyebrow || 'Reference'}
        title={answer.header?.title || 'Personal Time Off'}
        description={
          answer.header?.description ||
          'Plan time away with confidence, protect delivery, and keep every handover accountable.'
        }
        icon={<Calendar className="h-5 w-5" />}
        actions={
          <>
            <a href="/exports/leave_requests" download className={EDIFY_BTN_OUTLINE}>
              <span>Export CSV</span>
            </a>
            <a href="/exports/leave_requests?format=xlsx" download className={EDIFY_BTN_OUTLINE}>
              <span>Excel</span>
            </a>
            <a href="/exports/leave_requests?format=pdf" download className={EDIFY_BTN_OUTLINE}>
              <span>PDF</span>
            </a>
            <button type="button" onClick={() => setShowRequestForm((v) => !v)} className={EDIFY_BTN_PRIMARY}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              <span>{requestAction?.label || 'Request Leave'}</span>
            </button>
          </>
        }
      />

      {requestNotice ? (
        <p
          role="status"
          className={`rounded-[10px] border px-4 py-2.5 text-[13px] font-semibold ${
            requestNotice.ok
              ? 'border-[var(--edify-success-border)] bg-[var(--edify-success-light)] text-[var(--edify-success-text)]'
              : 'border-[var(--edify-danger-border)] bg-[var(--edify-danger-light)] text-[var(--edify-danger-text)]'
          }`}
        >
          {requestNotice.text}
        </p>
      ) : null}

      {showRequestForm ? (
        <form
          onSubmit={handleLeaveSubmit}
          className="rounded-[16px] border border-[var(--brand-primary-border)] bg-[var(--edify-card-surface)] p-5 shadow-sm"
        >
          <div className="mb-3 flex items-center justify-between border-b border-[var(--edify-table-divider)] pb-2.5">
            <div>
              <h2 className="text-[15px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                Request Personal Time Off
              </h2>
              <p className="text-[12px] text-[var(--edify-text-muted)]">
                Submitted directly to the Go gateway and recorded in the tamper-evident audit chain.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowRequestForm(false)}
              aria-label="Close leave request form"
              className="rounded-lg p-1.5 text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="space-y-1">
              <span className="block text-[12px] font-semibold text-[var(--edify-text)]">Leave Type</span>
              <select
                name="leave_type"
                defaultValue="annual"
                className="h-9 w-full rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px] text-[var(--edify-text)]"
              >
                <option value="annual">Personal Time Off</option>
                <option value="sick">Sick Leave</option>
                <option value="maternity">Maternity Leave</option>
                <option value="paternity">Paternity Leave</option>
                <option value="bereavement">Bereavement Leave</option>
              </select>
            </label>
            <div className="space-y-1">
              <span className="block text-[12px] font-semibold text-[var(--edify-text)]">Start Date *</span>
              <EdifyDatePicker
                name="start_date"
                label="Start Date"
                required
                size="sm"
                policy={{ mode: 'free' }}
              />
            </div>
            <div className="space-y-1">
              <span className="block text-[12px] font-semibold text-[var(--edify-text)]">End Date *</span>
              <EdifyDatePicker
                name="end_date"
                label="End Date"
                required
                size="sm"
                policy={{ mode: 'free' }}
              />
            </div>
            <label className="space-y-1 sm:col-span-2">
              <span className="block text-[12px] font-semibold text-[var(--edify-text)]">Reason</span>
              <input
                type="text"
                name="reason"
                placeholder="Brief reason for your leave request"
                className="h-9 w-full rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px] text-[var(--edify-text)]"
              />
            </label>
            <label className="space-y-1">
              <span className="block text-[12px] font-semibold text-[var(--edify-text)]">Handover Notes</span>
              <input
                type="text"
                name="handover_notes"
                placeholder="Who covers your clusters/schools"
                className="h-9 w-full rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px] text-[var(--edify-text)]"
              />
            </label>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={() => setShowRequestForm(false)} className={EDIFY_BTN_OUTLINE}>
              Cancel
            </button>
            <button type="submit" disabled={isPending} className={EDIFY_BTN_PRIMARY}>
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              <span>{isPending ? 'Submitting…' : 'Submit Leave Request'}</span>
            </button>
          </div>
        </form>
      ) : null}

      {/* Top Navigation Tabs (My Leave | Coverage | Holidays & Blackouts) */}
      {mainTabs && mainTabs.tabs.length > 0 ? (
        <nav aria-label="Leave views" className="flex flex-wrap items-center gap-1.5">
          {mainTabs.tabs.map((tab) => {
            const IconComp = tabIcon(tab.label);
            const href = resolveSafeHref(pagePath, tab.href) || pagePath;
            return (
              <Link
                key={tab.label}
                href={href}
                aria-current={tab.active ? 'page' : undefined}
                className={`inline-flex items-center gap-2 rounded-[10px] px-3.5 py-2 text-[13px] font-semibold transition-colors ${
                  tab.active
                    ? 'bg-[var(--brand-primary)] text-white shadow-xs'
                    : 'border border-[var(--edify-border)] bg-[var(--edify-card-surface)] text-[var(--edify-text-muted)] hover:border-[var(--brand-primary-border)] hover:text-[var(--brand-primary-text)]'
                }`}
              >
                <IconComp className="h-3.5 w-3.5" aria-hidden="true" />
                <span>{tab.label}</span>
              </Link>
            );
          })}
        </nav>
      ) : null}

      {isMyLeaveTab ? (
        <>
          {/* Performance Overview + 4 KPI Cards */}
          <section aria-label="Leave performance overview" className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                <h2 className="text-[15px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                  Performance Overview
                </h2>
              </div>
              <span className="text-[11.5px] font-medium text-[var(--edify-text-muted)]">
                FY 2027 · Live Go balances
              </span>
            </div>

            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
              <KpiStatCard
                label={kpiAvailable.label}
                value={kpiAvailable.value}
                helper={kpiAvailable.helper || `Used: ${portfolio.used} · Allocated: ${portfolio.allocated}`}
                tone="brand"
                icon={<Calendar className="h-5 w-5" />}
                watermark={<Calendar className="h-14 w-14 text-[var(--brand-primary)]" />}
              />
              <KpiStatCard
                label={kpiPending.label}
                value={kpiPending.value}
                helper={kpiPending.helper || undefined}
                tone="warning"
                icon={<Clock className="h-5 w-5" />}
                watermark={<Clock className="h-14 w-14 text-[var(--edify-warning)]" />}
              />
              <KpiStatCard
                label={kpiTeamAway.label}
                value={kpiTeamAway.value}
                helper={kpiTeamAway.helper || undefined}
                tone="purple"
                icon={<Users className="h-5 w-5" />}
                watermark={<Users className="h-14 w-14 text-[var(--edify-purple)]" />}
              />
              <KpiStatCard
                label={kpiHandovers.label}
                value={kpiHandovers.value}
                helper={kpiHandovers.helper || undefined}
                tone="success"
                icon={<RefreshCw className="h-5 w-5" />}
                watermark={<RefreshCw className="h-14 w-14 text-[var(--edify-success)]" />}
              />
            </div>
          </section>

          {/* 3-Column Portfolio / Guidance & Policy / Usage Trend */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {/* Leave Balance Portfolio */}
            <section className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)]">
              <div className="mb-3 flex items-start gap-2">
                <PieChart className="mt-0.5 h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                <div>
                  <h3 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                    Leave Balance Portfolio
                  </h3>
                  <p className="text-[11.5px] text-[var(--edify-text-muted)]">Remaining / annual allocation</p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <DonutChart
                  size={122}
                  strokeWidth={16}
                  centerValue={String(portfolio.allocated)}
                  centerLabel="Days (Annual)"
                  slices={[
                    { label: 'Used', value: portfolio.used, color: 'var(--brand-primary)' },
                    { label: 'Remaining', value: portfolio.remaining, color: 'var(--edify-sky-100, #bdd8e9)' },
                  ]}
                />
                <div className="flex-1 space-y-2.5 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-semibold text-[var(--edify-text)]">
                      <span className="h-2.5 w-2.5 rounded-[3px] bg-[var(--brand-primary)]" />
                      Used
                    </span>
                    <span className="font-bold tabular-nums text-[var(--edify-text)]">
                      {portfolio.used} days ({portfolio.usedPct}%)
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-semibold text-[var(--edify-text)]">
                      <span className="h-2.5 w-2.5 rounded-[3px] bg-[var(--edify-sky-100,#bdd8e9)]" />
                      Remaining
                    </span>
                    <span className="font-bold tabular-nums text-[var(--edify-text)]">
                      {portfolio.remaining} days ({portfolio.remPct}%)
                    </span>
                  </div>
                  <div className="flex items-center justify-between border-t border-[var(--edify-table-divider)] pt-2">
                    <span className="inline-flex items-center gap-1.5 text-[var(--edify-text-muted)]">
                      <Calendar className="h-3.5 w-3.5" aria-hidden="true" />
                      Annual Allocation
                    </span>
                    <span className="font-extrabold tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                      {portfolio.allocated} days
                    </span>
                  </div>
                </div>
              </div>
            </section>

            {/* Leave Guidance & Policy */}
            <section className="flex flex-col justify-between rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)]">
              <div>
                <div className="mb-3 flex items-start gap-2">
                  <ShieldCheck className="mt-0.5 h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                  <div>
                    <h3 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                      Leave Guidance &amp; Policy
                    </h3>
                    <p className="text-[11.5px] text-[var(--edify-text-muted)]">
                      Review your balance and team calendar before requesting leave.
                    </p>
                  </div>
                </div>
                <ul className="space-y-2.5 text-[12.5px] font-medium text-[var(--edify-text)]">
                  {[
                    'Check your available leave balance.',
                    'Confirm team coverage and handover.',
                    'Follow the leave policy and approval workflow.',
                  ].map((line) => (
                    <li key={line} className="flex items-center gap-2.5">
                      <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-[var(--edify-success-light)] text-[var(--edify-success-text)]">
                        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                      </span>
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <Link
                href={policyHref || '/leave/policies'}
                className="mt-4 flex w-full items-center justify-center rounded-[10px] border border-[var(--brand-primary-border)] bg-[var(--brand-primary-soft)] px-3 py-2 text-[12.5px] font-bold text-[var(--brand-primary-text)] transition-colors hover:bg-[var(--brand-primary)] hover:text-white"
              >
                View Leave Policy →
              </Link>
            </section>

            {/* Leave Usage Trend */}
            <section className="rounded-[14px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)]">
              <div className="mb-2 flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                <h3 className="text-[14px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                  Leave Usage Trend (FY 2027)
                </h3>
              </div>
              <MonthlyBarChart
                labels={FY_MONTHS}
                primary={monthlyUsage.taken}
                secondary={monthlyUsage.planned}
                primaryColor="var(--brand-primary)"
                secondaryColor="var(--edify-sky-400, #7bbde8)"
              />
              <div className="mt-1.5 flex items-center justify-center gap-4 text-[11px] font-semibold text-[var(--edify-text-muted)]">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-[3px] bg-[var(--brand-primary)]" />
                  Days Taken
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-[3px] bg-[var(--edify-sky-400,#7bbde8)]" />
                  Planned / Approved
                </span>
              </div>
            </section>
          </div>

          {/* Balance Breakdown Cards (Personal Time Off, Sick, Maternity, Paternity) */}
          {balanceStrip && balanceStrip.metrics.length > 0 ? (
            <section aria-label="Leave balance breakdown" className="space-y-3">
              <div className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                <h2 className="text-[15px] font-extrabold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                  {balanceStrip.title || 'Leave Balances'}
                </h2>
              </div>
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
                {balanceStrip.metrics.map((m, idx) => {
                  const cfg = BALANCE_STYLES[idx % BALANCE_STYLES.length]!;
                  const IconComp = cfg.icon;
                  return (
                    <KpiStatCard
                      key={m.label}
                      label={m.label}
                      value={m.value}
                      helper={m.helper || undefined}
                      tone={cfg.tone}
                      icon={<IconComp className="h-5 w-5" />}
                    />
                  );
                })}
              </div>
            </section>
          ) : null}

          {/* Upcoming / Past / All Leave Requests Table */}
          <section className="overflow-hidden rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-xs)]">
            <div role="tablist" aria-label="Leave requests" className="flex flex-wrap items-center gap-1.5 border-b border-[var(--edify-table-divider)] px-4 py-3">
              {(leaveSegments.length > 0
                ? leaveSegments
                : [
                    { label: 'Upcoming (0)', count: '', active: true, blocks: [] },
                    { label: 'Past (0)', count: '', active: false, blocks: [] },
                    { label: 'All (0)', count: '', active: false, blocks: [] },
                  ]
              ).map((seg, idx) => {
                const active = idx === activeSegIdx;
                const SegIcon = idx === 0 ? Calendar : idx === 1 ? Clock : Layers;
                return (
                  <button
                    key={seg.label}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setActiveSegIdx(idx)}
                    className={`inline-flex items-center gap-1.5 rounded-[9px] px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors ${
                      active
                        ? 'bg-[var(--brand-primary)] text-white shadow-xs'
                        : 'text-[var(--edify-text-muted)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)]'
                    }`}
                  >
                    <SegIcon className="h-3.5 w-3.5" aria-hidden="true" />
                    <span>
                      {seg.label}
                      {seg.count ? ` (${seg.count})` : ''}
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-[12.5px]">
                <thead>
                  <tr className="border-b border-[var(--edify-table-divider)] bg-[color-mix(in_srgb,var(--brand-primary)_4%,var(--edify-surface))]">
                    <th className="w-10 px-4 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                      #
                    </th>
                    {(
                      activeTable?.columns.map((c) => c.label) ?? [
                        'Leave Type',
                        'Start Date',
                        'End Date',
                        'Duration (Days)',
                        'Status',
                        'Handover',
                        'Actions',
                      ]
                    ).map((col) => (
                      <th
                        key={col}
                        className="whitespace-nowrap px-4 py-2.5 text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                {realRows.length > 0 ? (
                  <tbody className="divide-y divide-[var(--edify-table-divider)]">
                    {realRows.map((row, idx) => (
                      <tr
                        key={idx}
                        className="transition-colors hover:bg-[color-mix(in_srgb,var(--brand-primary)_4%,transparent)]"
                      >
                        <td className="px-4 py-3 font-semibold tabular-nums text-[var(--edify-text-muted)]">
                          {idx + 1}
                        </td>
                        {row.cells.map((cell, ci) => {
                          const href = resolveSafeHref(pagePath, cell.href);
                          return (
                            <td key={ci} className="whitespace-nowrap px-4 py-3 text-[var(--edify-text)]">
                              {cell.badge ? (
                                <Badge tone={cell.tone}>{cell.text}</Badge>
                              ) : href ? (
                                <Link
                                  href={href}
                                  className="font-semibold text-[var(--brand-primary-text)] hover:underline"
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
                icon="calendar"
                title="No leave requests yet"
                description={
                  activeTable?.emptyMessage ||
                  'When you submit a request, its approval and coverage status will appear here.'
                }
                action={
                  <button
                    type="button"
                    onClick={() => setShowRequestForm(true)}
                    className="inline-flex items-center gap-2 rounded-[10px] border border-[var(--brand-primary)] bg-[var(--edify-card-surface)] px-4 py-2 text-[13px] font-semibold text-[var(--brand-primary-text)] transition-colors hover:bg-[var(--brand-primary-soft)] dark:text-[var(--edify-sky-400)]"
                  >
                    <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                    <span>Request Leave</span>
                  </button>
                }
              />
            ) : null}
          </section>
        </>
      ) : (
        <div className="space-y-4">
          <FeedBlocks
            blocks={nonMyLeaveBlocks}
            pagePath={pagePath}
            drawerHref={drawerHref}
            selectable={false}
          />
        </div>
      )}
    </div>
  );
}
