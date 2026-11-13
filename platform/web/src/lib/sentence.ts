/**
 * A paragraph the page feed reads whole (PagePanelItem text with `lead` and
 * `textLinks`): split into its bold opening, plain runs and its links at the
 * words they carry, in order. Words a link names that the text does not hold
 * are left as text (the link is not invented elsewhere).
 */
import type { PageLink, PagePanel } from '@/gen/edify/screens/v1/page_pb';

export type SentencePart =
  | { readonly kind: 'lead'; readonly text: string }
  | { readonly kind: 'text'; readonly text: string }
  | { readonly kind: 'link'; readonly text: string; readonly href: string };

export function sentenceParts(text: string, lead: string, links: readonly Pick<PageLink, 'text' | 'href'>[]): SentencePart[] {
  const parts: SentencePart[] = [];
  let rest = text;
  if (lead && rest.startsWith(lead)) {
    parts.push({ kind: 'lead', text: lead });
    rest = rest.slice(lead.length);
  }
  for (const link of links) {
    const at = link.text ? rest.indexOf(link.text) : -1;
    if (at < 0) continue;
    if (at > 0) parts.push({ kind: 'text', text: rest.slice(0, at) });
    parts.push({ kind: 'link', text: link.text, href: link.href });
    rest = rest.slice(at + link.text.length);
  }
  if (rest) parts.push({ kind: 'text', text: rest });
  return parts;
}

/** The tones a note is drawn in (the existing .edify-note[data-tone]). */
const NOTE_TONES = new Set(['info', 'warning', 'danger', 'success']);

/**
 * The tone of a panel that is a note (an untitled card of toned paragraphs
 * only: Planning's workload line, My Plan's past-due line), else ''.
 */
export function noteTone(panel: Pick<PagePanel, 'title' | 'badges' | 'items'>): string {
  if (panel.title || panel.badges.length || !panel.items.length) return '';
  const tones = panel.items.map((item) => (item.kind.case === 'text' && NOTE_TONES.has(item.tone) ? item.tone : ''));
  return tones.every(Boolean) ? (tones[0] ?? '') : '';
}
