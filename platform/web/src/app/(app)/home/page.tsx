import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound, redirect } from 'next/navigation';

import { IdentityService } from '@/gen/edify/identity/v1/identity_pb';
import { HomeScreenService } from '@/gen/edify/screens/v1/home_pb';
import type { GetHomeQueueResponse, GetHomeResponse, HomeFigure, HomePriorityRow, HomeUpcoming } from '@/gen/edify/screens/v1/home_pb';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isNotFound, isUnavailable } from '@/lib/gateway';
import { homeDate, homeFigures, homeHeader } from '@/lib/homeScreen';
import type { HomeFigureCard } from '@/lib/homeScreen';
import { safeIcon } from '@/lib/icon';
import { withRouteShortcut } from '@/lib/routePlanner';

export const metadata: Metadata = { title: 'Home — Edify' };

type HomeParts = { home: GetHomeResponse; queue: GetHomeQueueResponse; figures: HomeFigure[]; total: number | undefined };
type HomeAnswer = { kind: 'home'; parts: HomeParts } | { kind: 'elsewhere'; url: string } | { kind: 'notMoved' };

/** Each part of Home; where the reader starts instead; or not moved yet. */
async function askHome(): Promise<HomeAnswer> {
  return asReader(async (token): Promise<HomeAnswer> => {
    const client = gatewayClient(HomeScreenService, token);
    try {
      const [answer, session] = await Promise.all([client.getHome({}), gatewayClient(IdentityService, token).getSession({})]);
      // Quick access opens Smart Route in My Plan's place for a role that plans routes.
      const home = { ...answer, shortcuts: withRouteShortcut(answer.shortcuts, session.session?.activeRole ?? '') };
      if (home.redirectUrl) return { kind: 'elsewhere', url: home.redirectUrl };
      const queue = await client.getHomeQueue({});
      if (queue.todoFiguresLater) {
        const later = await client.getHomeTodoFigures({});
        return { kind: 'home', parts: { home, queue, figures: later.queueFigures, total: later.priorityTotal } };
      }
      return { kind: 'home', parts: { home, queue, figures: queue.queueFigures, total: queue.priorityTotal } };
    } catch (error) {
      if (isNotFound(error)) notFound();
      if (isUnavailable(error)) return { kind: 'notMoved' };
      throw error;
    }
  });
}

/* Home's small icon set (templates/partials/home/icon.html). */
const GLYPHS = {
  bolt: <path d="M13 2 4 14h7l-1 8 9-12h-7z" />,
  grid: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M16 3v4M8 3v4M3 11h18" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  chevron: <path d="m9 6 6 6-6 6" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
} as const;

function Glyph({ name }: { name: keyof typeof GLYPHS }) {
  return (
    <svg
      className="edify-home-glyph"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {GLYPHS[name]}
    </svg>
  );
}

/** An icon the gateway sends as the existing web's SVG markup. */
function SentIcon({ svg, className }: { svg: string; className: string }) {
  return <span className={className} aria-hidden="true" dangerouslySetInnerHTML={{ __html: safeIcon(svg) }} />;
}

function Figure({ card }: { card: HomeFigureCard }) {
  return (
    <Link
      href={card.url}
      className={`edify-home__figure edify-home__figure--${card.tone}${card.loading ? ' edify-home__figure--loading' : ''}`}
      data-home-figure={card.key}
      aria-busy={card.loading || undefined}
    >
      <SentIcon svg={card.iconSvg} className="edify-home__figure-glyph" />
      <span className="edify-home__figure-value">
        {card.loading ? (
          <>
            <span className="edify-home__skeleton" aria-hidden="true" />
            <span className="sr-only">Loading</span>
          </>
        ) : (
          card.value
        )}
      </span>
      <span className="edify-home__figure-label">{card.label}</span>
      {card.description ? <span className="sr-only">: {card.description}</span> : null}
    </Link>
  );
}

function PriorityItem({ row }: { row: HomePriorityRow }) {
  return (
    <li>
      <Link href={row.url} className="edify-home__item" data-home-priority={row.key || undefined}>
        <SentIcon svg={row.iconSvg} className={`edify-home__item-mark edify-home__item-mark--${row.markTone || row.statusTone}`} />
        <span className="edify-home__item-body">
          <span className="edify-home__item-name">{row.title}</span>
          {row.context ? <span className="edify-home__item-sub">{row.context}</span> : null}
          <span className="edify-home__item-tags">
            {row.statusLabel ? <span className={`edify-home__tag edify-home__tag--${row.statusTone}`}>{row.statusLabel}</span> : null}
            {row.dueLabel ? (
              <span className={`edify-home__due edify-home__due--${row.dueTone}`}>
                <Glyph name="clock" />
                {row.dueLabel}
              </span>
            ) : null}
          </span>
        </span>
        <span className="edify-home__item-go">
          {row.actionLabel}
          <Glyph name="chevron" />
        </span>
      </Link>
    </li>
  );
}

function UpcomingItem({ item }: { item: HomeUpcoming }) {
  return (
    <li>
      <Link href={item.url} className="edify-home__item edify-home__item--upcoming" data-home-upcoming="">
        <span className={`edify-home__datebox${item.isToday ? ' edify-home__datebox--today' : ''}`}>
          <span>{item.isToday ? 'TODAY' : item.month}</span>
          <strong>{item.day}</strong>
        </span>
        <span className="edify-home__item-body">
          <span className="edify-home__item-name">
            {item.title}
            {item.where ? ` — ${item.where}` : ''}
          </span>
          <span className="edify-home__item-sub">
            {item.time ? `${item.time} · ` : ''}
            {item.typeLabel} · {item.statusLabel}
          </span>
        </span>
        <span className="edify-home__item-go edify-home__item-go--quiet">
          <Glyph name="chevron" />
          <span className="sr-only">Open</span>
        </span>
      </Link>
    </li>
  );
}

