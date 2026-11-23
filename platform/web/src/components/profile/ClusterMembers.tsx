'use client';

/*
 * The cluster's member schools: Go's roster, narrowed and ordered in the
 * browser, opened row by row into each school's scores, and exported as the
 * reader sees it. The ticks, row actions and opened row are the shared table's.
 */
import { Download, Search } from 'lucide-react';
import { useMemo, useState } from 'react';

import { CONTROL } from '@/components/drawer/drawerParts';
import { FeedTable } from '@/components/page/FeedTable';
import type { PageTable } from '@/gen/edify/screens/v1/page_pb';
import { memberTypes, membersCsv, shownMembers } from '@/lib/clusterProfileView';

interface ClusterMembersProps {
  readonly table: PageTable;
  readonly pagePath: string;
  readonly drawerHref: string;
  readonly selectable: boolean;
}

export function ClusterMembers({ table, pagePath, drawerHref, selectable }: ClusterMembersProps) {
  const [search, setSearch] = useState('');
  const [type, setType] = useState('');
  const [ssa, setSsa] = useState('');
  const [sort, setSort] = useState('name');
  const types = useMemo(() => memberTypes(table.rows, table.columns), [table]);
  const rows = useMemo(() => shownMembers(table.rows, table.columns, { search, type, ssa, sort }), [table, search, type, ssa, sort]);

  const exportRows = () => {
    const url = URL.createObjectURL(new Blob([membersCsv(table.columns, rows)], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'cluster-member-schools.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  const select = `${CONTROL} sm:w-auto`;
  return (
    <div className="space-y-2" data-block="cluster-members">
      <div data-pf="member-tools">
        <label className="relative block">
          <span className="sr-only">Search schools by name or ID</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--edify-text-muted)]" aria-hidden="true" />
          <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search schools…" className={`${CONTROL} pl-9`} />
        </label>
        <select aria-label="Filter by school type" className={select} value={type} onChange={(event) => setType(event.target.value)}>
          <option value="">All types</option>
          {types.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        <select aria-label="Filter by SSA" className={select} value={ssa} onChange={(event) => setSsa(event.target.value)}>
          <option value="">All SSA</option>
          <option value="assessed">Assessed</option>
          <option value="not">Not assessed</option>
        </select>
        <select aria-label="Sort schools" className={select} value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="name">Sort: Name</option>
          <option value="ssa-low">Sort: SSA, lowest first</option>
          <option value="ssa-high">Sort: SSA, highest first</option>
          <option value="visit">Sort: Longest since visit</option>
        </select>
        <button type="button" onClick={exportRows} disabled={!rows.length} className="edify-action-button secondary h-10 px-3 disabled:opacity-50">
          <Download className="h-4 w-4" aria-hidden="true" /> Export
        </button>
      </div>
      <FeedTable table={{ ...table, rows }} pagePath={pagePath} drawerHref={drawerHref} selectable={selectable} />
    </div>
  );
}
