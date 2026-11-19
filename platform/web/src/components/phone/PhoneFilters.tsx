'use client';

/*
 * A page's filters as the app draws them (PageFilterBar.tsx): as many
 * selects as a phone's row holds (three), the rest under More as a panel of
 * labelled selects. It is the page's GET form: a change sends every filter
 * and the form's hidden values, as the existing web's filter form does.
 */
import { useRef } from 'react';

import type { PageFilter, PageFilters } from '@/gen/edify/screens/v1/page_pb';

import { MorePanel } from './MorePanel';

/** Selects a phone's filter row holds before the rest go under More. */
const IN_ROW = 3;

function FilterSelect({ filter, onChange }: { filter: PageFilter; onChange: () => void }) {
  return (
    <select data-ph="select" name={filter.name} defaultValue={filter.value} aria-label={filter.label} onChange={onChange}>
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
  const send = () => form.current?.requestSubmit();
  const shown = filters.filters.slice(0, IN_ROW);
  const rest = filters.filters.slice(IN_ROW);
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
        <MorePanel look="more-button" roomy label={`More filters${restSet ? `, ${restSet} set` : ''}`} words={`More${restSet ? ` ${restSet}` : ''}`}>
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