function Empty({ title, copy, cta }: { title: string; copy: string; cta?: boolean }) {
  return (
    <div className="edify-home__empty">
      <p className="edify-home__empty-title">{title}</p>
      <p className="edify-home__empty-copy">{copy}</p>
      {cta ? (
        <Link href="/my-plan" className="edify-home__empty-cta">
          Open My Plan
        </Link>
      ) : null}
    </div>
  );
}

/*
 * Home, as the existing Home draws it (templates/pages/home/index.html and
 * partials/home/*), from the gateway's HomeScreenService answers: the
 * greeting, Today's overview, the priority actions, Quick access and the
 * reader's upcoming activities. A reader who does not use Home is sent where
 * they start.
 */
export default async function HomePage() {
  const answer = await askHome();
  if (answer.kind === 'elsewhere') redirect(answer.url);
  if (answer.kind === 'notMoved') return <NotMovedYet href={`${environment().existingWebUrl}/home`} />;
  const { home, queue, figures, total } = answer.parts;
  const header = homeHeader(home);
  const cards = homeFigures(home.figures, figures);
  const rows = queue.priorityRows;
  return (
    <div className="edify-home" data-mobile-family="home" data-page="/home">
      <header className="edify-home__hero edify-inverse-surface">
        <div className="edify-home__wordmark">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="edify-home__wordmark-logo" src="/static/images/logo.png" alt="Edify" width={72} height={30} />
          <span className="edify-home__wordmark-rule" aria-hidden="true" />
          <span className="edify-home__wordmark-product">
            Planning &amp;
            <br />
            Monitoring
          </span>
        </div>
        <h1 className="edify-page-title edify-home__greeting">
          <span className="edify-home__greeting-words">{header.title}</span>
        </h1>
        <p className="edify-home__subtitle">Here’s what needs you today</p>
        {home.roleTitle ? <p className="edify-home__role">{home.roleTitle}</p> : null}
      </header>
      <header className="edify-page-header edify-home__desk-head mobile-home-hide">
        <div className="edify-page-header__lead">
          <p className="edify-page-eyebrow">{header.eyebrow}</p>
          <h1 className="edify-page-title edify-page-header__title">{header.title}</h1>
          <p className="edify-page-header__description">{header.description}</p>
        </div>
      </header>
      <section className="edify-home__card edify-home__overview" aria-labelledby="home-summary-title">
        <div className="edify-home__card-head">
          <h2 id="home-summary-title" className="edify-home__card-title">
            Today’s overview
          </h2>
          <time className="edify-home__date" dateTime={home.today}>
            {homeDate(home)}
          </time>
        </div>
        <ul className="edify-home__figures" role="list" data-count={cards.length}>
          {cards.map((card) => (
            <li key={card.key}>
              <Figure card={card} />
            </li>
          ))}
        </ul>
      </section>
      <section className="edify-home__card edify-home__card--queue" aria-labelledby="home-priority-title">
        <div className="edify-home__card-head">
          <h2 id="home-priority-title" className="edify-home__card-title">
            <span className="edify-home__head-glyph">
              <Glyph name="bolt" />
            </span>
            Priority actions
          </h2>
          {total ? (
            <Link href="/todos" className="edify-home__see-all">
              View all {total}
              <Glyph name="arrow" />
            </Link>
          ) : null}
        </div>
        {rows.length ? (
          <ul className="edify-home__list" role="list">
            {rows.map((row, i) => (
              <PriorityItem key={row.key || `${row.title}-${i}`} row={row} />
            ))}
          </ul>
        ) : (
          <Empty title="Nothing needs you right now" copy="New work appears here as soon as it is yours to do." cta={queue.hasPlan} />
        )}
      </section>
      {home.shortcuts.length || home.hasPlan ? (
        <div className="edify-home__side">
          {home.shortcuts.length ? (
            <section className="edify-home__card edify-home__card--side" aria-labelledby="home-shortcuts-title">
              <div className="edify-home__card-head">
                <h2 id="home-shortcuts-title" className="edify-home__card-title">
                  <span className="edify-home__head-glyph">
                    <Glyph name="grid" />
                  </span>
                  Quick access
                </h2>
              </div>
              <ul className="edify-home__shortcuts" role="list">
                {home.shortcuts.map((s) => (
                  <li key={s.url}>
                    <Link href={s.url} className="edify-home__shortcut">
                      <SentIcon svg={s.iconSvg} className="edify-home__shortcut-glyph" />
                      <span className="edify-home__shortcut-label">{s.label}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {home.hasPlan ? (
            <section className="edify-home__card edify-home__card--side" aria-labelledby="home-upcoming-title">
              <div className="edify-home__card-head">
                <h2 id="home-upcoming-title" className="edify-home__card-title">
                  <span className="edify-home__head-glyph">
                    <Glyph name="calendar" />
                  </span>
                  Upcoming activities
                </h2>
                {home.upcoming.length ? (
                  <Link href="/my-plan?status=upcoming" className="edify-home__see-all">
                    View all
                    <Glyph name="arrow" />
                  </Link>
                ) : null}
              </div>
              {home.upcoming.length ? (
                <ul className="edify-home__list" role="list">
                  {home.upcoming.map((item) => (
                    <UpcomingItem key={item.id} item={item} />
                  ))}
                </ul>
              ) : (
                <Empty title="No activities coming up" copy="Plan your next visit or training and it will show here." cta />
              )}
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
