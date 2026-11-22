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
import { useRouter } from 'next/navigation';
import { Fragment, useId, useState, useTransition } from 'react';
import type { ReactNode } from 'react';

import { transitionTeamAction } from '@/app/(app)/actions/transition';
import type { PageAction, PageCell, PageRow, PageTable } from '@/gen/edify/screens/v1/page_pb';
import { actionHref, isActionsCell, isHeadingRow, resolveHref, splitActions } from '@/lib/feedPage';
import { titleCase } from '@/lib/titleCase';

import { Badge } from '../blocks/Badge';
import { PlanningChips } from '../blocks/PlanningChips';
import { RowActions } from '../blocks/RowActions';
import { edifyTone, textTone } from '../blocks/tones';
import { Explanation } from './Explanation';
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

const INTERACTIVE_SELECTOR = 'a, button, input, label, select, textarea, [role="menu"], [role="menuitem"], [data-row-actions]';

function isInteractiveTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest(INTERACTIVE_SELECTOR));
}

/** Stable identifier for a row so filtering, sorting or paging cannot attach details to another record. */
export function stableRowKey(row: PageRow, fallbackIndex: number): string {
  if (row.pickId) return `pick:${row.pickId}`;
  if (row.detailsHref) return `detail:${row.detailsHref}`;
  const linked = row.cells.find((cell) => cell.href);
  if (linked?.href) return `href:${linked.href}:${row.cells[0]?.text ?? ''}`;
  const signature = row.cells
    .map((cell) => cell.text.trim())
    .filter(Boolean)
    .slice(0, 3)
    .join('|');
  return signature ? `sig:${signature}` : `row:${fallbackIndex}`;
}

function profileLinkLabel(subject: string, href: string): string {
  if (href.startsWith('/clusters/')) return `Open ${subject} cluster profile`;
  if (href.startsWith('/schools/')) return `Open ${subject} school profile`;
  return `Open ${subject} profile`;
}

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
  if (!href) return text;
  if (href.includes('format=csv') || href.startsWith('/exports/')) {
    return (
      <a href={href} download className="inline no-underline hover:underline font-semibold edify-primary-text">
        {text}
      </a>
    );
  }
  return (
    <Link href={href} className="inline no-underline hover:underline font-semibold edify-primary-text">
      {text}
    </Link>
  );
}

const TEAM_ACTION_POST_RE = /^\/actions\/[A-Za-z0-9_-]+\/(acknowledge|start|block|return|cancel|escalate|resolve)$/;

