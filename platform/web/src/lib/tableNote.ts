/**
 * A table's explanation sent as a block of its own (owner, 2026-11-20: "hide
 * all the explanations ... using a chevron"): a panel with no title,
 * subtitle or badges holding one plain sentence or more, straight after a
 * table or after that table's pager. My Plan's training summary and
 * Programme Schools' partner line arrive so; a table's own footnote is the
 * other form. Such a note folds as the footnote does (Explanation.tsx).
 * Pure, so it is tested apart from the page; the app reads it the same way
 * (mobile/src/ui/page/tableNote.ts).
 */
import type { PageBlock } from '@/gen/edify/screens/v1/page_pb';

/** The fewest characters a note has: an explanation, not a status line. */
export const NOTE_MIN_LENGTH = 80;

/** A pager drawn under a table: the pager block, or a panel of page links. */
function isPager(block: PageBlock | undefined): boolean {
  const kind = block?.kind;
  if (kind?.case === 'pager') return true;
  return kind?.case === 'panel' && kind.value.items.some((item) => item.kind.case === 'links');
}

/** The note's words when the block at `index` is a table's note, else null. */
export function tableNote(blocks: readonly PageBlock[], index: number): string | null {
  const kind = blocks[index]?.kind;
  if (kind?.case !== 'panel') return null;
  const { title, subtitle, badges, items } = kind.value;
  const item = items[0];
  if (title || subtitle || badges.length > 0 || items.length !== 1 || item?.kind.case !== 'text') return null;
  if (item.lead || item.tone || item.textLinks.length > 0) return null;
  const text = item.kind.value.trim();
  if (text.length < NOTE_MIN_LENGTH) return null;
  let before = index - 1;
  while (before >= 0 && isPager(blocks[before])) before -= 1;
  return blocks[before]?.kind.case === 'table' ? text : null;
}
