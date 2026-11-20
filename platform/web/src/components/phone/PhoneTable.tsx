'use client';

/*
 * A record table as the app draws it (PageTableView.tsx): a card with its
 * title bar, the table itself, a note under it, or the empty state in place
 * of its rows. On every screen the table is a spreadsheet that scrolls
 * sideways in its own region (owner, 2026-11-20: "i like the spreadsheet
 * list format better on all screen", which reversed 2026-11-19's row cards).
 * ROWS_ON_PHONES brings back the row cards and, from 16 rows, the compact
 * list with its sheet (lib/rowCard). A table wider than the screen shows the
 * slim orange "Swipe to view more columns" pill once, which leaves after
 * about four seconds (owner, 2026-10-02). A row with details opens under
 * itself, one at a time; ticked rows feed the page's bar (input[data-pick]).
 */
import { ChevronDown, ChevronRight, X } from 'lucide-react';
import { Fragment, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import type { PageAction, PageRow, PageTable } from '@/gen/edify/screens/v1/page_pb';
import { actionHref, isActionsCell, resolveHref } from '@/lib/feedPage';
import { asList, rowCard, summaryOf } from '@/lib/rowCard';
import type { RowCard, RowFact } from '@/lib/rowCard';

import { Explanation } from '../page/Explanation';
import { CellActions } from '../page/FeedTable';
import { PhoneEmpty, PhonePager } from './PhoneParts';
import { phoneTone } from './tone';

/** The hint shows once per visit, as the app's does until a swipe. */
let hintSeen = false;

/** A phone's tables as row cards (owner, 2026-11-19), reversed for the spreadsheet on every screen (2026-11-20). */
const ROWS_ON_PHONES = false;

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
        ROWS_ON_PHONES ? (
          asList(table.rows.length) ? (
            <List table={table} resolve={resolve} hrefOf={hrefOf} selectable={selectable} />
          ) : (
            <Cards table={table} resolve={resolve} hrefOf={hrefOf} selectable={selectable} />
          )
        ) : (
          <Grid table={table} resolve={resolve} hrefOf={hrefOf} selectable={selectable} />
        )
      )}
      {table.pager ? <PhonePager pager={table.pager} resolve={resolve} /> : null}
      {footer}
      {table.footnote ? <Explanation text={table.footnote} phone /> : null}
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

/** A tick that sets every row's tick on the page (the bar counts them). */
function tickAll(event: { currentTarget: HTMLInputElement }) {
  const on = event.currentTarget.checked;
  event.currentTarget
    .closest('[data-ph="rows-wrap"]')
    ?.querySelectorAll<HTMLInputElement>('input[data-pick]')
    .forEach((box) => {
      box.checked = on;
      box.dispatchEvent(new Event('change', { bubbles: true }));
    });
}

