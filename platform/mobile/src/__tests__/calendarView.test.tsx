import { create } from '@bufbuild/protobuf';
import { act } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { createRoot, type TestInstance } from 'test-renderer';

import { PageBlockSchema, type PageBlock } from '../gen/edify/screens/v1/page_pb';
import { PageBlocksView } from '../ui/page/PageBlocksView';
import { PageLinkContext, PickContext } from '../ui/page/shared';

// The icon set ships as ES modules only; the month's words and presses are what is tested.
jest.mock('lucide-react-native', () => new Proxy({}, { get: (_, name) => (name === '__esModule' ? false : () => null) }));

/** The Calendar page's answer as the feed gives it: filters, the event-type segments, then the month block. */
const BLOCKS: PageBlock[] = [
  create(PageBlockSchema, {
    kind: { case: 'filters', value: { filters: [], hidden: { year: '2026', month: '11', event_kind: '' } } },
  }),
  create(PageBlockSchema, {
    kind: {
      case: 'segments',
      value: {
        caption: 'Operations calendar',
        segments: [
          {
            label: 'All events3',
            blocks: [
              { kind: { case: 'panel', value: { title: 'November 2026', subtitle: 'Your schedule' } } },
              { kind: { case: 'panel', value: { title: 'November 2026', items: [{ kind: { case: 'text', value: 'No events in November 2026.' } }] } } },
            ],
          },
        ],
      },
    },
  }),
  create(PageBlockSchema, {
    kind: {
      case: 'calendar',
      value: {
        year: 2026,
        month: 11,
        today: '2026-11-13',
        kind: 'all',
        kinds: [
          { value: 'all', label: 'All events', count: '3' },
          { value: 'leave', label: 'Leave', count: '1' },
        ],
        days: [
          { date: '2026-11-03', events: [{ kind: 'activity', family: 'visit', title: 'Donor Visit', meta: 'Kimenyedde', href: '/my-plan/a1', pickId: 'a1' }] },
          {
            date: '2026-11-13',
            today: true,
            events: [
              { kind: 'leave', title: 'Annual leave', meta: 'Annual' },
              { kind: 'activity', family: 'training', title: 'Training', meta: 'Day 1 of 2', href: '/my-plan/t1', pickId: 't1' },
            ],
          },
          { date: '2026-11-14', dayOff: true, events: [{ kind: 'activity', family: 'training', title: 'Training', meta: 'Day 2 of 2', pickId: 't1', continued: true, dayOff: true }] },
        ],
      },
    },
  }),
];

/** A phone's frame, so the page's filter bar can place its menus. */
const METRICS = { frame: { x: 0, y: 0, width: 390, height: 844 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };

interface Drawn {
  readonly root: TestInstance;
  readonly onFilter: jest.Mock;
  readonly onLink: jest.Mock;
  readonly onPick: jest.Mock;
}

async function draw(picked: readonly string[] = []): Promise<Drawn> {
  const onFilter = jest.fn();
  const onLink = jest.fn();
  const onPick = jest.fn();
  const renderer = createRoot();
  await act(async () => {
    renderer.render(
      <SafeAreaProvider initialMetrics={METRICS}>
        <PageLinkContext.Provider value={onLink}>
          <PickContext.Provider value={{ isOn: true, picked, set: onPick }}>
            <PageBlocksView blocks={BLOCKS} onFilter={onFilter} />
          </PickContext.Provider>
        </PageLinkContext.Provider>
      </SafeAreaProvider>,
    );
  });
  return { root: renderer.container, onFilter, onLink, onPick };
}

function texts(root: TestInstance): string[] {
  return root
    .queryAll((node) => node.type === 'Text')
    .map((node) => node.children.filter((child): child is string => typeof child === 'string').join(''))
    .filter((text) => text !== '');
}

function byLabel(root: TestInstance, label: string): TestInstance {
  const found = root.queryAll((node) => typeof node.type === 'string' && node.props.accessibilityLabel === label);
  if (!found[0]) {
    throw new Error(`nothing labelled ${label}`);
  }
  return found[0];
}

async function press(node: TestInstance): Promise<void> {
  await act(async () => {
    (node.props.onClick ?? node.props.onPress)?.({});
  });
}

describe('the Calendar month block in the app', () => {
  it('draws the month in place of the event-type segments', async () => {
    const { root } = await draw();
    const words = texts(root);
    expect(words).not.toContain('All events3');
    expect(words).toEqual(expect.arrayContaining(['All events', 'Leave', 'YOUR SCHEDULE', 'November 2026', 'Friday, November 13']));
  });

  it('opens on today with today’s entries, and shows the month on All month', async () => {
    const { root } = await draw();
    expect(texts(root)).toEqual(expect.arrayContaining(['Annual leave', 'Training', 'Day 1 of 2']));
    expect(texts(root)).not.toContain('Donor Visit');
    await press(byLabel(root, 'Tuesday, November 3, 1 events'));
    expect(texts(root)).toContain('Donor Visit');
    expect(texts(root)).not.toContain('Annual leave');
  });

  it('ticks an activity for the page’s bar', async () => {
    const { root, onPick } = await draw();
    await press(byLabel(root, 'Select Training, Day 1 of 2'));
    expect(onPick).toHaveBeenCalledWith(['t1'], true);
  });

  it('opens an activity’s page', async () => {
    const { root, onLink } = await draw();
    const link = root.queryAll((node) => typeof node.type === 'string' && node.props.accessibilityRole === 'link')[0];
    await press(link!);
    expect(onLink).toHaveBeenCalledWith('/my-plan/t1');
  });

  it('moves to another tab or month through the page’s filters', async () => {
    const { root, onFilter } = await draw();
    await press(byLabel(root, 'Leave, 1'));
    expect(onFilter).toHaveBeenLastCalledWith('event_kind', 'leave', { year: '2026', month: '11', event_kind: '' });
    await press(byLabel(root, 'Next month'));
    expect(onFilter).toHaveBeenLastCalledWith('month', '12', { year: '2026', month: '11', event_kind: '' });
  });
});
