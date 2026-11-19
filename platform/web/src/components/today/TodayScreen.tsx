/**
 * The redesigned Today (docs/migration/177 stage D, 179, 180): from Go's Home
 * answer (lib/homeData), the next thing on the reader's plan, what waits on
 * them and the figures that hold something, drawn with the design system
 * (components/eds). Mobile first: one column on a phone, the figures and
 * quick access beside the queue from 1024px. Which rows and figures it shows
 * is lib/todayView's choice.
 */
import type { HomeUpcoming } from '@/gen/edify/screens/v1/home_pb';
import { Button, EmptyState, KpiStat, SectionHeader, StatusBadge, Surface, TaskList, TaskRow } from '@/components/eds';
import type { HomeParts } from '@/lib/homeData';
import { homeFigures } from '@/lib/homeScreen';
import { countedFigures, figureNumber, nextUp, toneOf, waitingRows } from '@/lib/todayView';

function NextUp({ next }: { next: HomeUpcoming | undefined }) {
  if (!next) {
    return <EmptyState title="Nothing planned next" body="Plan a visit or a training and it appears here." action={<Button href="/my-plan">Open My Plan</Button>} />;
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

export function TodayScreen({ parts, note }: { parts: HomeParts; note?: string }) {
  const { home, queue, figures, total } = parts;
  const waiting = waitingRows(queue.priorityRows);
  const counted = countedFigures(homeFigures(home.figures, figures));
  return (
    <div className="min-h-full bg-ds-bg px-4 py-5 text-ds-text lg:px-8" data-page="/home" data-design="today" data-eds>
      <header className="mx-auto max-w-5xl">
        <p className="text-ds-caption font-semibold text-ds-text-subtle">
          {home.todayLabel} · FY{home.fy}
          {home.roleTitle ? ` · ${home.roleTitle}` : ''}
        </p>
        <h1 className="mt-1 text-ds-title font-bold">Today</h1>
        {note ? <p className="mt-1 text-ds-caption text-ds-text-subtle">{note}</p> : null}
      </header>
      <div className="mx-auto mt-5 grid max-w-5xl gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          {home.hasPlan ? <NextUp next={nextUp(home.upcoming)} /> : null}
          <SectionHeader title="Waiting on you" href="/todos" linkLabel={total ? `All ${total} To-Dos` : 'All To-Dos'} />
          {waiting.length ? (
            <TaskList>
              {waiting.map((row, i) => (
                <TaskRow
                  key={`${row.key}-${i}`}
                  title={row.title}
                  context={row.context}
                  status={row.statusLabel || row.dueLabel || undefined}
                  tone={toneOf(row.statusTone || row.dueTone)}
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
                    <KpiStat key={`${f.key}-${i}`} label={f.label} value={figureNumber(f)} />
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
