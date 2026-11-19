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
import type { ReactNode } from 'react';

import type { PageAction, PageCell, PageRow, PageTable } from '@/gen/edify/screens/v1/page_pb';
import { actionHref, isActionsCell, isHeadingRow, resolveHref, splitActions } from '@/lib/feedPage';

import { Badge } from '../blocks/Badge';
import { PlanningChips } from '../blocks/PlanningChips';
import { RowActions } from '../blocks/RowActions';
import { edifyTone, textTone } from '../blocks/tones';
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
  /** The list's pager strip when it arrives as a block of its own after the table. */
  readonly footer?: ReactNode;
}

const ROW_TONES: Readonly<Record<string, string>> = {
  done: 'bg-[var(--edify-success-light,#ecfdf5)]',
  overdue: 'bg-[var(--edify-danger-light,#fff1f2)]',
  dayoff: 'bg-[var(--edify-warning-light)]',
  // The record the rest of the page is about (the account whose memberships are open).
  selected: 'bg-[var(--brand-primary-soft)]',
};

const CELL = 'px-3 py-2';

function CellText({ cell, resolve }: { cell: PageCell; resolve: (href: string) => string }) {
  const href = resolve(cell.href);
  if (cell.pills.length) return <PlanningChips pills={cell.pills} />;
  if (cell.badge) return <Badge tone={cell.tone}>{cell.text}</Badge>;
  // The existing table's toned figure (`.edify-status-text[data-edify-tone]`).
  const tone = edifyTone(cell.tone);
  const text = tone ? (
    <span className={cell.strong ? 'edify-status-text font-semibold' : 'edify-status-text'} data-edify-tone={tone}>
      {cell.text}
    </span>
  ) : (
    <span className={cell.strong ? 'font-semibold' : undefined}>{cell.text}</span>
  );
  return href ? (
    <Link href={href} className="no-underline hover:opacity-90 font-semibold edify-primary-text">
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

/** A cell tone as the Admin dashboard's .admin-status colour. */
const ADMIN_STATUS: Readonly<Record<string, string>> = { danger: 's-red', warning: 's-orange', info: 's-blue', success: 's-green' };

/**
 * A table in the Admin dashboard's own card (.admin-panel around
 * .admin-table, partials/dashboards/admin/operations.html): the card's and
 * table's own class names, its head link and foot link, a status as its
 * coloured word, and the card's own empty row.
 */
function AdminTable({ table, resolve }: { table: PageTable; resolve: (href: string) => string }) {
  const headerHref = table.headerLink ? resolve(table.headerLink.href) : '';
  const footerHref = table.footerLink ? resolve(table.footerLink.href) : '';
  return (
    // A card with a header is a structured surface (static/js/micro-ux.js), which consistency.css reads for its padding.
    <section className={`${table.cardClass || 'admin-panel'} edify-structured-surface`} aria-label={table.title || undefined} data-block="table" data-family="admin-panel">
      <header className="admin-panel__header">
        <h2>
          {table.title}
          {table.count ? (
            <>
              {' '}
              <span className="admin-count">{table.count}</span>
            </>
          ) : null}
        </h2>
        {table.headerLink && headerHref ? <Link href={headerHref}>{table.headerLink.text}</Link> : null}
      </header>
      <div className="admin-table-wrap">
        <table className={table.tableClass || 'admin-table'}>
          {table.title ? <caption className="sr-only">{table.title}</caption> : null}
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column.label} scope="col">
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.length ? (
              table.rows.map((row, index) => (
                <tr key={index}>
                  {row.cells.map((cell, cellIndex) => {
                    const href = resolve(cell.href);
                    const status = ADMIN_STATUS[edifyTone(cell.tone)];
                    const text = status ? <span className={`admin-status ${status}`}>{cell.text}</span> : cell.strong ? <strong>{cell.text}</strong> : cell.text;
                    return (
                      <td key={cellIndex} data-label={table.columns[cellIndex]?.label || undefined}>
                        {href ? <Link href={href}>{text}</Link> : text}
                      </td>
                    );
                  })}
                </tr>
              ))
            ) : (
              <tr className="admin-table__empty-row">
                <td colSpan={Math.max(table.columns.length, 1)}>
                  <div className="admin-empty admin-empty--table">
                    <span>{table.emptyMessage}</span>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {table.pager ? <Pager pager={{ ...table.pager, pages: table.pager.pages.map((page) => ({ ...page, href: resolve(page.href) })) }} /> : null}
      </div>
      {table.footerLink && footerHref ? (
        <Link className="admin-panel__footer-link" href={footerHref}>
          {table.footerLink.text} <span aria-hidden="true">→</span>
        </Link>
      ) : null}
    </section>
  );
}

export function FeedTable({ table, pagePath, drawerHref, selectable, footer }: FeedTableProps) {
  const resolve = (href: string) => resolveHref(pagePath, href);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const [open, setOpen] = useState<number | null>(null);
  if (table.family === 'admin-panel') return <AdminTable table={table} resolve={resolve} />;
  const ticks = selectable && table.rows.some((row) => row.pickId);
  const opens = table.rows.some((row) => row.details.length || row.detailBlocks.length);
  const span = table.columns.length + (ticks ? 1 : 0) + (opens ? 1 : 0);
  const emptyHref = table.emptyAction ? hrefOf(table.emptyAction) : '';
  const titled = Boolean(table.title || table.count);

  return (
    <section aria-label={table.title || undefined} data-block="table" className="card p-0 overflow-hidden">
      {titled ? (
        <header className="edify-table-titlebar flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-3">
          <h3>{table.title}</h3>
          {table.subtitle || table.count ? (
            <span className="tabular-nums">
              {table.subtitle}
              {table.subtitle && table.count ? ' · ' : ''}
              {table.count ? <span data-count>{table.count}</span> : null}
            </span>
          ) : null}
        </header>
      ) : null}
      {table.rows.length ? (
        <div className="overflow-x-auto">
          <table className="edify-record-table edify-data-table w-full text-left text-[12px] whitespace-nowrap" data-mobile-table="scroll">
            {table.columns.length ? (
              <thead>
                <tr>
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
                    <th key={column.label} scope="col" className={`${CELL} ${column.numeric ? 'text-right' : ''}`}>
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
                    <tr key={index} className="edify-group-head" data-heading>
                      <th colSpan={span} scope="colgroup">
                        <span className="edify-group-head__label">{row.cells[0]?.text}</span>
                      </th>
                    </tr>
                  );
                }
                const subject = row.cells.find((cell) => cell.href)?.text ?? row.cells[1]?.text ?? row.cells[0]?.text ?? '';
                const detailsId = `row-details-${index}`;
                const hasDetails = row.details.length > 0 || row.detailBlocks.length > 0;
                return (
                  <Fragment key={index}>
                    <tr className={ROW_TONES[row.tone] ?? undefined} data-row={row.pickId || undefined} data-tone={row.tone || undefined}>
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
                        <td
                          key={cellIndex}
                          className={`${CELL} ${table.columns[cellIndex]?.numeric ? 'text-right tabular-nums' : ''} ${isActionsCell(cell) ? 'w-px' : ''}`}
                          data-label={table.columns[cellIndex]?.label || undefined}
                        >
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
        // The existing empty state on a line (components/empty_state.html, line="true").
        <div className="edify-empty-state edify-empty-state--line" data-empty>
          <span className="edify-empty-state__mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
              />
            </svg>
          </span>
          <p className="edify-empty-state__message">{table.emptyMessage}</p>
          {table.emptyAction && emptyHref ? (
            <a href={emptyHref} className="font-semibold edify-primary-text edify-primary-text-hover underline underline-offset-2">
              {table.emptyAction.label} <span aria-hidden="true">→</span>
            </a>
          ) : null}
        </div>
      )}
      {table.footnote ? <p className="border-t edify-border-top px-4 py-3 edify-text-caption edify-text-muted">{table.footnote}</p> : null}
      {table.pager ? <Pager pager={{ ...table.pager, pages: table.pager.pages.map((page) => ({ ...page, href: resolve(page.href) })) }} /> : null}
      {footer}
    </section>
  );
}
