/**
 * A part carried as its element structure is drawn with the existing class
 * names, in-app links and sizes, and anything unsafe that reaches the web
 * app is dropped here too: other elements, script links, handlers and other
 * styles.
 */
import { create } from '@bufbuild/protobuf';
import type { MessageInitShape } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { PageMarkupSchema } from '@/gen/edify/screens/v1/page_pb';

import { FeedMarkup } from './FeedMarkup';

const draw = (markup: MessageInitShape<typeof PageMarkupSchema>) => renderToStaticMarkup(<FeedMarkup markup={create(PageMarkupSchema, markup)} />);

describe('a part drawn from its elements', () => {
  it('keeps its classes, links, attributes and sizes', () => {
    const html = draw({
      root: {
        tag: 'section',
        className: 'admin-panel admin-planning-progress',
        attrs: { 'aria-labelledby': 't', 'data-card-key': 'planning_progress' },
        children: [
          { tag: 'a', attrs: { href: '?progress_period=week', 'aria-current': 'true', 'data-edify-tab': '' }, className: 'is-active', children: [{ text: 'Week' }] },
          { tag: 'span', style: { height: '36%' }, children: [{ tag: 'strong', children: [{ text: '36%' }] }] },
          { tag: 'svg', attrs: { viewBox: '0 0 24 24', 'stroke-width': '2' }, children: [{ tag: 'path', attrs: { d: 'M5 12h14' } }] },
          { tag: 'td', attrs: { colspan: '4' } },
        ],
      },
    });
    expect(html).toContain('<section class="admin-panel admin-planning-progress" aria-labelledby="t" data-card-key="planning_progress">');
    expect(html).toContain('<a class="is-active" href="?progress_period=week" aria-current="true" data-edify-tab="">Week</a>');
    expect(html).toContain('<span style="height:36%"><strong>36%</strong></span>');
    expect(html).toContain('<svg viewBox="0 0 24 24" stroke-width="2"><path d="M5 12h14"></path></svg>');
    expect(html).toContain('<td colSpan="4"></td>');
  });

  it('drops what is not safe, even if it reaches the web app', () => {
    const html = draw({
      root: {
        tag: 'div',
        attrs: { onclick: 'x()' },
        children: [
          { tag: 'a', attrs: { href: 'javascript:alert(1)', onmouseover: 'x()' }, children: [{ text: 'bad' }] },
          { tag: 'a', attrs: { href: '//evil.example/x' }, children: [{ text: 'far' }] },
          { tag: 'script', children: [{ text: 'alert(1)' }] },
          { tag: 'img', attrs: { src: '/x', onerror: 'x()' } },
          { tag: 'span', style: { background: 'url(x)', width: 'calc(100% - 1px)' } },
        ],
      },
    });
    expect(html).toBe('<div><a>bad</a><a>far</a><span></span></div>');
  });
});
