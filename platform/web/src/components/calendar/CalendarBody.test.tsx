/**
 * The Calendar drawn from an answer shaped as the Go gateway gives it
 * (trimmed from the Director's answer on the development database,
 * 2026-11-13): people strips, the composer, the event tabs and the month.
 */
import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { GetPageResponseSchema } from '@/gen/edify/screens/v1/page_screen_pb';

import { CalendarBody } from './CalendarBody';

const EXISTING = 'http://localhost:8125/calendar';
const at = (person: string) => `/calendar?year=2026&month=2${person ? `&person=${person}` : ''}`;

function grid(): JsonValue[] {
  const items: JsonValue[] = [{ rows: { rows: [{ label: 'FEB', value: '01' }] } }, { text: 'Select all' }, { text: 'Mon' }];
  for (let day = 1; day <= 28; day += 1) {
    if (day === 1) items.push({ rows: { rows: [{ label: 'Sun', value: '1' }] } });
    else if (day === 17) items.push({ rows: { rows: [{ label: 'Public holiday', value: '17' }] } });
    else items.push({ text: String(day) });
    if (day === 3) items.push({ links: { links: [{ text: 'Donor Visit', href: '/my-plan/a1', caption: 'Kimenyedde Primary' }] } });
    if (day === 16) items.push({ text: 'Archbishop Janani Luwum Day' });
  }
  items.push({ links: { links: [{ text: 'Donor VisitKimenyedde Primary', href: '/my-plan/a1' }] } }, { text: 'Leave, holidays, and organization events are overlays.' });
  return items;
}

const ANSWER: JsonValue = {
  header: { title: 'Calendar', eyebrow: 'Operations calendar', actions: [{ key: 'apply_for_leave', label: 'Apply for Leave', enabled: true, href: '/personal-time-off' }] },
  blocks: [
    { panel: { items: [{ links: { links: [{ text: 'My calendar', href: at(''), caption: '0' }, { text: "Program Lead 1's team", href: at('pl1'), caption: '2' }] } }] } },
    { panel: { title: 'Add an organization event', subtitle: 'Country calendar', items: [{ heading: 'Add other event' }] } },
    { filters: { filters: [{ name: 'status', label: 'Status', options: [{ label: 'All statuses' }, { value: 'scheduled', label: 'Scheduled' }] }], hidden: { event_kind: '', month: '2', year: '2026' } } },
    {
      segments: {
        caption: 'Operations calendar',
        segments: [
          { label: 'All events2', blocks: [{ panel: { title: 'February 2026', subtitle: 'Your schedule', items: [{ text: 'No matching events for this date and event type.' }] } }, { panel: { title: 'February 2026', subtitle: 'February 1, 2026 – February 28, 2026', items: grid() } }] },
          { label: 'Holidays1', blocks: [] },
        ],
      },
    },
    {
      calendar: {
        year: 2026,
        month: 2,
        today: '2026-02-16',
        kind: 'all',
        kinds: [
          { value: 'all', label: 'All events', count: '2' },
          { value: 'holiday', label: 'Holidays', count: '1' },
        ],
        days: [
          { date: '2026-02-03', events: [{ kind: 'activity', family: 'visit', title: 'Donor Visit', meta: 'Kimenyedde Primary', href: '/my-plan/a1', pickId: 'a1' }] },
          { date: '2026-02-16', today: true, dayOff: true, events: [{ kind: 'holiday', title: 'Archbishop Janani Luwum Day', meta: 'Public holiday' }, { kind: 'activity', family: 'training', title: 'Group Training', meta: 'Reschedule: public holiday · Mukono', href: '/my-plan/a2', dayOff: true }] },
        ],
      },
    },
  ],
  selection: { noun: 'activities selected', actions: [{ label: 'Reschedule', href: '/activity-selection/reschedule', param: 'ids', joined: true }] },
};

function draw(query: Record<string, string>, view: 'month' | 'agenda' = 'month'): string {
  const answer = fromJson(GetPageResponseSchema, ANSWER);
  return renderToStaticMarkup(<CalendarBody answer={answer} query={query} view={view} existingHref={EXISTING} now={new Date(Date.UTC(2026, 1, 16, 9))} />);
}

describe('CalendarBody', () => {
  it('draws the month grid with each event on its day and today marked', () => {
    const html = draw({ month: '2', year: '2026' });
    expect(html).toMatch(/data-day="3"[^]*?Donor Visit[^]*?Kimenyedde Primary/);
    expect(html).toContain('href="/my-plan/a1"');
    expect(html).toMatch(/data-day="16"[^]*?Archbishop Janani Luwum Day[^]*?Public holiday/);
    expect(html).toMatch(/data-day="16"[^]*?Today/);
    expect(html).toContain('February 1, 2026 – February 28, 2026');
    expect(html).toContain('Leave, holidays, and organization events are overlays.');
  });

  it('draws the people strip with the reader’s calendar open and its counts', () => {
    const html = draw({});
    expect(html).toMatch(/aria-selected="true"[^>]*><span>My calendar<\/span> <span data-tab-count="true">0<\/span>/);
    expect(html).toContain('Program Lead 1&#x27;s team');
  });

  it('opens the composer on the existing web and each event tab on this page', () => {
    const html = draw({});
    expect(html).toContain(`href="${EXISTING}"`);
    expect(html).toContain('Add other event');
    expect(html).toContain('href="/calendar?event_kind=holiday"');
  });

  it('colours each entry by its family, marks the day off and ticks what may be moved', () => {
    const html = draw({ month: '2', year: '2026' });
    expect(html).toMatch(/data-event="activity" data-family="visit"[^>]*><input type="checkbox"[^>]*data-pick="a1"[^>]*aria-label="Select Donor Visit, Kimenyedde Primary"/);
    expect(html).toMatch(/data-day="16" data-day-off="true"/);
    expect(html).toMatch(/data-event="activity" data-family="training" data-day-off="true"/);
    expect(html).toContain('On a holiday or leave day: reschedule');
  });

  it('draws only the open tab’s entries', () => {
    const answer = fromJson(GetPageResponseSchema, ANSWER);
    const block = answer.blocks.at(-1);
    if (block?.kind.case === 'calendar') block.kind.value.kind = 'holiday';
    const html = renderToStaticMarkup(<CalendarBody answer={answer} query={{ month: '2', year: '2026', event_kind: 'holiday' }} view="month" existingHref={EXISTING} now={new Date(Date.UTC(2026, 1, 16, 9))} />);
    expect(html).toContain('Archbishop Janani Luwum Day');
    expect(html).not.toContain('Donor Visit');
    expect(html).toMatch(/aria-selected="true"[^>]*><span>Holidays<\/span>/);
  });

  it('lists only the days with events in the Agenda view and keeps the view in the filters', () => {
    const html = draw({ view: 'agenda' }, 'agenda');
    expect(html).toContain('Tuesday 3 February');
    expect(html).toContain('Monday 16 February');
    expect(html).not.toContain('Wednesday 4 February');
    expect(html).toMatch(/name="view" value="agenda"/);
  });
});
