/**
 * The navigation's icons arrive as SVG markup (NavItem.icon_svg, the drawing
 * the web page uses). They are drawn only when they are plain outline
 * drawings: no script, no event handler, no link, no foreign content.
 */
const ALLOWED_TAGS = new Set(['svg', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'ellipse', 'g']);
const ALLOWED_ATTRIBUTES = new Set([
  'class', 'fill', 'viewbox', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'd', 'cx', 'cy',
  'r', 'rx', 'ry', 'x', 'y', 'x1', 'x2', 'y1', 'y2', 'width', 'height', 'points', 'xmlns', 'aria-hidden',
  'fill-rule', 'clip-rule', 'transform', 'opacity', 'stroke-miterlimit',
]);
const TAG = /<\/?\s*([a-zA-Z][\w:-]*)([^>]*)>/g;
const ATTRIBUTE = /([a-zA-Z_:][\w:.-]*)\s*=\s*("[^"]*"|'[^']*')/g;

function attributesAllowed(attributes: string): boolean {
  let allowed = true;
  const leftover = attributes.replace(ATTRIBUTE, (_all, attribute: string) => {
    if (!ALLOWED_ATTRIBUTES.has(attribute.toLowerCase())) allowed = false;
    return '';
  });
  return allowed && !leftover.replace(/\//g, '').trim();
}

export function isSafeIcon(markup: string): boolean {
  const text = markup.trim();
  if (!text.startsWith('<svg') || !text.endsWith('</svg>')) return false;
  if (/javascript:|url\(|&#|<!|<\?/i.test(text)) return false;
  let rest = text;
  for (const match of text.matchAll(TAG)) {
    const [whole, name = '', attributes = ''] = match;
    if (!ALLOWED_TAGS.has(name.toLowerCase()) || !attributesAllowed(attributes)) return false;
    rest = rest.replace(whole, '');
  }
  return rest.trim() === '';
}

/** The markup if it is safe to draw, otherwise nothing. */
export function safeIcon(markup: string): string {
  return isSafeIcon(markup) ? markup : '';
}
