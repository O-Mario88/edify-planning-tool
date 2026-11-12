import { describe, expect, it } from 'vitest';

import { safeIcon } from './icon';

const DASHBOARD =
  '<svg class="app-sidebar__item-icon-svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6a2 2 0 012-2h2" /></svg>';

describe('safeIcon', () => {
  it('draws the navigation outline icons', () => {
    expect(safeIcon(DASHBOARD)).toBe(DASHBOARD);
  });

  it.each([
    '<svg onload="alert(1)"><path d="M0 0"/></svg>',
    '<svg><script>alert(1)</script></svg>',
    '<svg><a href="javascript:alert(1)"><path d="M0 0"/></a></svg>',
    '<svg><foreignObject><div></div></foreignObject></svg>',
    '<svg><path d="M0 0" style="background:url(x)"/></svg>',
    '<img src=x onerror=alert(1)>',
    '<svg><path d="M0 0"/></svg><img src=x>',
  ])('refuses %s', (markup) => {
    expect(safeIcon(markup)).toBe('');
  });
});
