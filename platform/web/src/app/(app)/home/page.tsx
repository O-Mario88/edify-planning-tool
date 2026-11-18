import type { Metadata } from 'next';
import { notFound, redirect } from 'next/navigation';

import { HomeScreenService } from '@/gen/edify/screens/v1/home_pb';
import type { GetHomeQueueResponse, GetHomeResponse, HomeFigure, HomePriorityRow, HomeUpcoming } from '@/gen/edify/screens/v1/home_pb';
import { Badge } from '@/components/blocks/Badge';
import { Card } from '@/components/blocks/Card';
import { KpiStrip } from '@/components/blocks/KpiStrip';
import { PageHeader } from '@/components/blocks/PageHeader';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isNotFound, isUnavailable } from '@/lib/gateway';
import { homeFigures, homeHeader, homeTone } from '@/lib/homeScreen';
import { safeIcon } from '@/lib/icon';

export const metadata: Metadata = { title: 'Home — Edify' };

const noAction = (): string => '';

type HomeParts = { home: GetHomeResponse; queue: GetHomeQueueResponse; figures: HomeFigure[] };
type HomeAnswer = { kind: 'home'; parts: HomeParts } | { kind: 'elsewhere'; url: string } | { kind: 'notMoved' };

/** Each part of Home; where the reader starts instead; or not moved yet. */
async function askHome(): Promise<HomeAnswer> {
  return asReader(async (token): Promise<HomeAnswer> => {
    const client = gatewayClient(HomeScreenService, token);
    try {
      const home = await client.getHome({});
      if (home.redirectUrl) return { kind: 'elsewhere', url: home.redirectUrl };
      const queue = await client.getHomeQueue({});
      const figures = queue.todoFiguresLater ? (await client.getHomeTodoFigures({})).queueFigures : queue.queueFigures;
      return { kind: 'home', parts: { home, queue, figures } };
    } catch (error) {
      if (isNotFound(error)) notFound();
      if (isUnavailable(error)) return { kind: 'notMoved' };
      throw error;
    }
  });
}

function Icon({ svg }: { svg: string }) {
  const markup = safeIcon(svg);
  if (!markup) return null;
  return (
    <span
      aria-hidden
      className="inline-flex h-5 w-5 shrink-0 text-[var(--brand-primary-text)] [&_svg]:h-5 [&_svg]:w-5"
      dangerouslySetInnerHTML={{ __html: markup }}
    />
  );
}

function PriorityRow({ row }: { row: HomePriorityRow }) {
  return (
    <li className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between" data-home-priority>
      <div className="flex min-w-0 items-start gap-3">
        <Icon svg={row.iconSvg} />
        <div className="min-w-0">
          <p className="font-semibold text-[var(--edify-text)]">{row.title}</p>
          {row.context ? <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">{row.context}</p> : null}
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        {row.dueLabel ? <Badge tone={homeTone(row.dueTone) || 'neutral'}>{row.dueLabel}</Badge> : null}
        {row.statusLabel ? <Badge tone={homeTone(row.statusTone) || 'neutral'}>{row.statusLabel}</Badge> : null}
        {row.actionLabel && row.url ? (
          <a
            href={row.url}
            className="inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] px-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--brand-primary-text)] hover:bg-[var(--edify-surface-muted)]"
          >
            {row.actionLabel}
          </a>
        ) : null}
      </div>
    </li>
  );
}

function UpcomingRow({ item }: { item: HomeUpcoming }) {
  const body = (
    <>
      <div
        className={`flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-[8px] border ${item.isToday ? 'border-[var(--brand-primary-border)] bg-[var(--brand-primary-soft)]' : 'border-[var(--edify-border)]'}`}
      >
        <span className="text-[10px] font-semibold uppercase text-[var(--edify-text-muted)]">{item.month}</span>
        <span className="text-[15px] font-bold leading-none text-[var(--edify-text)]">{item.day}</span>
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-[var(--edify-text)]">{item.title}</p>
        <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">{[item.where, item.time].filter(Boolean).join(' · ')}</p>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        {item.typeLabel ? <Badge tone="neutral">{item.typeLabel}</Badge> : null}
        {item.statusLabel ? <Badge tone="info">{item.statusLabel}</Badge> : null}
      </div>
    </>
  );
  return (
    <li>
      {item.url ? (
        <a href={item.url} className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--edify-surface-muted)]">
          {body}
        </a>
      ) : (
        <div className="flex items-center gap-3 px-4 py-3">{body}</div>
      )}
    </li>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <Card flush label={title}>
      <h2 className="flex items-center gap-2 border-b border-[var(--edify-border)] px-4 py-3 text-[length:var(--edify-text-heading-size)] font-semibold">
        {title}
        {count !== undefined ? <span className="text-[var(--edify-text-muted)]">({count})</span> : null}
      </h2>
      {children}
    </Card>
  );
}

/*
 * Home, drawn from the gateway's HomeScreenService answers (the phone app's
 * Home reads the same): the greeting, the overview figures, the priority
 * actions, the reader's upcoming work and their shortcuts. A reader who does
 * not use Home is sent where they start.
 */
export default async function HomePage() {
  const answer = await askHome();
  if (answer.kind === 'elsewhere') redirect(answer.url);
  if (answer.kind === 'notMoved') return <NotMovedYet href={`${environment().existingWebUrl}/home`} />;
  const { home, queue, figures } = answer.parts;
  const rows = queue.priorityRows;
  const total = queue.priorityTotal ?? rows.length;
  return (
    <div className="mx-auto max-w-[1500px] space-y-4 px-4 pb-24 pt-5 sm:px-6 lg:pb-8" data-page="/home">
      <PageHeader header={homeHeader(home)} hrefOf={noAction} />
      {home.figures.length ? <KpiStrip strip={homeFigures(home.figures, figures)} /> : null}
      <Section title="Priority actions" count={total}>
        {rows.length ? (
          <ul className="divide-y divide-[var(--edify-border)]">
            {rows.map((row, i) => (
              <PriorityRow key={row.key || `${row.title}-${i}`} row={row} />
            ))}
          </ul>
        ) : (
          <p className="px-4 py-6 text-[var(--edify-text-muted)]">Nothing is waiting on you.</p>
        )}
      </Section>
      {home.hasPlan ? (
        <Section title="Upcoming activities">
          {home.upcoming.length ? (
            <ul className="divide-y divide-[var(--edify-border)]">
              {home.upcoming.map((item) => (
                <UpcomingRow key={item.id} item={item} />
              ))}
            </ul>
          ) : (
            <p className="px-4 py-6 text-[var(--edify-text-muted)]">No activities coming up.</p>
          )}
        </Section>
      ) : null}
      {home.shortcuts.length ? (
        <Section title="Shortcuts">
          <ul className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-3 lg:grid-cols-6">
            {home.shortcuts.map((s) => (
              <li key={s.url}>
                <a
                  href={s.url}
                  className="flex h-full items-center gap-2 rounded-[8px] border border-[var(--edify-border)] px-3 py-2 font-semibold text-[var(--edify-text)] hover:bg-[var(--edify-surface-muted)]"
                >
                  <Icon svg={s.iconSvg} />
                  <span className="min-w-0 truncate">{s.label}</span>
                </a>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}
