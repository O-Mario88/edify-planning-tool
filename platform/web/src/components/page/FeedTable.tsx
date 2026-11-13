'use client';

/*
 * A table card (PageTable): its title with the count beside it, the line
 * beside the title, the columns and rows, the empty state with its way out,
 * the note under it and its pager. A row may carry a tick box for the page's
 * bar, a tone (done, overdue, day off), its buttons and one Actions menu,
 * and what opening it shows. A row of one cell in a table of several columns
 * is a heading between groups. Tables stay tables on a phone and scroll
 * whole, with no frozen column (owner, 2026-09-30).
 */
import Link from 'next/link';
import { Fragment, useState } from 'react';

import type { PageAction, PageCell, PageRow, PageTable } from '@/gen/edify/screens/v1/page_pb';
import { actionHref, isActionsCell, isHeadingRow, resolveHref, splitActions } from '@/lib/feedPage';

import { Badge } from '../blocks/Badge';
import { RowActions } from '../blocks/RowActions';
import { textTone } from '../blocks/tones';
import { Icon } from '../shell/icons';
import { FeedPanel } from './FeedPanel';
import { Pager } from '../blocks/Pager';

export interface FeedTableProps {
  readonly table: PageTable;
  /** The page's own path, for the answer's bare-query links. */
  readonly pagePath: string;
  /** Where a drawer opens while drawers are the existing web's. */
  readonly drawerHref: string;
  /** The page has a bar for ticked rows. */
  readonly selectable: boolean;
}

const ROW_TONES: Readonly<Record<string, string>> = {
  done: 'bg-[var(--edify-success-light,#ecfdf5)]',
  overdue: 'bg-[var(--edify-danger-light,#fff1f2)]',
  dayoff: 'bg-[var(--edify-warning-light)]',
};

const CELL = 'whitespace-nowrap px-3 py-2 align-middle first:pl-4 last:pr-4';

function CellText({ cell, resolve }: { cell: PageCell; resolve: (href: string) => string }) {
  const href = resolve(cell.href);
  if (cell.badge) return <Badge tone={cell.tone}>{cell.text}</Badge>;
  const text = <span className={`${cell.strong ? 'font-semibold' : ''} ${textTone(cell.tone)}`}>{cell.text}</span>;
  return href ? (
    <Link href={href} className="font-medium text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-accent-text)]">
      {text}
    </Link>
  ) : (
    text
  );
}

function CellActions({ actions, subject, hrefOf }: { actions: readonly PageAction[]; subject: string; hrefOf: (action: PageAction) => string }) {
  const { buttons, menu } = splitActions(actions);
  return (
    <div className="flex items-center justify-end gap-2">
      {buttons.map((action) =>
        action.enabled ? (
          <a key={action.label} href={hrefOf(action)} className="inline-flex h-6 items-center rounded-[var(--radius-control)] border border-[var(--brand-primary-border)] bg-[var(--edify-surface)] px-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--brand-primary-text)] dark:text-[var(--edify-accent-text)]">
            {action.label}
          </a>
        ) : (
          <span key={action.label} title={action.reason || undefined} className="inline-flex h-6 cursor-not-allowed items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] px-3 text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text-subtle)]">
            {action.label}
          </span>
        ),
      )}
      <RowActions
        subject={subject}
        actions={menu.map((action) => ({ key: `${action.key}:${action.label}`, label: action.label, enabled: action.enabled, reason: action.reason, href: hrefOf(action) }))}
      />
    </div>
  );
}

function RowDetails({ row, columns, resolve, id, subject, drawerHref }: { row: PageRow; columns: number; resolve: (href: string) => string; id: string; subject: string; drawerHref: string }) {
  const detailsHref = resolve(row.detailsHref);
  return (
    <tr id={id} className="border-b border-[var(--edify-table-divider)] bg-[var(--edify-card-surface)]">
      <td colSpan={columns} className="px-4 py-3">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
          {row.details.map((fact) => {
            const href = resolve(fact.href);
            return (
              <div key={fact.label} className="min-w-0">
                <dt className="text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{fact.label}:</dt>
                <dd className={`truncate font-medium ${textTone(fact.tone)}`}>
                  {href ? <Link href={href} className="hover:underline">{fact.value}</Link> : fact.value}
                </dd>
              </div>
            );
          })}
        </dl>
        {row.detailBlocks.length ? (
          <div className="mt-3 grid gap-3">
            {row.detailBlocks.map((block, index) =>
              block.kind.case === 'panel' ? <FeedPanel key={index} panel={block.kind.value} resolve={resolve} drawerHref={drawerHref} nested /> : null,
            )}
          </div>
        ) : null}
        {detailsHref ? (
          <Link href={detailsHref} className="mt-3 inline-block text-[13px] font-semibold text-[var(--brand-primary-text)] underline dark:text-[var(--edify-accent-text)]">
            {/* templates/partials/planning/school_row.html */}
            Open {subject} school profile
          </Link>
        ) : null}
      </td>
    </tr>
  );
}

