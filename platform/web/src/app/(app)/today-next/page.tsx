/**
 * The redesigned Today (docs/migration/177 stage D, 179, 180), from the same
 * Go answers as Home (HomeScreenService through lib/homeData): the next thing
 * on the reader's plan, what waits on them, and the year's figures that
 * hold something. Mobile first: one column on a phone, the plan and figures
 * beside the queue from 1024px. Rows that only report "all clear" are left
 * out — Home shows them, so this page is the proposal and Home stays as it
 * is until the owner chooses (179's decisions).
 */
import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import type { HomePriorityRow, HomeUpcoming } from '@/gen/edify/screens/v1/home_pb';
import { Button, EmptyState, KpiStat, SectionHeader, StatusBadge, Surface, TaskList, TaskRow } from '@/components/eds';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { environment } from '@/lib/environment';
import { askHome } from '@/lib/homeData';

export const metadata: Metadata = { title: 'Today (redesign) — Edify' };

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

/** Go's tone words as the design system's. */
function tone(word: string): Tone {
  switch (word) {
    case 'danger':
    case 'critical':
      return 'danger';
    case 'warning':
      return 'warning';
    case 'success':
      return 'success';
    case 'info':
    case 'primary':
      return 'info';
    default:
      return 'neutral';
  }
}

/** A row that only reports nothing to do ("0 … — All clear"). */
function allClear(row: HomePriorityRow): boolean {
  return row.count === 0 && tone(row.statusTone) === 'success';
}

function NextUp({ next }: { next: HomeUpcoming | undefined }) {
  if (!next) {
    return <EmptyState title="Nothing planned next" body="Plan a visit or a training and it appears here with its route." action={<Button href="/my-plan">Open My Plan</Button>} />;
  }
  return (
    <Surface>
      <p className="text-ds-caption font-semibold text-ds-text-subtle">
        {next.isToday ? 'Next up · today' : `Next up · ${next.day} ${next.month}`}
        {next.time ? ` · ${next.time}` : ''}
      </p>
      <p className="mt-1 text-ds-lead font-bold text-ds-text">{next.title}</p>
      <p className="mt-1 text-ds-caption text-ds-text-subtle">{[next.where, next.typeLabel].filter(Boolean).join(' · ')}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button href={next.url}>Open</Button>
        {next.statusLabel ? <StatusBadge tone="info">{next.statusLabel}</StatusBadge> : null}
      </div>
    </Surface>
  );
}

export default async function TodayNextPage() {
  const answer = await askHome();
  if (answer.kind === 'elsewhere') redirect(answer.url);
  if (answer.kind === 'notMoved') return <NotMovedYet href={`${environment().existingWebUrl}/home`} />;
  const { home, queue, figures, total } = answer.parts;
  const waiting = queue.priorityRows.filter((row) => !allClear(row));
  const counted = [...home.figures, ...figures].filter((f) => /^\d[\d,]*$/.test(f.value) && f.value !== '0');
  const next = home.upcoming.find((u) => u.isToday) ?? home.upcoming[0];
  return (
    <div className="min-h-full bg-ds-bg px-4 py-5 text-ds-text lg:px-8">
      <header className="mx-auto max-w-5xl">
        <p className="text-ds-caption font-semibold text-ds-text-subtle">
          {home.todayLabel} · FY{home.fy}
          {home.roleTitle ? ` · ${home.roleTitle}` : ''}
        </p>
        <h1 className="mt-1 text-ds-title font-bold">Today</h1>
        <p className="mt-1 text-ds-caption text-ds-text-subtle">Redesign preview, from your live queue. Home is unchanged.</p>
      </header>
      <div className="mx-auto mt-5 grid max-w-5xl gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          {home.hasPlan ? <NextUp next={next} /> : null}
          <SectionHeader title="Waiting on you" count={total ?? waiting.length} href="/todos" />
          {waiting.length ? (
            <TaskList>
              {waiting.map((row, i) => (
                <TaskRow
                  key={`${row.key}-${i}`}
                  title={row.title}
                  context={row.context}
                  status={row.statusLabel || row.dueLabel || undefined}
                  tone={tone(row.statusTone || row.dueTone)}
                  action={row.actionLabel || 'Open'}
                  href={row.url}
                />
              ))}
            </TaskList>
          ) : (
            <EmptyState title="Nothing waits on you" body="New work appears here as soon as it is yours to do." />
          )}
        </div>
        <aside className="space-y-3">
          {counted.length ? (
            <>
              <SectionHeader title="At a glance" />
              <Surface>
                <div className="grid grid-cols-2 gap-4">
                  {counted.map((f, i) => (
                    <KpiStat key={`${f.key}-${i}`} label={f.label} value={Number(f.value.replace(/,/g, ''))} />
                  ))}
                </div>
              </Surface>
            </>
          ) : null}
          {home.shortcuts.length ? (
            <>
              <SectionHeader title="Go to" />
              <div className="grid grid-cols-2 gap-2">
                {home.shortcuts.map((s, i) => (
                  <Button key={`${s.url}-${i}`} kind="secondary" href={s.url}>
                    {s.label}
                  </Button>
                ))}
              </div>
            </>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
