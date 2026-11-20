'use client';

/*
 * A page's filters as the app draws them (PageFilterBar.tsx): as many
 * selects as a phone's row holds (three; two on a narrow phone, so a value
 * such as "Last 30 Days" is never cut), the rest under More as a panel of
 * labelled selects. It is the page's GET form: a change sends every filter
 * and the form's hidden values, as the existing web's filter form does.
 */
import { useLayoutEffect, useRef, useState } from 'react';

import type { PageFilter, PageFilters } from '@/gen/edify/screens/v1/page_pb';

import { selectName } from '../blocks/FilterBar';
import { MorePanel } from './MorePanel';

/** Selects a phone's filter row holds before the rest go under More. */
const IN_ROW = 3;
/** On a row narrower than this a third select would cut its value. */
const NARROW_ROW_PX = 480;

/** How many selects the row holds at its width, measured before paint and
 *  again when the row's width changes. */
export function inRowFor(width: number): number {
  return width > 0 && width < NARROW_ROW_PX ? IN_ROW - 1 : IN_ROW;
}

function FilterSelect({ filter, onChange }: { filter: PageFilter; onChange: () => void }) {
  return (
    <select data-ph="select" name={filter.name} defaultValue={filter.value} aria-label={selectName(filter)} onChange={onChange}>
      {filter.options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function PhoneFilters({ filters, action }: { filters: PageFilters; action: string }) {
  const form = useRef<HTMLFormElement>(null);
  const [inRow, setInRow] = useState(IN_ROW);
  useLayoutEffect(() => {
    const el = form.current;
    if (!el) return undefined;
    setInRow(inRowFor(el.clientWidth));
    if (typeof ResizeObserver === 'undefined') return undefined;
    const watch = new ResizeObserver(() => setInRow(inRowFor(el.clientWidth)));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  const send = () => form.current?.requestSubmit();
  const shown = filters.filters.slice(0, inRow);
  const rest = filters.filters.slice(inRow);
  const restSet = rest.filter((filter) => filter.value !== (filter.options[0]?.value ?? '')).length;
  return (
    <form ref={form} data-ph="filters" data-roomy={rest.length === 0 || undefined} method="get" action={action} aria-label="Filters">
      {Object.entries(filters.hidden).map(([name, value]) => (
        <input key={name} type="hidden" name={name} value={value} />
      ))}
      {shown.map((filter) => (
        <label key={filter.name} data-ph="filter">
          <span data-ph="filter-label">{filter.label}</span>
          <FilterSelect filter={filter} onChange={send} />
        </label>
      ))}
      {rest.length > 0 ? (
        <MorePanel look="more-button" roomy label={`More${restSet ? ` ${restSet}` : ''} filters${restSet ? `, ${restSet} set` : ''}`} words={`More${restSet ? ` ${restSet}` : ''}`}>
          {rest.map((filter) => (
            <label key={filter.name} data-ph="more-field">
              <span data-ph="filter-label">{filter.label}</span>
              <FilterSelect filter={filter} onChange={send} />
            </label>
          ))}
        </MorePanel>
      ) : null}
    </form>
  );
}