export function FeedTable({ table, pagePath, drawerHref, selectable }: FeedTableProps) {
  const resolve = (href: string) => resolveHref(pagePath, href);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const [open, setOpen] = useState<number | null>(null);
  const ticks = selectable && table.rows.some((row) => row.pickId);
  const opens = table.rows.some((row) => row.details.length || row.detailBlocks.length);
  const span = table.columns.length + (ticks ? 1 : 0) + (opens ? 1 : 0);
  const emptyHref = table.emptyAction ? hrefOf(table.emptyAction) : '';
  const titled = Boolean(table.title || table.count);

  return (
    <section aria-label={table.title || undefined} data-block="table" className="overflow-hidden rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-sm)]">
      {titled ? (
        <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--edify-border)] bg-[var(--edify-surface-muted)] px-4 py-2.5">
          <h2 className="text-[length:var(--edify-text-title-size)] font-bold">{table.title}</h2>
          {table.subtitle ? <span className="text-[length:var(--edify-text-label-size)] font-medium sm:ml-auto">{table.subtitle}</span> : null}
          {table.count ? <span className={`text-[length:var(--edify-text-label-size)] font-semibold ${table.subtitle ? '' : 'ml-auto'}`} data-count>{table.count}</span> : null}
        </header>
      ) : null}
      {table.rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] border-collapse text-left text-[13.7px]">
            {table.columns.length ? (
              <thead>
                <tr className="border-b border-[var(--edify-border)] text-[length:var(--edify-text-label-size)]">
                  {ticks ? (
                    <th scope="col" className={`${CELL} w-8`}>
                      <input
                        type="checkbox"
                        aria-label="Select all on this page"
                        className="h-4 w-4 accent-[var(--brand-primary)]"
                        onChange={(event) => {
                          const table = event.currentTarget.closest('table');
                          table?.querySelectorAll<HTMLInputElement>('input[data-pick]').forEach((box) => {
                            box.checked = event.currentTarget.checked;
                            box.dispatchEvent(new Event('change', { bubbles: true }));
                          });
                        }}
                      />
                    </th>
                  ) : null}
                  {opens ? <th scope="col" className={`${CELL} w-6`}><span className="sr-only">Details</span></th> : null}
                  {table.columns.map((column) => (
                    <th key={column.label} scope="col" className={`${CELL} whitespace-nowrap font-bold ${column.numeric ? 'text-right' : ''}`}>
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
            ) : null}
            <tbody>
              {table.rows.map((row, index) => {
                if (isHeadingRow(row, table.columns)) {
                  return (
                    <tr key={index} className="border-b border-[var(--edify-border)] bg-[var(--edify-surface-muted)]" data-heading>
                      <th colSpan={span} scope="rowgroup" className={`${CELL} font-bold`}>{row.cells[0]?.text}</th>
                    </tr>
                  );
                }
                const subject = row.cells.find((cell) => cell.href)?.text ?? row.cells[1]?.text ?? row.cells[0]?.text ?? '';
                const detailsId = `row-details-${index}`;
                const hasDetails = row.details.length > 0 || row.detailBlocks.length > 0;
                return (
                  <Fragment key={index}>
                    <tr className={`border-b border-[var(--edify-table-divider)] ${ROW_TONES[row.tone] ?? ''}`} data-row={row.pickId || undefined} data-tone={row.tone || undefined}>
                      {ticks ? (
                        <td className={CELL}>
                          {row.pickId ? (
                            <input type="checkbox" data-pick={row.pickId} aria-label={row.pickLabel || `Select ${subject}`} className="h-4 w-4 accent-[var(--brand-primary)]" />
                          ) : null}
                        </td>
                      ) : null}
                      {opens ? (
                        <td className={CELL}>
                          {hasDetails ? (
                            <button
                              type="button"
                              onClick={() => setOpen(open === index ? null : index)}
                              aria-expanded={open === index}
                              aria-controls={detailsId}
                              aria-label={open === index ? `Hide details for ${subject}` : `Show details for ${subject}`}
                              className="grid h-6 w-6 place-items-center rounded text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)]"
                            >
                              <Icon name="chevronRight" className={`h-4 w-4 transition-transform ${open === index ? 'rotate-90' : ''}`} />
                            </button>
                          ) : null}
                        </td>
                      ) : null}
                      {row.cells.map((cell, cellIndex) => (
                        <td key={cellIndex} className={`${CELL} ${table.columns[cellIndex]?.numeric ? 'text-right' : ''} ${isActionsCell(cell) ? 'w-px whitespace-nowrap' : ''}`}>
                          {isActionsCell(cell) ? <CellActions actions={cell.actions} subject={subject} hrefOf={hrefOf} /> : <CellText cell={cell} resolve={resolve} />}
                        </td>
                      ))}
                    </tr>
                    {open === index && hasDetails ? <RowDetails row={row} columns={span} resolve={resolve} id={detailsId} subject={subject} drawerHref={drawerHref} /> : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-4 py-5 text-[length:var(--edify-text-label-size)] font-medium" data-empty>
          {table.emptyMessage}
          {table.emptyAction && emptyHref ? (
            <>
              {' '}
              <a href={emptyHref} className="ml-1 font-semibold text-[var(--brand-primary-text)] underline dark:text-[var(--edify-accent-text)]">
                {table.emptyAction.label} →
              </a>
            </>
          ) : null}
        </p>
      )}
      {table.footnote ? <p className="border-t border-[var(--edify-table-divider)] px-4 py-3 text-[length:var(--edify-text-label-size)] font-medium">{table.footnote}</p> : null}
      {table.pager ? <Pager pager={{ ...table.pager, pages: table.pager.pages.map((page) => ({ ...page, href: resolve(page.href) })) }} /> : null}
    </section>
  );
}
