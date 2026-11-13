'use client';

/*
 * The pager's rows-a-page chooser ("15 / page"): choosing reopens the list at
 * its first page with that many rows, the page's other choices kept.
 */
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import type { PageFilter } from '@/gen/edify/screens/v1/page_pb';
import { withPageSize } from '@/lib/pager';

export function PageSize({ size }: { size: PageFilter }) {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  return (
    <select
      name={size.name}
      aria-label={size.label}
      defaultValue={size.value}
      onChange={(event) => router.push(`${path}${withPageSize(params.toString(), size.name, event.target.value)}`)}
      className="edify-select h-8 rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-2 pr-6 text-[13px] font-bold text-[var(--edify-text)]"
    >
      {size.options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
