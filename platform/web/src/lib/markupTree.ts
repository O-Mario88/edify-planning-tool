/**
 * A part of the existing page carried as its own element structure
 * (PageMarkup, read by apps/mobile_feed/markup_tree.py), checked again here
 * before it is drawn: only the same safe elements, class names, in-app
 * links, the attributes the stylesheets and screen readers read, and sizes
 * in percent or pixels. Nothing is drawn as raw HTML.
 */
import type { PageMarkupNode } from '@/gen/edify/screens/v1/page_pb';

export const ALLOWED_TAGS = new Set([
  'div', 'section', 'article', 'aside', 'header', 'footer', 'nav', 'figure', 'figcaption',
  'h2', 'h3', 'h4', 'p', 'span', 'strong', 'b', 'em', 'i', 'small', 'time', 'a',
  'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'br',
  'table', 'caption', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
  'svg', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'g', 'ellipse',
]);

/** Attribute names as React spells them; anything else is not carried. */
const REACT_NAMES: Readonly<Record<string, string>> = {
  id: 'id',
  title: 'title',
  role: 'role',
  scope: 'scope',
  colspan: 'colSpan',
  rowspan: 'rowSpan',
  datetime: 'dateTime',
  viewBox: 'viewBox',
  fill: 'fill',
  stroke: 'stroke',
  'stroke-width': 'strokeWidth',
  'stroke-linecap': 'strokeLinecap',
  'stroke-linejoin': 'strokeLinejoin',
  d: 'd',
  cx: 'cx',
  cy: 'cy',
  r: 'r',
  rx: 'rx',
  ry: 'ry',
  x: 'x',
  y: 'y',
  x1: 'x1',
  x2: 'x2',
  y1: 'y1',
  y2: 'y2',
  points: 'points',
  width: 'width',
  height: 'height',
  transform: 'transform',
};

const NAMED_ATTR = /^(?:aria|data)-[a-z0-9-]{1,40}$/;
const SIZE = /^\d+(?:\.\d+)?(?:%|px)?$/;
const STYLE_PROPS = new Set(['width', 'height', '--w']);
const MAX_VALUE = 500;

/** A link within the app: a path (not //host), a query or a fragment. */
export function safeHref(value: string): string {
  const href = value.trim();
  if (href.startsWith('//') || !['/', '?', '#'].includes(href.charAt(0)) || href.length > MAX_VALUE) return '';
  return href;
}

/** The element's props: its class names, the carried attributes and sizes. */
export function markupProps(node: PageMarkupNode): Record<string, unknown> {
  const props: Record<string, unknown> = {};
  if (node.className) props.className = node.className;
  for (const [name, value] of Object.entries(node.attrs)) {
    if (value.length > MAX_VALUE) continue;
    if (name === 'href') {
      if (node.tag === 'a' && safeHref(value)) props.href = safeHref(value);
    } else if (NAMED_ATTR.test(name)) {
      props[name] = value;
    } else if (REACT_NAMES[name]) {
      props[REACT_NAMES[name]] = value;
    }
  }
  const style: Record<string, string> = {};
  for (const [prop, value] of Object.entries(node.style)) {
    if (STYLE_PROPS.has(prop) && SIZE.test(value)) style[prop] = value;
  }
  if (Object.keys(style).length) props.style = style;
  return props;
}
