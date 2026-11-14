import { create } from '@bufbuild/protobuf';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { PageActionSchema } from '@/gen/edify/screens/v1/page_pb';

import { HeaderAction } from './PageHeader';

describe('HeaderAction', () => {
  it('marks an export as a download', () => {
    const action = create(PageActionSchema, { key: 'export', label: 'Export', enabled: true, href: '/planning?export=csv', download: true });

    const html = renderToStaticMarkup(createElement(HeaderAction, { action, href: action.href }));

    expect(html).toContain('download=""');
    expect(html).toContain('href="/planning?export=csv"');
  });

  it('leaves a link to a page without the download mark', () => {
    const action = create(PageActionSchema, { key: 'scoring', label: 'Scoring', enabled: true, href: '/cluster-oversight/scoring' });

    const html = renderToStaticMarkup(createElement(HeaderAction, { action, href: action.href }));

    expect(html).not.toContain('download');
  });
});
