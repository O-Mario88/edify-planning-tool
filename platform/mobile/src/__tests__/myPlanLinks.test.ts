import { create } from '@bufbuild/protobuf';

import { PageLinkTabSchema } from '../gen/edify/screens/v1/page_pb';
import { isShownFor, railTabs, selectionPath, webPageFor } from '../ui/page/pageLinks';

const tab = (label: string, active = false) => create(PageLinkTabSchema, { label, href: `?period=${label}`, active });

describe('railTabs', () => {
  test('a phone shows the first tab and the open one, the rest under More', () => {
    const { shown, rest } = railTabs([tab('week'), tab('month'), tab('quarter'), tab('fy', true)]);

    expect(shown.map((t) => t.label)).toEqual(['week', 'fy']);
    expect(rest.map((t) => t.label)).toEqual(['month', 'quarter']);
  });

  test('with the first tab open, the second shows beside it', () => {
    const { shown } = railTabs([tab('week', true), tab('month'), tab('quarter')]);

    expect(shown.map((t) => t.label)).toEqual(['week', 'month']);
  });
});

describe('webPageFor', () => {
  test("an activity's drawer opens its activity page on the web", () => {
    expect(webPageFor('/my-plan/a1/complete-drawer')).toBe('/my-plan/a1');
    expect(webPageFor('/activities/a1/start')).toBe('/my-plan/a1');
    expect(webPageFor('/my-plan/a1')).toBe('/my-plan/a1');
  });

  test('the export drawer and a planning modal open My Plan itself', () => {
    expect(webPageFor('/my-plan/export-drawer?fy=2026')).toBe('/my-plan?fy=2026');
    expect(webPageFor('/planning/schedule-modal?cluster_id=c1&action=training')).toBe('/my-plan?cluster_id=c1');
    expect(webPageFor('/planning/schedule-modal?action=training&cluster_id=c1')).toBe('/my-plan?cluster_id=c1');
    expect(webPageFor('/planning/schedule-modal?action=meeting')).toBe('/my-plan');
  });
});

describe('isShownFor', () => {
  test("a row shows while each chip is on all or on the row's own value", () => {
    const row = { cat: 'Finance', prio: 'high' };

    expect(isShownFor(row, { cat: 'all', prio: 'all' })).toBe(true);
    expect(isShownFor(row, { cat: 'Finance', prio: 'all' })).toBe(true);
    expect(isShownFor(row, { cat: 'SSA', prio: 'all' })).toBe(false);
    expect(isShownFor(row, { cat: 'Finance', prio: 'low' })).toBe(false);
  });

  test('a row with no key for a chip is not hidden by it', () => {
    expect(isShownFor({}, { cat: 'SSA' })).toBe(true);
  });
});

describe('selectionPath', () => {
  test("opens the bar's drawer with every ticked row in one value", () => {
    const cancel = { href: '/activity-selection/cancel', param: 'ids' };
    expect(selectionPath(cancel, ['a1', 'a2'])).toBe('/activity-selection/cancel?ids=a1,a2');
  });

  test('sends a list of schools the same way, for the feed to send one per school', () => {
    const assign = { href: '/planning/bulk-assign-partner-drawer', param: 'school_ids' };
    expect(selectionPath(assign, ['1693'])).toBe('/planning/bulk-assign-partner-drawer?school_ids=1693');
  });
});
