/**
 * Stage B's preview (docs/migration/177, 179): the Enterprise Design System's
 * tokens and components, and before/after pairs for three phone screens.
 * Each "before" is a real capture of the existing application (Stage A,
 * local development data); each "after" is the proposed layout drawn with
 * the design system and SAMPLE content, to review the structure before any
 * page is rebuilt. Nothing here reads or changes data.
 */
import { Bell, Search } from 'lucide-react';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import {
  Button,
  DataTable,
  EmptyState,
  KpiStat,
  SectionHeader,
  Segmented,
  Skeleton,
  StatusBadge,
  Surface,
  TaskList,
  TaskRow,
} from '@/components/eds';
import type { DataColumn, DataRow } from '@/components/eds';

export const metadata: Metadata = { title: 'Design preview — Edify' };

const SWATCHES = [
  'bg', 'surface', 'surface-sunken', 'surface-selected', 'border', 'border-strong', 'text', 'text-muted',
  'text-subtle', 'primary', 'primary-soft', 'brand-ink', 'focus', 'success', 'warning', 'danger', 'info',
  'chart-1', 'chart-2', 'chart-3', 'chart-4', 'chart-5', 'chart-6',
] as const;

/** The type scale, as Tailwind classes written out whole so they are built. */
const TYPE = [
  ['caption', 'text-ds-caption'],
  ['body', 'text-ds-body'],
  ['control', 'text-ds-control'],
  ['lead', 'text-ds-lead'],
  ['title', 'text-ds-title'],
  ['display', 'text-ds-display'],
  ['figure', 'text-ds-figure'],
] as const;

/** A phone-width frame (375 points) with the top bar and bottom bar the
 *  redesign keeps. */
function Phone({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="w-[375px] max-w-full shrink-0 overflow-hidden rounded-[28px] border border-ds-border-strong bg-ds-bg shadow-ds-overlay">
      <div className="flex h-[52px] items-center justify-between border-b border-ds-border bg-ds-surface px-4">
        <div className="min-w-0">
          <p className="text-ds-caption font-semibold text-ds-text-subtle">Thu 19 Nov · FY2027</p>
          <p className="truncate text-ds-lead font-bold text-ds-text">{title}</p>
        </div>
        <div className="flex items-center gap-1 text-ds-text-muted" aria-hidden="true">
          <span className="grid h-11 w-11 place-items-center">
            <Search size={20} />
          </span>
          <span className="grid h-11 w-11 place-items-center">
            <Bell size={20} />
          </span>
        </div>
      </div>
      <div className="h-[704px] space-y-4 overflow-y-auto p-4">{children}</div>
      <nav className="grid h-[56px] grid-cols-5 border-t border-ds-border bg-ds-surface text-ds-caption font-semibold text-ds-text-subtle">
        {['Today', 'My Plan', 'Schools', 'Messages', 'More'].map((item, i) => (
          <span key={item} className={`grid place-items-center ${i === 0 ? 'text-ds-primary' : ''}`}>
            {item}
          </span>
        ))}
      </nav>
    </div>
  );
}