export function CellActions({ actions, subject, hrefOf }: { actions: readonly PageAction[]; subject: string; hrefOf: (action: PageAction) => string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [feedback, setFeedback] = useState<string | null>(null);
  const { buttons, menu } = splitActions(actions);
  return (
    <div className="flex items-center justify-end gap-2">
      {feedback ? (
        <span role="alert" className="text-[11px] font-semibold text-[#be123c] dark:text-[var(--edify-danger)]">
          {feedback}
        </span>
      ) : null}
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
        actions={menu.map((action) => {
          const href = hrefOf(action);
          const isTeamPost = action.enabled && !action.drawer && TEAM_ACTION_POST_RE.test(href.split('?')[0] ?? '');
          return {
            key: `${action.key}:${action.label}`,
            label: pending && isTeamPost ? `${action.label}…` : action.label,
            enabled: action.enabled && !pending,
            reason: action.reason,
            href,
            onSelect: isTeamPost
              ? () => {
                  setFeedback(null);
                  startTransition(async () => {
                    const res = await transitionTeamAction(href);
                    if (res.ok) {
                      router.refresh();
                    } else {
                      setFeedback(res.message);
                    }
                  });
                }
              : undefined,
          };
        })}
      />
    </div>
  );
}

function RowDetails({ row, columns, resolve, id, subject, drawerHref }: { row: PageRow; columns: number; resolve: (href: string) => string; id: string; subject: string; drawerHref: string }) {
  const detailsHref = resolve(row.detailsHref);
  return (
    <tr
      id={id}
      data-row-details=""
      onClick={(event) => event.stopPropagation()}
      className="border-b border-[var(--edify-table-divider)] bg-[var(--edify-card-surface)] whitespace-normal"
    >
      <td colSpan={columns} className="space-y-3 px-4 py-3">
        {detailsHref ? (
          <div>
            <Link href={detailsHref} className="inline text-[13px] font-bold text-[var(--edify-text)] hover:underline">
              {profileLinkLabel(subject, detailsHref)}
            </Link>
          </div>
        ) : null}
        {row.details.length ? (
          <dl className="flex flex-wrap gap-x-5 gap-y-1.5 text-[length:var(--edify-text-label-size)]">
            {row.details.map((fact) => {
              const href = resolve(fact.href);
              return (
                <div key={fact.label} className="flex min-w-0 items-baseline gap-1">
                  <dt className="font-medium text-[var(--edify-text-muted)]">{fact.label}:</dt>
                  <dd className={`font-semibold ${textTone(fact.tone)}`}>
                    {href ? (
                      <Link href={href} className="inline text-[var(--brand-primary-text)] hover:underline dark:text-[var(--edify-accent-text)]">
                        {fact.value}
                      </Link>
                    ) : (
                      fact.value
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        ) : null}
        {row.detailBlocks.length ? (
          <div className="space-y-3">
            {row.detailBlocks.map((block, index) =>
              block.kind.case === 'panel' ? <FeedPanel key={index} panel={block.kind.value} resolve={resolve} drawerHref={drawerHref} nested /> : null,
            )}
          </div>
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
        <table className={table.tableClass || 'admin-table'} data-titled>
          {table.title ? <caption className="sr-only">{table.title}</caption> : null}
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column.label} scope="col">
                  {titleCase(column.label)}
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
  const [openKey, setOpenKey] = useState<string | null>(null);
  const tableId = useId();
  if (table.family === 'admin-panel') return <AdminTable table={table} resolve={resolve} />;
  const ticks = selectable && table.rows.some((row) => row.pickId);
  const span = table.columns.length + (ticks ? 1 : 0);
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
        // A region a keyboard can reach and scroll (WCAG: scrollable-region-focusable).
        <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={`${table.title || 'Table'}, scrolls sideways`}>
          <table className="edify-record-table edify-data-table w-full text-left text-[12px] whitespace-nowrap" data-mobile-table="scroll" data-titled>
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
                          const tbl = event.currentTarget.closest('table');
                          tbl?.querySelectorAll<HTMLInputElement>('input[data-pick]').forEach((box) => {
                            box.checked = event.currentTarget.checked;
                            box.dispatchEvent(new Event('change', { bubbles: true }));
                          });
                        }}
                      />
                    </th>
                  ) : null}
                  {table.columns.map((column) => (
                    <th key={column.label} scope="col" className={`${CELL} ${column.numeric ? 'text-right' : ''}`}>
                      {titleCase(column.label)}
                    </th>
                  ))}
                </tr>
              </thead>
            ) : null}
            <tbody>
              {table.rows.map((row, index) => {
                if (isHeadingRow(row, table.columns)) {
                  return (
                    <tr key={`head:${row.cells[0]?.text ?? index}`} className="edify-group-head" data-heading>
                      <th colSpan={span} scope="colgroup">
                        <span className="edify-group-head__label">{row.cells[0]?.text}</span>
                      </th>
                    </tr>
                  );
                }
                const rowKey = stableRowKey(row, index);
                const subject = row.cells.find((cell) => cell.href)?.text ?? row.cells[1]?.text ?? row.cells[0]?.text ?? '';
                const detailsId = `row-details-${tableId}-${rowKey.replace(/[^A-Za-z0-9_-]/g, '-')}`;
                const hasDetails = row.details.length > 0 || row.detailBlocks.length > 0;
                const isOpen = openKey === rowKey;
                const rowTone = ROW_TONES[row.tone] ?? '';
                const interactiveClass = hasDetails
                  ? 'cursor-pointer transition-colors hover:bg-[color-mix(in_oklab,var(--edify-surface-muted)_55%,transparent)] focus-within:bg-[color-mix(in_oklab,var(--edify-surface-muted)_40%,transparent)]'
                  : '';
                return (
                  <Fragment key={rowKey}>
                    <tr
                      className={`${rowTone} ${interactiveClass}`.trim() || undefined}
                      data-row={row.pickId || undefined}
                      data-tone={row.tone || undefined}
                      data-open={isOpen ? 'true' : undefined}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (!hasDetails || isInteractiveTarget(event.target)) return;
                        if (window.getSelection()?.toString()) return;
                        setOpenKey(isOpen ? null : rowKey);
                      }}
                    >
                      {ticks ? (
                        <td className={CELL}>
                          {row.pickId ? (
                            <input type="checkbox" data-pick={row.pickId} aria-label={row.pickLabel || `Select ${subject}`} className="h-4 w-4 accent-[var(--brand-primary)]" />
                          ) : null}
                        </td>
                      ) : null}
                      {row.cells.map((cell, cellIndex) => (
                        <td
                          key={cellIndex}
                          className={`${CELL} ${table.columns[cellIndex]?.numeric ? 'text-right tabular-nums' : ''} ${isActionsCell(cell) ? 'w-px' : ''}`}
                          data-label={table.columns[cellIndex]?.label || undefined}
                        >
                          {cellIndex === 0 && hasDetails ? (
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                setOpenKey(isOpen ? null : rowKey);
                              }}
                              aria-expanded={isOpen}
                              aria-controls={detailsId}
                              aria-label={isOpen ? `Hide details for ${subject}` : `Show details for ${subject}`}
                              className="sr-only focus:not-sr-only focus:mr-1.5 focus:inline-flex focus:items-center focus:rounded focus:bg-[var(--edify-surface)] focus:px-1.5 focus:py-0.5 focus:text-[11px] focus:font-semibold focus:text-[var(--brand-primary-text)] focus:outline focus:outline-2 focus:outline-[var(--edify-accent)]"
                            >
                              {isOpen ? 'Hide details' : 'Show details'}
                            </button>
                          ) : null}
                          {isActionsCell(cell) ? <CellActions actions={cell.actions} subject={subject} hrefOf={hrefOf} /> : <CellText cell={cell} resolve={resolve} />}
                        </td>
                      ))}
                    </tr>
                    {isOpen && hasDetails ? <RowDetails row={row} columns={span} resolve={resolve} id={detailsId} subject={subject} drawerHref={drawerHref} /> : null}
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
      {table.footnote ? <Explanation text={table.footnote} /> : null}
      {table.pager ? <Pager pager={{ ...table.pager, pages: table.pager.pages.map((page) => ({ ...page, href: resolve(page.href) })) }} /> : null}
      {footer}
    </section>
  );
}
