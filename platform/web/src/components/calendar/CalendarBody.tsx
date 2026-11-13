/*
 * The Calendar page's parts in the answer's order: the header, the people
 * strips (a Lead's officers; the Director's teams and members), the Add
 * other event button, the filters, the event tabs and the month card.
 * Parts the feed reads generically (the day-off notice, the Coordinator's
 * workspace strip) are drawn by FeedBlocks as on every page.
 */
import { create } from '@bufbuild/protobuf';

import type { GetPageResponse } from '@/gen/edify/screens/v1/page_screen_pb';
import { PageLinkTabsSchema } from '@/gen/edify/screens/v1/page_pb';
import type { PageAction, PageBlock, PagePanel, PageSegments } from '@/gen/edify/screens/v1/page_pb';
import { eventTabs, peopleStrips, readMonth, todayIn } from '@/lib/calendarPage';
import { actionHref, queryString } from '@/lib/feedPage';

import { BUTTON_OUTLINE } from '../blocks/buttons';
import { PageHeader } from '../blocks/PageHeader';
import { TabRail } from '../blocks/TabRail';
import { FeedBlocks } from '../page/FeedBlocks';
import { Icon } from '../shell/icons';
import { CalendarMonthCard } from './CalendarMonthCard';

export interface CalendarBodyProps {
  readonly answer: GetPageResponse;
  readonly query: Readonly<Record<string, string>>;
  readonly view: 'month' | 'agenda';
  /** This page on the existing web, where its drawers and composer open. */
  readonly existingHref: string;
  readonly now: Date;
}

const PAGE = '/calendar';
/** The phone calendar's words for a chosen day when the month has no events (calendar/agenda.html). */
const NO_EVENTS_FOR_DATE = 'No events for this date.';

/** The composer's panel ("Add an organization event": one heading, its button). */
function composerOf(panel: PagePanel): string {
  const [item, ...rest] = panel.items;
  return !rest.length && item?.kind.case === 'heading' ? item.kind.value : '';
}

function withExistingKind(href: string, kind: string): string {
  const url = new URL(href);
  url.searchParams.set('event_kind', kind);
  return url.toString();
}

function Segments({ segments, hidden, query, view, existingHref, now }: { segments: PageSegments; hidden: Readonly<Record<string, string>> } & Omit<CalendarBodyProps, 'answer'>) {
  const tabs = eventTabs(segments.segments.map((segment) => segment.label));
  const year = Number(hidden.year);
  const month = Number(hidden.month);
  const all = segments.segments[0];
  const panels = (all?.blocks ?? []).flatMap((block) => (block.kind.case === 'panel' ? [block.kind.value] : []));
  // The tab draws the phone's small month first, then the grid: the grid is the last month read.
  const grid = panels.map((panel) => readMonth(panel, year, month)).filter((read) => read !== null).at(-1) ?? null;
  const phone = panels[0];
  // A chosen day with nothing: the sentence after the phone's day list, which the page writes only when the
  // month has events; otherwise its script's own words (index.html, calendar-agenda__empty).
  const afterList = phone ? phone.items.slice(phone.items.map((item) => item.kind.case).lastIndexOf('links') + 1) : [];
  const sentence = phone?.items.some((item) => item.kind.case === 'links') ? afterList.flatMap((item) => (item.kind.case === 'text' ? [item.kind.value] : [])).at(-1) : '';
  const dayEmpty = sentence || NO_EVENTS_FOR_DATE;
  const here = `${PAGE}${queryString(query)}`;
  const rail = create(PageLinkTabsSchema, {
    label: segments.caption,
    scrolls: true,
    tabs: tabs.map((tab, index) => ({ label: tab.label, active: index === 0, href: index === 0 || !tab.kind ? here : withExistingKind(existingHref, tab.kind) })),
  });
  return (
    <>
      <TabRail rail={rail} counts={tabs.map((tab) => Number(tab.count || 0))} />
      {grid ? (
        <CalendarMonthCard month={grid} query={query} view={view} today={todayIn(now, year, month)} eyebrow={phone?.subtitle ?? ''} dayEmpty={dayEmpty} />
      ) : (
        <FeedBlocks blocks={all?.blocks ?? []} pagePath={PAGE} drawerHref={existingHref} selectable={false} />
      )}
    </>
  );
}

function Block({ block, ...props }: { block: PageBlock } & Omit<CalendarBodyProps, 'answer'>) {
  const kind = block.kind;
  if (kind.case === 'panel') {
    const strips = peopleStrips(kind.value, props.query.person ?? '');
    if (strips) {
      return (
        <div className="space-y-2" data-block="people">
          {strips.map((strip, index) => (
            <TabRail key={index} rail={create(PageLinkTabsSchema, { scrolls: true, tabs: strip.map((tab) => ({ label: tab.label, href: tab.href, active: tab.active })) })} counts={strip.map((tab) => Number(tab.count))} />
          ))}
        </div>
      );
    }
    const composer = composerOf(kind.value);
    if (composer) {
      // The composer saves on the existing web, where it opens.
      return (
        <a href={props.existingHref} className={`${BUTTON_OUTLINE} self-start`} aria-label={kind.value.title || composer}>
          <Icon name="plus" className="h-4 w-4" />
          {composer}
        </a>
      );
    }
  }
  if (kind.case === 'filters' && props.view === 'agenda') {
    const value = { ...kind.value, hidden: { ...kind.value.hidden, view: 'agenda' } };
    return <FeedBlocks blocks={[{ ...block, kind: { case: 'filters', value } }]} pagePath={PAGE} drawerHref={props.existingHref} selectable={false} />;
  }
  return <FeedBlocks blocks={[block]} pagePath={PAGE} drawerHref={props.existingHref} selectable={false} />;
}

export function CalendarBody({ answer, ...props }: CalendarBodyProps) {
  const filters = answer.blocks.find((block) => block.kind.case === 'filters');
  const hidden = filters?.kind.case === 'filters' ? filters.kind.value.hidden : {};
  const hrefOf = (action: PageAction) => actionHref(action, PAGE, props.existingHref);
  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-4 px-4 pb-24 pt-5 sm:px-6 lg:pb-8" data-page={PAGE}>
      {answer.header ? <PageHeader header={answer.header} hrefOf={hrefOf} /> : null}
      {answer.blocks.map((block, index) =>
        block.kind.case === 'segments' ? (
          <Segments key={index} segments={block.kind.value} hidden={hidden} {...props} />
        ) : (
          <Block key={index} block={block} {...props} />
        ),
      )}
    </div>
  );
}
