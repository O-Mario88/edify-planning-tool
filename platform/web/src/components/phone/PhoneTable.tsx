'use client';

/*
 * A record table as the app draws it (PageTableView.tsx): a card with its
 * title bar, the table scrolling sideways in its own region (owner,
 * 2026-09-27: tables stay tables), a note under it, or the empty state in
 * place of its rows. A table wider than the screen shows the slim orange
 * "Swipe to view more columns" pill once, which leaves after about four
 * seconds (owner, 2026-10-02). A row with details opens under itself, one
 * at a time; ticked rows feed the page's bar (input[data-pick]).
 */
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Fragment, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import type { PageAction, PageRow, PageTable } from '@/gen/edify/screens/v1/page_pb';
import { actionHref, isActionsCell, resolveHref } from '@/lib/feedPage';

import { CellActions } from '../page/FeedTable';
import { PhoneEmpty, PhonePager } from './PhoneParts';
import { phoneTone } from './tone';

/** The hint shows once per visit, as the app's does until a swipe. */
let hintSeen = false;

/** What a row is called: the record it links to, else its first words. */
function rowName(row: PageRow): string {
  return row.cells.find((cell) => cell.href && cell.text)?.text || row.cells.find((cell) => cell.text)?.text || 'this row';
}

export interface PhoneTableProps {
  readonly table: PageTable;
  /** The page's own path, for the answer's bare-query links. */
  readonly pagePath: string;
  /** Where a drawer opens while drawers are the existing web's. */
  readonly drawerHref: string;
  /** The page has a bar for ticked rows. */
  readonly selectable: boolean;
  /** Drawn inside another card (a segment): no card of its own. */
  readonly bare?: boolean;
  /** A pager strip that arrived as its own block after the table. */
  readonly footer?: ReactNode;
}

export function PhoneTable({ table, pagePath, drawerHref, selectable, bare = false, footer }: PhoneTableProps) {
  const resolve = (href: string) => resolveHref(pagePath, href);
  const hrefOf = (action: PageAction) => actionHref(action, pagePath, drawerHref);
  const hasTitle = Boolean(table.title || table.subtitle || table.count);
  const body = (
    <>
      {hasTitle ? (
        <div data-ph="titlebar">
          {table.title ? <h2 data-ph="table-title">{table.title}</h2> : null}
          {table.subtitle ? <span data-ph="table-subtitle">{table.subtitle}</span> : null}
          {table.count ? (
            <span data-ph="table-count" aria-label={`${table.count} listed`}>
              {table.count}
            </span>
          ) : null}
        </div>
      ) : null}
      {table.rows.length === 0 && table.emptyMessage ? (
        <PhoneEmpty message={table.emptyMessage} action={table.emptyAction} hrefOf={hrefOf} />
      ) : (
        <Grid table={table} resolve={resolve} hrefOf={hrefOf} selectable={selectable} />
      )}
      {table.pager ? <PhonePager pager={table.pager} resolve={resolve} /> : null}
      {footer}
      {table.footnote ? <p data-ph="footnote">{table.footnote}</p> : null}
    </>
  );
  return bare ? body : <section data-ph="card" aria-label={table.title || undefined}>{body}</section>;
}

interface GridProps {
  readonly table: PageTable;
  readonly resolve: (href: string) => string;
  readonly hrefOf: (action: PageAction) => string;
  readonly selectable: boolean;
}