function Before({ src, alt }: { src: string; alt: string }) {
  return (
    <figure className="w-[375px] max-w-full shrink-0">
      {/* A capture of the existing application, shown as it was taken. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} width={375} height={812} className="rounded-[28px] border border-ds-border-strong" />
      <figcaption className="mt-2 text-ds-caption text-ds-text-subtle">Before: the existing application (Stage A capture, local data)</figcaption>
    </figure>
  );
}

function Pair({ title, why, before, after }: { title: string; why: string[]; before: ReactNode; after: ReactNode }) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-ds-title font-bold text-ds-text">{title}</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-ds-body text-ds-text-muted">
          {why.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>
      <div className="flex flex-wrap items-start gap-6">
        {before}
        <figure className="w-[375px] max-w-full shrink-0">
          {after}
          <figcaption className="mt-2 text-ds-caption text-ds-text-subtle">After: proposed, sample content</figcaption>
        </figure>
      </div>
    </section>
  );
}

function CceoToday() {
  return (
    <Phone title="Today">
      <Surface>
        <p className="text-ds-caption font-semibold text-ds-text-subtle">Next up · 9:00</p>
        <p className="mt-1 text-ds-lead font-bold text-ds-text">Support visit — Kasawo Church of Uganda P/S</p>
        <p className="mt-1 text-ds-caption text-ds-text-subtle">Mukono · 1 of 3 stops on today&apos;s route</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Button href="#">Start visit</Button>
          <Button kind="secondary" href="#">
            Route
          </Button>
        </div>
      </Surface>
      <SectionHeader title="Waiting on you" count={4} href="#" />
      <TaskList>
        <TaskRow title="Upload visit evidence" context="Goma Division UMEA P/S · visited 17 Nov" status="Due today" tone="warning" action="Upload" href="#" />
        <TaskRow title="Plan follow-up visit" context="Nakifuma P/S · SSA weakest: leadership" status="This week" tone="info" action="Plan" href="#" />
        <TaskRow title="Confirm partner delivery" context="Kyampisi UMEA P/S · partner" status="Overdue" tone="danger" action="Review" href="#" />
        <TaskRow title="Add school to a cluster" context="Kiwanga P/S · no active cluster" action="Cluster" href="#" />
      </TaskList>
      <SectionHeader title="This year" />
      <Surface>
        <div className="grid grid-cols-2 gap-4">
          <KpiStat label="Support visits" value={212} of={280} />
          <KpiStat label="Trainings" value={9} of={12} />
        </div>
      </Surface>
    </Phone>
  );
}

function PlDecisions() {
  return (
    <Phone title="Today">
      <Segmented items={['My work', 'Team']} active="Team" />
      <SectionHeader title="Decisions waiting" count={7} href="#" />
      <TaskList>
        <TaskRow title="Approve fund request" context="Okello's week of 24 Nov · UGX 1,240,000" status="Due Mon" tone="warning" action="Review" href="#" />
        <TaskRow title="Verify completed visit" context="Nansubuga · Kiwanga P/S · evidence uploaded" status="2 days" tone="info" action="Verify" href="#" />
        <TaskRow title="Verify completed visit" context="Mugisha · Seeta High · evidence uploaded" status="1 day" tone="info" action="Verify" href="#" />
        <TaskRow title="Follow up overdue plans" context="Achieng · 4 visits past their date" status="Overdue" tone="danger" action="Follow up" href="#" />
      </TaskList>
      <SectionHeader title="Team this week" href="#" linkLabel="Oversight" />
      <Surface>
        <div className="grid grid-cols-2 gap-4">
          <KpiStat label="Visits done" value={38} of={52} />
          <KpiStat label="Evidence overdue" value={5} hint="3 officers" />
        </div>
      </Surface>
    </Phone>
  );
}

const MONEY: { label: string; amount: string; count: number; tone: 'warning' | 'info' | 'success' }[] = [
  { label: 'Pending disbursement', amount: 'UGX 18,420,000', count: 14, tone: 'warning' },
  { label: 'Approved budgets', amount: 'UGX 96,000,000', count: 3, tone: 'info' },
  { label: 'Partner payments ready', amount: 'UGX 7,350,000', count: 6, tone: 'success' },
];

function AccountantMoney() {
  return (
    <Phone title="Today">
      <SectionHeader title="Money waiting on you" />
      <div className="space-y-2">
        {MONEY.map((m) => (
          <a
            key={m.label}
            href="#"
            className="flex min-h-[var(--ds-target)] items-center justify-between rounded-ds-lg border border-ds-border bg-ds-surface px-4 py-3 shadow-ds-raised"
          >
            <div>
              <p className="text-ds-caption font-semibold text-ds-text-subtle">{m.label}</p>
              <p className="mt-0.5 text-ds-lead font-bold tabular-nums text-ds-text">{m.amount}</p>
            </div>
            <StatusBadge tone={m.tone}>{m.count} items</StatusBadge>
          </a>
        ))}
      </div>
      <SectionHeader title="Exceptions" count={0} />
      <EmptyState title="No exceptions" body="Advances, budgets and payments reconcile. New exceptions appear here first." />
    </Phone>
  );
}

const SCHOOL_COLUMNS: DataColumn[] = [
  { key: 'name', label: 'School', role: 'title' },
  { key: 'id', label: 'School ID', role: 'context' },
  { key: 'district', label: 'District', role: 'context' },
  { key: 'visit', label: 'Last visit' },
  { key: 'ssa', label: 'SSA average', numeric: true },
  { key: 'cluster', label: 'Cluster' },
  { key: 'state', label: 'Status', role: 'status' },
];

const SCHOOL_ROWS: DataRow[] = [
  { id: '1', href: '#', tone: 'success', cells: { name: 'Kasawo Church of Uganda P/S', id: '001026', district: 'Mukono', visit: '17 Nov 2026', ssa: '3.4', cluster: 'Cluster A', state: 'Visited' } },
  { id: '2', href: '#', tone: 'warning', cells: { name: 'Goma Division UMEA P/S', id: '001598', district: 'Mukono', visit: '2 Oct 2026', ssa: '2.8', cluster: 'Cluster A', state: 'Follow-up due' } },
  { id: '3', href: '#', tone: 'danger', cells: { name: 'Kyampisi UMEA P/S', id: '002114', district: 'Mukono', visit: '', ssa: '2.1', cluster: '', state: 'Not visited' } },
];

export default function DesignPreviewPage() {
  return (
    <div className="space-y-12 bg-ds-bg p-6 text-ds-text">
      <header className="max-w-3xl">
        <p className="text-ds-caption font-bold uppercase tracking-wide text-ds-primary">Stage B · preview</p>
        <h1 className="mt-1 text-ds-display font-bold">Edify Enterprise Design System</h1>
        <p className="mt-2 text-ds-body text-ds-text-muted">
          Tokens and components for the redesigned web and native screens, and before/after pairs for three phone screens. Before is a real capture of the
          existing application; after is the proposed layout with sample content. Review the structure here before any page is rebuilt.
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-ds-title font-bold">Colour</h2>
        <p className="text-ds-body text-ds-text-muted">Every text and status colour meets WCAG 2.2 AA on the surfaces it is drawn on (checked when the tokens are built).</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          {SWATCHES.map((name) => (
            <div key={name} className="overflow-hidden rounded-ds-md border border-ds-border bg-ds-surface">
              <div className="h-12" style={{ background: `var(--ds-${name})` }} />
              <p className="px-2 py-1 text-ds-caption font-semibold">{name}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-ds-title font-bold">Type</h2>
        <div className="space-y-2 rounded-ds-lg border border-ds-border bg-ds-surface p-4">
          {TYPE.map(([name, className]) => (
            <p key={name} className={`${className} font-semibold`}>
              {name} · Planned 212 of 280 support visits
            </p>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-ds-title font-bold">Components</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <Surface>
            <div className="flex flex-wrap gap-2">
              <Button>Primary</Button>
              <Button kind="secondary">Secondary</Button>
              <Button kind="ghost">Ghost</Button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <StatusBadge>Draft</StatusBadge>
              <StatusBadge tone="info">Waiting on you</StatusBadge>
              <StatusBadge tone="success">Verified</StatusBadge>
              <StatusBadge tone="warning">Due today</StatusBadge>
              <StatusBadge tone="danger">Overdue</StatusBadge>
            </div>
          </Surface>
          <Surface>
            <Skeleton />
          </Surface>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-ds-title font-bold">Tables</h2>
        <p className="text-ds-body text-ds-text-muted">
          A table from 768px; below that each row shows the school, its School ID and district, and its status, with the other columns under More details
          (owner, 2026-11-19: rows on phones). Resize the window to see both.
        </p>
        <DataTable caption="Schools, sample" columns={SCHOOL_COLUMNS} rows={SCHOOL_ROWS} empty={{ title: 'No schools', body: 'Schools appear here once they are assigned to you.' }} />
      </section>

      <Pair
        title="CCEO · Today"
        why={[
          'The next visit and its route lead, with one action, instead of a greeting band.',
          'Only work that waits on the officer is listed; "0 schools not clustered — all clear" rows are gone.',
          'Targets are two figures with their share, not four zero tiles.',
        ]}
        before={<Before src="/design-preview/before/cceo-home-phone.jpg" alt="The existing CCEO Home on a phone" />}
        after={<CceoToday />}
      />
      <Pair
        title="Program Lead · Today"
        why={['My work and Team are kept apart, as the brief asks.', 'Decisions others wait on come first, each with the one action it needs.']}
        before={<Before src="/design-preview/before/pl-home-phone.jpg" alt="The existing Program Lead Home on a phone" />}
        after={<PlDecisions />}
      />
      <Pair
        title="Accountant · Today"
        why={['Money states are kept distinct, each with its UGX total and count.', 'Exceptions have a place of their own, empty when there are none.']}
        before={<Before src="/design-preview/before/accountant-home-phone.jpg" alt="The existing Accountant Home on a phone" />}
        after={<AccountantMoney />}
      />
    </div>
  );
}