function Cards({ table, resolve, hrefOf, selectable }: GridProps) {
  const [openRow, setOpenRow] = useState<number | null>(null);
  const ticks = selectable && table.rows.some((row) => row.pickId);
  return (
    <div data-ph="rows-wrap">
      {ticks ? (
        <label data-ph="rows-all">
          <input type="checkbox" aria-label="Select all on this page" onChange={tickAll} />
          Select all on this page
        </label>
      ) : null}
      <ul data-ph="rows" aria-label={table.title || 'Rows'}>
        {table.rows.map((row, rowIndex) => {
          const card = rowCard(table.columns, row);
          const name = rowName(row);
          const isOpen = openRow === rowIndex;
          const more = card.rest.length > 0 || row.details.length > 0 || row.detailsHref !== '';
          const detailsId = `ph-card-${rowIndex}`;
          const statusTone = card.status ? phoneTone(card.status.tone) : undefined;
          return (
            <li key={rowIndex} data-ph="row" data-row-tone={row.tone || undefined}>
              <div data-ph="row-head">
                {ticks && row.pickId ? <input type="checkbox" data-pick={row.pickId} aria-label={row.pickLabel || `Select ${name}`} /> : null}
                <div data-ph="row-name-wrap">
                  {card.title?.href ? (
                    <a data-ph="row-name" href={resolve(card.title.href)}>
                      {card.title.text}
                    </a>
                  ) : (
                    <span data-ph="row-name">{card.title?.text ?? name}</span>
                  )}
                  {card.id ? (
                    <span data-ph="row-id">
                      {card.id.label} {card.id.cell.text}
                    </span>
                  ) : null}
                </div>
                {card.status ? (
                  <span data-ph="row-status" data-ph-tone={statusTone && statusTone !== 'brand' ? statusTone : undefined}>
                    {card.status.text}
                  </span>
                ) : null}
              </div>
              {card.lead.length ? (
                <dl data-ph="row-facts">
                  {card.lead.map((fact, i) => (
                    <div key={`${fact.label}-${i}`} data-ph="row-fact">
                      <dt>{fact.label}</dt>
                      <dd data-ph-tone={phoneTone(fact.cell.tone) || undefined}>
                        {fact.cell.href ? <a href={resolve(fact.cell.href)}>{fact.cell.text}</a> : fact.cell.text}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              {more || card.actions ? (
                <div data-ph="row-foot">
                  {more ? (
                    <button
                      type="button"
                      data-ph="row-more"
                      aria-expanded={isOpen}
                      aria-controls={detailsId}
                      onClick={() => setOpenRow(isOpen ? null : rowIndex)}
                    >
                      {isOpen ? 'Hide details' : 'All details'}
                      {isOpen ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
                    </button>
                  ) : (
                    <span />
                  )}
                  {card.actions ? <CellActions actions={card.actions.actions} subject={name} hrefOf={hrefOf} /> : null}
                </div>
              ) : null}
              {isOpen ? (
                <div data-ph="row-details" id={detailsId}>
                  {card.rest.length ? (
                    <dl data-ph="row-facts">
                      {card.rest.map((fact, i) => (
                        <div key={`${fact.label}-${i}`} data-ph="row-fact">
                          <dt>{fact.label}</dt>
                          <dd data-ph-tone={phoneTone(fact.cell.tone) || undefined}>
                            {fact.cell.href ? <a href={resolve(fact.cell.href)}>{fact.cell.text}</a> : fact.cell.text}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                  {row.details.length ? (
                    <div data-ph="details-facts">
                      {row.details.map((fact) => (
                        <span key={fact.label} data-ph="details-fact" data-ph-tone={phoneTone(fact.tone)}>
                          {fact.label}: {fact.href ? <a href={resolve(fact.href)}><b>{fact.value}</b></a> : <b>{fact.value}</b>}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {row.detailsHref ? (
                    <a data-ph="details-link" href={resolve(row.detailsHref)}>
                      Open {name} profile
                    </a>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Facts({ facts, resolve }: { facts: readonly RowFact[]; resolve: (href: string) => string }) {
  return (
    <dl data-ph="row-facts">
      {facts.map((fact, i) => (
        <div key={`${fact.label}-${i}`} data-ph="row-fact">
          <dt>{fact.label}</dt>
          <dd data-ph-tone={phoneTone(fact.cell.tone) || undefined}>
            {fact.cell.href ? <a href={resolve(fact.cell.href)}>{fact.cell.text}</a> : fact.cell.text}
          </dd>
        </div>
      ))}
    </dl>
  );
}

interface SheetProps {
  readonly card: RowCard;
  readonly row: PageRow;
  readonly resolve: (href: string) => string;
  readonly hrefOf: (action: PageAction) => string;
  readonly onClose: () => void;
}

/** A row's whole card, in the sheet a compact list opens. */
function SheetBody({ card, row, resolve, hrefOf, onClose }: SheetProps) {
  const name = rowName(row);
  const statusTone = card.status ? phoneTone(card.status.tone) : undefined;
  return (
    <>
      <div data-ph="sheet-head">
        <div data-ph="row-name-wrap">
          {card.title?.href ? (
            <a data-ph="row-name" href={resolve(card.title.href)}>
              {card.title.text}
            </a>
          ) : (
            <span data-ph="row-name">{card.title?.text ?? name}</span>
          )}
          {card.id ? (
            <span data-ph="row-id">
              {card.id.label} {card.id.cell.text}
            </span>
          ) : null}
        </div>
        {card.status ? (
          <span data-ph="row-status" data-ph-tone={statusTone && statusTone !== 'brand' ? statusTone : undefined}>
            {card.status.text}
          </span>
        ) : null}
        <button type="button" data-ph="sheet-close" aria-label="Close" onClick={onClose}>
          <X size={18} aria-hidden="true" />
        </button>
      </div>
      {card.lead.length + card.rest.length > 0 ? <Facts facts={[...card.lead, ...card.rest]} resolve={resolve} /> : null}
      {row.details.length ? (
        <div data-ph="details-facts">
          {row.details.map((fact) => (
            <span key={fact.label} data-ph="details-fact" data-ph-tone={phoneTone(fact.tone)}>
              {fact.label}: {fact.href ? <a href={resolve(fact.href)}><b>{fact.value}</b></a> : <b>{fact.value}</b>}
            </span>
          ))}
        </div>
      ) : null}
      {row.detailsHref || card.actions ? (
        <div data-ph="row-foot">
          {row.detailsHref ? (
            <a data-ph="details-link" href={resolve(row.detailsHref)}>
              Open {name} profile
            </a>
          ) : (
            <span />
          )}
          {card.actions ? <CellActions actions={card.actions.actions} subject={name} hrefOf={hrefOf} /> : null}
        </div>
      ) : null}
    </>
  );
}

/** A long table (a directory): one line a row, its card in a sheet. The sheet
 *  is a modal dialog, in the top layer above the phone layout's containers. */
function List({ table, resolve, hrefOf, selectable }: GridProps) {
  const [open, setOpen] = useState<number | null>(null);
  const sheet = useRef<HTMLDialogElement>(null);
  const ticks = selectable && table.rows.some((row) => row.pickId);
  useEffect(() => {
    const dialog = sheet.current;
    if (!dialog) return;
    if (open !== null && !dialog.open) dialog.showModal();
    if (open === null && dialog.open) dialog.close();
  }, [open]);
  const openRow = open !== null ? table.rows[open] : undefined;
  return (
    <div data-ph="rows-wrap">
      {ticks ? (
        <label data-ph="rows-all">
          <input type="checkbox" aria-label="Select all on this page" onChange={tickAll} />
          Select all on this page
        </label>
      ) : null}
      <ul data-ph="list-rows" aria-label={table.title || 'Rows'}>
        {table.rows.map((row, rowIndex) => {
          const card = rowCard(table.columns, row);
          const name = rowName(row);
          const line = [card.id ? `${card.id.label} ${card.id.cell.text}` : '', summaryOf(card)].filter((s) => s !== '').join(' · ');
          return (
            <li key={rowIndex} data-ph="list-row" data-row-tone={row.tone || undefined}>
              {ticks && row.pickId ? <input type="checkbox" data-pick={row.pickId} aria-label={row.pickLabel || `Select ${name}`} /> : null}
              <button type="button" data-ph="list-open" aria-haspopup="dialog" onClick={() => setOpen(rowIndex)}>
                <span data-ph="list-title">{card.title?.text ?? name}</span>
                {line ? <span data-ph="list-line">{line}</span> : null}
              </button>
              <ChevronRight size={16} aria-hidden="true" data-ph="list-chevron" />
            </li>
          );
        })}
      </ul>
      <dialog ref={sheet} data-ph="sheet" aria-label={openRow ? rowName(openRow) : 'Details'} onClose={() => setOpen(null)}>
        {openRow ? (
          <SheetBody card={rowCard(table.columns, openRow)} row={openRow} resolve={resolve} hrefOf={hrefOf} onClose={() => setOpen(null)} />
        ) : null}
      </dialog>
    </div>
  );
}

