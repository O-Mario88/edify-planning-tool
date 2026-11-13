import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { GetNotificationCenterResponseSchema } from '@/gen/edify/screens/v1/notification_center_pb';

import {
  categoryChoices,
  keptQuery,
  notificationPager,
  notificationQuery,
  notificationRequest,
  notificationStrip,
  priorityPillTone,
  priorityTone,
} from './notificationCenter';

describe('notificationQuery and notificationRequest', () => {
  it('reads each key’s last value, as the view does', () => {
    const query = notificationQuery({ status: ['unread', 'read'], q: 'slo', other: 'x', page: '2' });
    expect(query).toEqual({ status: 'read', q: 'slo', page: '2' });
  });

  it('sends an absent status as absent and an empty one as asked', () => {
    expect('status' in notificationRequest({})).toBe(false);
    expect(notificationRequest({ status: '' })).toMatchObject({ status: '' });
  });

  it('turns the boxes on only for the words the view looks for', () => {
    expect(notificationRequest({ action_required: 'true', settings: 'saved' })).toMatchObject({ actionRequired: true, settingsSaved: true });
    expect(notificationRequest({ action_required: 'yes', settings: 'ok' })).toMatchObject({ actionRequired: false, settingsSaved: false });
  });
});

describe('the page’s blocks from the answer', () => {
  const answer = create(GetNotificationCenterResponseSchema, {
    kpis: { actionRequired: 7, critical: 2 },
    filters: {
      categories: [
        { value: 'hr', label: 'Hr' },
        { value: 'hr', label: 'Hr' },
        { value: 'follow_up', label: 'Follow_Up' },
      ],
    },
    page: { page: 2, pageSize: 50, total: 380n, totalPages: 8 },
    pageNumbers: [1, 2, 3, 0, 8],
  });

  it('draws the two figures with their helpers', () => {
    const strip = notificationStrip(answer);
    expect(strip.metrics.map((m) => [m.label, m.value, m.tone])).toEqual([
      ['Action required', '7', 'warning'],
      ['Critical tasks', '2', 'danger'],
    ]);
  });

  it('offers each category once, after All Categories, in the answer’s order', () => {
    expect(categoryChoices(answer).map((c) => c.value)).toEqual(['', 'hr', 'follow_up']);
  });

  it('words the pager as the existing one and links each page with the filters kept', () => {
    const pager = notificationPager(answer, { status: 'unread', page: '2', settings: 'saved' });
    expect(pager?.summary).toBe('Showing 51–100 of 380');
    expect(pager?.pages.map((p) => [p.label, p.href, p.current])).toEqual([
      ['1', '/notifications?status=unread&page=1', false],
      ['2', '', true],
      ['3', '/notifications?status=unread&page=3', false],
      ['…', '', false],
      ['8', '/notifications?status=unread&page=8', false],
    ]);
  });

  it('draws no pager for one page', () => {
    const one = create(GetNotificationCenterResponseSchema, { page: { page: 1, pageSize: 50, total: 3n, totalPages: 1 } });
    expect(notificationPager(one, {})).toBeUndefined();
  });

  it('keeps the filters but not the page or the saved notice', () => {
    expect(keptQuery({ q: 'x', page: '3', settings: 'saved', priority: '' })).toEqual({ q: 'x' });
  });
});

describe('priority tones (the template’s branches)', () => {
  it.each([
    ['urgent', 'danger', 'danger'],
    ['high', 'warning', 'warning'],
    ['normal', 'info', 'neutral'],
    ['low', 'neutral', 'neutral'],
    ['weird', 'neutral', 'neutral'],
  ])('%s', (priority, icon, pill) => {
    expect(priorityTone(priority)).toBe(icon);
    expect(priorityPillTone(priority)).toBe(pill);
  });
});
