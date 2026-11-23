'use client';

/*
 * The year and period, set small inside a card as the designs draw them. The
 * native select lies invisibly over the small label, so it keeps the 16px text
 * that stops a phone zooming in. A change reloads the page's own address.
 */
import { ChevronDown } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import type { PageFilter } from '@/gen/edify/screens/v1/page_pb';

export function CardFilters({ filters }: { filters: readonly PageFilter[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const change = (name: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(name, value);
    else next.delete(name);
    router.push(`${pathname}?${next.toString()}`);
  };
  return (
    <span data-pf="card-filters">
      {filters.map((filter) => {
        const shown = filter.options.find((option) => option.value === filter.value)?.label ?? filter.options[0]?.label ?? '';
        return (
          <span key={filter.name} data-pf="card-select">
            <span aria-hidden="true">{shown}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <select aria-label={filter.label} value={filter.value} onChange={(event) => change(filter.name, event.target.value)}>
              {filter.options.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </span>
        );
      })}
    </span>
  );
}
