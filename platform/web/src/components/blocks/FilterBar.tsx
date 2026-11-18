'use client';

/*
 * One row of labelled selects with a square clear button at its end
 * (owner's rules: filters one row + ×). A GET form: choosing a value reloads
 * the page with it, and the page starts again at page one. When the filters
 * do not fit the row, the last ones fold under "More filters", which opens
 * below its button (static/js/micro-ux.js: three a phone, one 144px slot each
 * wider).
 */
import { useEffect, useRef, useState } from 'react';

import { isEmptyFilter } from '@/lib/emptyFilter';
import { arrangesRow, filterSlots, foldFilters, UNMEASURED_SLOTS } from '@/lib/filterSlots';


export interface FilterOption {
  readonly value: string;
  readonly label: string;
}
export interface Filter {
  readonly name: string;
  readonly label: string;
  /** The short word drawn over the select ("FY"); the label stays its name for a screen reader. */
  readonly caption?: string;
  readonly value: string;
  readonly options: readonly FilterOption[];
  readonly disabled?: boolean;
  /** The page folds it under its own More filters whatever the width (PageFilter.more). */
  readonly more?: boolean;
}

/** Below 48rem the existing web lays the row out as a phone's. */
const PHONE_QUERY = '(max-width: 47.999rem)';

/** A tucked filter counts on More when it narrows: not "all", and "all" is one of its choices (micro-ux.js filterMoreCount). */
function applied(filter: Filter): boolean {
  const all = (value: string) => !value || value.toLowerCase() === 'all';
  return !filter.disabled && !all(filter.value.trim()) && filter.options.some((option) => all(option.value));
}

/** A field as the existing filter row draws it (micro-ux.js arrangeFilterRows). */
function Field({ filter, onChange, inRow = true }: { filter: Filter; onChange: () => void; inRow?: boolean }) {
  return (
    <div className={`platform-filter-compact flex flex-col edify-filter-field ${inRow ? 'edify-filter-row__field' : ''}`}>
      <span className="edify-filter-label" aria-hidden={filter.caption ? true : undefined}>
        {filter.caption || filter.label}
      </span>
      <select
        name={filter.name}
        aria-label={filter.label}
        defaultValue={filter.value}
        disabled={filter.disabled}
        onChange={onChange}
        className="h-9 px-3 text-[12px] font-semibold bg-slate-50 border border-slate-200 rounded-control edify-focus-surface focus:outline-none transition-all disabled:text-slate-400"
      >
        {filter.options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function FilterBar({
  action,
  filters,
  hidden,
  clearHref,
  label = 'Filters',
  oneRow = false,
}: {
  action: string;
  filters: readonly Filter[];
  hidden: Readonly<Record<string, string>>;
  /** Where the row's × leads; a page without a Clear (the school profile) has no ×. */
  clearHref?: string;
  label?: string;
  /** On a wide screen every filter shares one row with the × (owner, 2026-09-27). */
  oneRow?: boolean;
}) {
  const form = useRef<HTMLFormElement>(null);
  const [open, setOpen] = useState(false);
  const [layout, setLayout] = useState({ slots: UNMEASURED_SLOTS, phone: false });
  const shown = filters.filter((filter) => !isEmptyFilter(filter));
  const quiet = filters.filter((filter) => isEmptyFilter(filter) && filter.value && !filter.disabled);
  useEffect(() => {
    const node = form.current;
    if (!node) return undefined;
    const phoneQuery = window.matchMedia(PHONE_QUERY);
    const measure = () => {
      const phone = phoneQuery.matches;
      setLayout({ slots: filterSlots(node.getBoundingClientRect().width, phone), phone });
    };
    measure();
    const resize = new ResizeObserver(measure);
    resize.observe(node);
    phoneQuery.addEventListener('change', measure);
    return () => {
      resize.disconnect();
      phoneQuery.removeEventListener('change', measure);
    };
  }, []);
  useEffect(() => {
    if (!open) return undefined;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !form.current?.querySelector('[data-filter-more]')?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', close);
    };
  }, [open]);
  const submit = () => form.current?.requestSubmit();
  // A page that keeps its own grid (the School Directory) folds only on a phone.
  const { inRow, folded } = foldFilters(shown, layout.slots, layout.phone, Boolean(oneRow || layout.phone));
  const foldedApplied = folded.filter(applied).length;
  const columns = inRow.length + (folded.length ? 1 : 0);
  // Too few fields to share the row: each keeps its own width, as the existing page leaves them.
  const ownWidth = !arrangesRow(shown.length, layout.phone);
  const shared = (oneRow || layout.phone) && !ownWidth;
  // The existing filter row's DOM (micro-ux.js arrangeFilterRows), drawn by its stylesheets.
  const arranged = !ownWidth;
  return (
    <form
      ref={form}
      method="get"
      action={action}
      aria-label={label}
      data-block="filters"
      data-component="filter-toolbar"
      className={`edify-filter-bar flex flex-wrap items-end gap-2.5 ${arranged ? 'edify-filter-row' : ''}`}
      data-edify-filter-row={arranged ? '' : undefined}
      data-edify-filter-slots={arranged && layout.slots ? layout.slots : undefined}
      style={arranged ? ({ '--edify-filter-cols': String(shared ? columns - (folded.length ? 1 : 0) : inRow.length) } as React.CSSProperties) : undefined}
    >
      {Object.entries(hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      {quiet.map((filter) => (
        <input key={filter.name} type="hidden" name={filter.name} value={filter.value} />
      ))}
      {inRow.map((filter) => (
        <Field key={filter.name} filter={filter} onChange={submit} inRow={arranged} />
      ))}
      {folded.length ? (
        <div className={`edify-filter-more edify-filter-row__field ${open ? 'is-open' : ''}`} data-edify-filter-more="" data-filter-more>
          <button type="button" className="edify-filter-more__toggle" aria-expanded={open} aria-controls="edify-filter-more-panel" onClick={() => setOpen(!open)}>
            <span>
              More<span className="edify-filter-more__long"> filters</span>
            </span>
            <span className="edify-filter-more__count" hidden={!foldedApplied}>
              {foldedApplied || ''}
            </span>
            <svg className="edify-filter-more__chevron" aria-hidden="true" viewBox="0 0 24 24">
              <path d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          <div className="edify-filter-more__panel" id="edify-filter-more-panel" role="group" aria-label="More filters" data-edify-filter-more-panel="" hidden={!open}>
            {folded.map((filter) => (
              <Field key={filter.name} filter={filter} onChange={submit} inRow={false} />
            ))}
          </div>
        </div>
      ) : null}
      {clearHref ? (
        <a href={clearHref} data-edify-filter-clear="" aria-label="Clear filters" title="Clear filters">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.25} strokeLinecap="round">
            <path d="M6 18L18 6M6 6l12 12" />
          </svg>
        </a>
      ) : null}
      <noscript>
        <button type="submit" className="btn btn-primary h-9">
          Apply
        </button>
      </noscript>
    </form>
  );
}