function Grid({ table, resolve, hrefOf, selectable }: GridProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const [hint, setHint] = useState(false);
  const [openRow, setOpenRow] = useState<number | null>(null);
  const opens = table.rows.some((row) => row.details.length > 0 || row.detailsHref !== '');
  const ticks = selectable && table.rows.some((row) => row.pickId);
  useEffect(() => {
    const node = scroller.current;
    if (!node || hintSeen || node.scrollWidth <= node.clientWidth + 2) return undefined;
    hintSeen = true;
    setHint(true);
    const timer = window.setTimeout(() => setHint(false), 4300);
    return () => window.clearTimeout(timer);
  }, []);
  const columnCount = table.columns.length + (opens ? 1 : 0) + (ticks ? 1 : 0);
  return (
    // A region a keyboard can reach and scroll (WCAG: scrollable-region-focusable).
    <div data-ph="scroller" ref={scroller} onScroll={() => setHint(false)} tabIndex={0} role="region" aria-label={`${table.title || 'Table'}, scrolls sideways`}>
      {hint ? (
        <span data-ph="hint" aria-hidden="true">
          Swipe to view more columns
        </span>
      ) : null}
      <table data-ph="grid">
        {table.columns.length > 0 ? (
          <thead>
            <tr>
              {ticks ? (
                <th scope="col">
                  <input
                    type="checkbox"
                    aria-label="Select all on this page"
                    onChange={(event) => {
                      const on = event.currentTarget.checked;
                      event.currentTarget.closest('table')?.querySelectorAll<HTMLInputElement>('input[data-pick]').forEach((box) => {
                        box.checked = on;
                        box.dispatchEvent(new Event('change', { bubbles: true }));
                      });
                    }}
                  />
                </th>
              ) : null}
              {opens ? <th scope="col" aria-label="Details" /> : null}
              {table.columns.map((column, index) => (
                <th key={`${column.label}-${index}`} scope="col" data-numeric={column.numeric || undefined}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
        ) : null}
        <tbody>
          {table.rows.map((row, rowIndex) => {
            const canOpen = row.details.length > 0 || row.detailsHref !== '';
            const isOpen = openRow === rowIndex;
            const name = rowName(row);
            const detailsId = `ph-row-${rowIndex}`;
            return (
              <Fragment key={rowIndex}>
                <tr data-row-tone={row.tone || undefined} data-open={isOpen || undefined}>
                  {ticks ? (
                    <td>{row.pickId ? <input type="checkbox" data-pick={row.pickId} aria-label={row.pickLabel || `Select ${name}`} /> : null}</td>
                  ) : null}
                  {opens ? (
                    <td data-ph-cell="expander">
                      {canOpen ? (
                        <button
                          type="button"
                          data-ph="expander"
                          aria-expanded={isOpen}
                          aria-controls={detailsId}
                          aria-label={`${isOpen ? 'Hide' : 'Show'} the details of ${name}`}
                          onClick={() => setOpenRow(isOpen ? null : rowIndex)}
                        >
                          {isOpen ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
                        </button>
                      ) : null}
                    </td>
                  ) : null}
                  {row.cells.map((cell, index) => {
                    if (isActionsCell(cell)) {
                      return (
                        <td key={index}>
                          <CellActions actions={cell.actions} subject={name} hrefOf={hrefOf} />
                        </td>
                      );
                    }
                    const tone = phoneTone(cell.tone);
                    const text = <span data-ph="cell-text">{cell.text}</span>;
                    return (
                      <td
                        key={index}
                        data-strong={cell.strong || undefined}
                        data-ph-tone={tone && tone !== 'brand' ? tone : undefined}
                        data-numeric={table.columns[index]?.numeric || undefined}
                      >
                        {cell.href ? <a href={resolve(cell.href)}>{text}</a> : text}
                      </td>
                    );
                  })}
                </tr>
                {isOpen ? (
                  <tr data-ph="details" id={detailsId}>
                    <td colSpan={columnCount}>
                      {row.detailsHref ? (
                        <a data-ph="details-link" href={resolve(row.detailsHref)}>
                          Open {name} profile
                        </a>
                      ) : null}
                      <div data-ph="details-facts">
                        {row.details.map((fact) => (
                          <span key={fact.label} data-ph="details-fact" data-ph-tone={phoneTone(fact.tone)}>
                            {fact.label}: {fact.href ? <a href={resolve(fact.href)}><b>{fact.value}</b></a> : <b>{fact.value}</b>}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
