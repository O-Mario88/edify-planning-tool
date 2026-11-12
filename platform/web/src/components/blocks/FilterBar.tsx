'use client';

/*
 * One row of labelled selects with a square clear button at its end
 * (owner's rules: filters one row + ×). A GET form: choosing a value reloads
 * the page with it, and the page starts again at page one.
 */
import { useRef, useState } from 'react';

import { Icon } from '../shell/icons';

export interface FilterOption {
  readonly value: string;
  readonly label: string;
}
export interface Filter {
  readonly name: string;
  readonly label: string;
  readonly value: string;
  readonly options: readonly FilterOption[];
  readonly disabled?: boolean;
}

/** On a phone the row keeps its first three filters; the rest sit behind More. */
const PHONE_FILTERS = 3;

export function FilterBar({
  action,
  filters,
  hidden,
  clearHref,
  label = 'Filters',
}: {
  action: string;
  filters: readonly Filter[];
  hidden: Readonly<Record<string, string>>;
  clearHref: string;
  label?: string;
}) {
  const form = useRef<HTMLFormElement>(null);
  const [more, setMore] = useState(false);
  const folded = filters.length > PHONE_FILTERS;
  return (
    <form ref={form} method="get" action={action} aria-label={label} data-block="filters" className="grid grid-cols-[repeat(4,minmax(0,1fr))_auto] items-end gap-2 sm:gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))]">
      {Object.entries(hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      {filters.map((filter, index) => (
        <label key={filter.name} className={`block min-w-0 ${index >= PHONE_FILTERS && !more ? 'max-sm:hidden' : ''}`}>
          <span className="mb-1 block truncate text-[length:var(--edify-text-micro-size)] font-medium text-[var(--edify-text-muted)]">{filter.label}</span>
          <select
            name={filter.name}
            aria-label={filter.label}
            defaultValue={filter.value}
            disabled={filter.disabled}
            onChange={() => form.current?.requestSubmit()}
            className="edify-select h-8 w-full truncate rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-[22px] text-center text-[14px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none disabled:bg-[var(--edify-surface-muted)] disabled:text-[var(--edify-text-subtle)]"
          >
            {filter.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      ))}
      {folded ? (
        <button
          type="button"
          aria-expanded={more}
          onClick={() => setMore(!more)}
          className="inline-flex h-8 items-center justify-center gap-1 rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[14px] font-semibold sm:hidden"
        >
          {more ? 'Fewer' : 'More'}
          <Icon name="chevronDown" className={`h-4 w-4 ${more ? 'rotate-180' : ''}`} />
        </button>
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
