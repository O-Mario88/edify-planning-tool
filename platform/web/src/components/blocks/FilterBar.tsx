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
import { filterFields, filterSlots, UNMEASURED_SLOTS } from '@/lib/filterSlots';

import { Icon } from '../shell/icons';

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
}

/** Below 48rem the existing web lays the row out as a phone's. */
const PHONE_QUERY = '(max-width: 47.999rem)';

/** A tucked filter counts on More when it narrows: not "all", and "all" is one of its choices (micro-ux.js filterMoreCount). */
function applied(filter: Filter): boolean {
  const all = (value: string) => !value || value.toLowerCase() === 'all';
  return !filter.disabled && !all(filter.value.trim()) && filter.options.some((option) => all(option.value));
}

function Field({ filter, onChange }: { filter: Filter; onChange: () => void }) {
  return (
    <label className="block min-w-0">
      <span className="mb-1 block truncate text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]" aria-hidden={filter.caption ? true : undefined}>
        {filter.caption || filter.label}
      </span>
      <select
        name={filter.name}
        aria-label={filter.label}
        defaultValue={filter.value}
        disabled={filter.disabled}
        onChange={onChange}
        className="edify-select h-8 w-full truncate rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-[22px] text-center text-[14px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none disabled:bg-[var(--edify-surface-muted)] disabled:text-[var(--edify-text-subtle)]"
      >
        {filter.options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
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
  clearHref: string;
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
  const fields = oneRow || layout.phone ? filterFields(shown.length, layout.slots, layout.phone) : shown.length;
  const inRow = shown.slice(0, fields);
  const folded = shown.slice(fields);
  const foldedApplied = folded.filter(applied).length;
  const columns = inRow.length + (folded.length ? 1 : 0);
  return (
    <form
      ref={form}
      method="get"
      action={action}
      aria-label={label}
      data-block="filters"
      style={oneRow || layout.phone ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr)) auto` } : undefined}
      className={`grid items-end gap-2 sm:gap-3 ${oneRow ? '' : 'grid-cols-[repeat(4,minmax(0,1fr))_auto] sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))]'}`}
    >
      {Object.entries(hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      {quiet.map((filter) => (
        <input key={filter.name} type="hidden" name={filter.name} value={filter.value} />
      ))}
      {inRow.map((filter) => (
        <Field key={filter.name} filter={filter} onChange={submit} />
      ))}
      {folded.length ? (
        <div className="relative min-w-0" data-filter-more>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="inline-flex h-8 w-full items-center justify-center gap-1 rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[14px] font-semibold text-[var(--edify-text)]"
          >
            <span>
              More<span className="max-sm:hidden"> filters</span>
            </span>
            {foldedApplied ? <span className="rounded-full bg-[var(--brand-primary)] px-1.5 text-[11px] font-bold text-white">{foldedApplied}</span> : null}
            <Icon name="chevronDown" className={`h-4 w-4 ${open ? 'rotate-180' : ''}`} />
          </button>
          <div
            role="group"
            aria-label="More filters"
            hidden={!open}
            className="absolute right-0 top-full z-30 mt-1 w-64 max-w-[calc(100vw-2rem)] space-y-3 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-3 shadow-[var(--edify-shadow-md)]"
          >
            {folded.map((filter) => (
              <Field key={filter.name} filter={filter} onChange={submit} />
            ))}
          </div>
        </div>
      ) : null}
      <a
        href={clearHref}
        aria-label="Clear Filters"
        title="Clear Filters"
        className="grid h-8 w-8 place-items-center rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] text-[var(--edify-text)] hover:bg-[var(--brand-primary-soft)]"
      >
        <Icon name="close" className="h-4 w-4" />
      </a>
      <noscript>
        <button type="submit">Apply</button>
      </noscript>
    </form>
  );
}
