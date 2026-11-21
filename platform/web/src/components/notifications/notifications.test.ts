import { create } from '@bufbuild/protobuf';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { NotificationDeliverySchema, NotificationItemSchema } from '@/gen/edify/screens/v1/notification_center_pb';

import { DeliverySettings } from './DeliverySettings';
import { NotificationList } from './NotificationList';

const WEB = 'http://localhost:8010';

function text(html: string): string {
  return html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();
}

describe('NotificationList', () => {
  const unread = create(NotificationItemSchema, {
    id: 'n1', title: '<b>Bold</b> & co', body: 'Body', categoryLabel: 'Follow_Up', priority: 'urgent', priorityLabel: 'Critical',
    unread: true, actionRequired: true, createdLabel: 'Nov 3, 2026 00:30', senderName: 'Pat', contextType: 'activity',
    contextId: 'None', targetRoute: '/activities/1?a=1&b=2', actionLabel: 'Open Record', canMarkRead: true, canArchive: true,
  });
  const archived = create(NotificationItemSchema, {
    id: 'n2', title: 'Old', categoryLabel: 'Hr', priority: 'low', priorityLabel: 'Low', status: 'archived', createdLabel: 'Oct 1, 2026 09:00',
  });

  it('draws a notification with every part the template shows, escaping its words', () => {
    const html = renderToStaticMarkup(createElement(NotificationList, { items: [unread, archived], existingWebUrl: WEB }));
    expect(html).toContain('&lt;b&gt;Bold&lt;/b&gt; &amp; co');
    expect(text(html)).toContain('Follow_Up Critical Action Required Body Nov 3, 2026 00:30 From Pat Link: activity (None)');
    expect(html).toContain(`href="${WEB}/activities/1?a=1&amp;b=2"`);
    expect(html).toMatch(/<button[^>]*type="submit"[^>]*>Mark read<\/button>/);
    expect(text(html)).toContain('Open Record Mark read Archive');
  });

  it('gives an archived notification neither Mark read nor Archive, and no record button without a record', () => {
    const html = renderToStaticMarkup(createElement(NotificationList, { items: [archived], existingWebUrl: WEB }));
    expect(text(html)).not.toMatch(/Mark read|Archive|Open Record|Action Required|From /);
  });

  it('says all caught up when nothing matches', () => {
    const html = renderToStaticMarkup(createElement(NotificationList, { items: [], existingWebUrl: WEB }));
    expect(text(html)).toContain('All caught up!');
  });
});

describe('DeliverySettings', () => {
  it('shows the choices as they stand, and the notice while email is not set up', () => {
    const delivery = create(NotificationDeliverySchema, {
      emailEnabled: false, pushEnabled: true, address: 'pl1@edify.org', emailConfigured: false, saved: true,
      categories: [{ value: 'leave_request', label: 'Leave_Request', muted: true }],
    });
    const words = text(renderToStaticMarkup(createElement(DeliverySettings, { delivery, existingWebUrl: WEB })));
    expect(words).toContain('Send push notifications (on)');
    expect(words).toContain('Email to pl1@edify.org Email is not set up on this server yet');
    expect(words).toContain('Email me (off)');
    expect(words).toContain("Don't email me about: ✓ Leave_Request (on)");
    expect(words).toContain('Saved.');
  });
});
