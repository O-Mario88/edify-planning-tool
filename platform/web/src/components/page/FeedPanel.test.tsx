import { readdirSync } from 'node:fs';
import { join, sep } from 'node:path';

import { create } from '@bufbuild/protobuf';
import type { ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { PagePanelSchema } from '@/gen/edify/screens/v1/page_pb';
import { isRouteHandlerHref } from '@/lib/feedPage';

import { FeedPanel } from './FeedPanel';

// A client link is the one Next prefetches, so the tests tell it from a plain <a>.
vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href} data-client-link="">
      {children}
    </a>
  ),
}));

const APP_FOLDER = join(process.cwd(), 'src', 'app');

const panelLinking = (text: string, href: string) =>
  create(PagePanelSchema, {
    title: 'School loan applications',
    items: [{ kind: { case: 'links', value: { links: [{ text, href }] } } }],
  });

const draw = (text: string, href: string) =>
  renderToStaticMarkup(<FeedPanel panel={panelLinking(text, href)} resolve={(value) => value} />);

/** Every file with this name under src/app, as the path a browser asks for. */
function appPaths(fileName: string): string[] {
  return readdirSync(APP_FOLDER, { recursive: true, encoding: 'utf8' })
    .filter((file) => file.split(sep).at(-1) === fileName)
    .map((file) => file.split(sep).slice(0, -1))
    .map((parts) => parts.filter((part) => !/^\(.*\)$/.test(part)).map((part) => (part.startsWith('[') ? 'x' : part)))
    .map((parts) => `/${parts.join('/')}`);
}

describe('FeedPanel links', () => {
  it('opens the loan application form with a plain link, which Next never prefetches', () => {
    const html = draw('Open form', '/loan-applications/apply');

    expect(html).toContain('href="/loan-applications/apply"');
    expect(html).not.toContain('data-client-link');
  });

  it('opens the SSA template download with a plain link', () => {
    expect(draw('Download Template', '/ssa/upload/template')).not.toContain('data-client-link');
  });

  it('keeps a client link to a page', () => {
    expect(draw('SSA upload', '/ssa/upload')).toContain('data-client-link');
  });
});

describe('isRouteHandlerHref', () => {
  it('knows every route handler in the app', () => {
    const handlers = appPaths('route.ts');

    expect(handlers.length).toBeGreaterThan(0);
    expect(handlers.filter((path) => !isRouteHandlerHref(path))).toEqual([]);
  });

  it('never takes a page for a route handler', () => {
    const pages = appPaths('page.tsx');

    expect(pages.length).toBeGreaterThan(0);
    expect(pages.filter((path) => isRouteHandlerHref(path))).toEqual([]);
  });

  it('reads the path of a link with a query or a fragment', () => {
    expect(isRouteHandlerHref('/loan-applications/apply?from=loans')).toBe(true);
    expect(isRouteHandlerHref('/exports/plan#top')).toBe(true);
    expect(isRouteHandlerHref('/loan-applications')).toBe(false);
    expect(isRouteHandlerHref('/apply-now')).toBe(false);
  });
});
