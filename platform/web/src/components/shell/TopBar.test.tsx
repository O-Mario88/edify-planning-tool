/** The top bar's badges carry the reader's unread figures, as the existing shell's do. */
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { TopBar } from './TopBar';

const account = { name: 'Paul N.', initials: 'PN', activeRole: 'CCEO', roles: [{ value: 'CCEO', label: 'CCEO' }], path: '/schools/1000' };
const search = { action: '/schools', placeholder: 'Search schools', value: '', keep: {} };

function draw(counts: { messages: number; notifications: number }): string {
  return renderToStaticMarkup(<TopBar search={search} account={account} existingWebUrl="http://localhost:8182" counts={counts} />);
}

describe('the top bar’s badges', () => {
  it('draws the notifications figure on the bell and none on Messages at zero', () => {
    const html = draw({ messages: 0, notifications: 4 });
    expect(html.match(/data-count-badge/g)).toHaveLength(1);
    expect(html).toMatch(/aria-label="Notifications, 4 unread"[^]*?data-count-badge[^>]*>4<\/span>/);
    expect(html).toMatch(/aria-label="Messages"/);
  });

  it('caps a long figure at 99+', () => {
    expect(draw({ messages: 138, notifications: 0 })).toMatch(/aria-label="Messages, 99\+ unread"[^]*?data-count-badge[^>]*aria-hidden="true"[^>]*>99\+<\/span>/);
  });
});
