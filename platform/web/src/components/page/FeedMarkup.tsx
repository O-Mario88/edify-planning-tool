/*
 * A part of the existing page drawn from its element structure (PageMarkup:
 * the Admin dashboard's workspace of bespoke cards), with the existing
 * stylesheets the root layout links. Every element is checked again
 * (lib/markupTree) and built with createElement; nothing is raw HTML.
 */
import { createElement, Fragment } from 'react';
import type { ReactNode } from 'react';

import type { PageMarkup, PageMarkupNode } from '@/gen/edify/screens/v1/page_pb';
import { ALLOWED_TAGS, markupProps } from '@/lib/markupTree';

/** Table parts, where HTML allows no text of their own (whitespace included). */
const NO_TEXT = new Set(['table', 'thead', 'tbody', 'tfoot', 'tr']);

function draw(node: PageMarkupNode, key: number): ReactNode {
  if (!node.tag) return node.text;
  if (!ALLOWED_TAGS.has(node.tag)) return null;
  if (node.tag === 'br') return createElement('br', { key });
  const kept = NO_TEXT.has(node.tag) ? node.children.filter((child) => child.tag || child.text.trim()) : node.children;
  const children = kept.map((child, index) => draw(child, index));
  return createElement(node.tag, { key, ...markupProps(node) }, ...children);
}

export function FeedMarkup({ markup }: { markup: PageMarkup }) {
  if (!markup.root) return null;
  return <Fragment>{draw(markup.root, 0)}</Fragment>;
}
