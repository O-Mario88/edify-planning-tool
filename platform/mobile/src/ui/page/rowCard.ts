/**
 * A table row read as a card for a phone (owner, 2026-11-19: "Rows on
 * phones"; docs/migration/181 Phase 5): its title (the record it names), its
 * ID, its status, the facts that lead (the table's first columns, as Go
 * orders them by importance) and the rest, which open under "All details".
 * The same choice as the web's (platform/web/src/lib/rowCard.ts). Pure, so
 * it is tested apart from the screen; nothing is counted or reworded here.
 */
import type { PageCell, PageColumn, PageRow } from '../../gen/edify/screens/v1/page_pb';

/** A cell with the label of its column. */
export interface RowFact {
  readonly label: string;
  readonly cell: PageCell;
  readonly numeric: boolean;
}

export interface RowCard {
  readonly title: PageCell | undefined;
  readonly id: RowFact | undefined;
  readonly status: PageCell | undefined;
  readonly lead: RowFact[];
  readonly rest: RowFact[];
  readonly actions: PageCell | undefined;
}

/** Facts a card shows before "All details". */
export const LEAD_FACTS = 4;

const ID_COLUMN = /\bid\b/i;
const STATUS_COLUMN = /\b(status|state)\b/i;

export function rowCard(columns: readonly PageColumn[], row: PageRow): RowCard {
  const cells = row.cells;
  const label = (i: number) => columns[i]?.label ?? '';
  const words = (i: number) => (cells[i]?.text ?? '').trim() !== '';
  const actionsAt = cells.findIndex((c) => c.actions.length > 0);
  const idAt = cells.findIndex((_, i) => i !== actionsAt && ID_COLUMN.test(label(i)) && words(i));
  const open = (i: number) => i !== actionsAt && i !== idAt && words(i);
  let titleAt = cells.findIndex((c, i) => open(i) && c.href !== '');
  if (titleAt < 0) titleAt = cells.findIndex((c, i) => open(i) && c.strong);
  if (titleAt < 0) titleAt = cells.findIndex((_, i) => open(i));
  const free = (i: number) => open(i) && i !== titleAt;
  let statusAt = cells.findIndex((_, i) => free(i) && STATUS_COLUMN.test(label(i)));
  if (statusAt < 0) statusAt = cells.findIndex((c, i) => free(i) && c.tone !== '' && !columns[i]?.numeric);
  const facts: RowFact[] = [];
  cells.forEach((cell, i) => {
    if (free(i) && i !== statusAt) facts.push({ label: label(i), cell, numeric: Boolean(columns[i]?.numeric) });
  });
  return {
    title: titleAt >= 0 ? cells[titleAt] : undefined,
    id: idAt >= 0 ? { label: label(idAt), cell: cells[idAt] as PageCell, numeric: false } : undefined,
    status: statusAt >= 0 ? cells[statusAt] : undefined,
    lead: facts.slice(0, LEAD_FACTS),
    rest: facts.slice(LEAD_FACTS),
    actions: actionsAt >= 0 ? cells[actionsAt] : undefined,
  };
}
