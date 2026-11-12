import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { SchoolDirectoryScreenService } from '@/gen/edify/screens/v1/school_directory_pb';
import { Card } from '@/components/blocks/Card';
import { FilterBar } from '@/components/blocks/FilterBar';
import { PageHeader } from '@/components/blocks/PageHeader';
import { Pager } from '@/components/blocks/Pager';
import { TabRail } from '@/components/blocks/TabRail';
import { DirectoryList } from '@/components/schools/DirectoryList';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isNotFound } from '@/lib/gateway';
import {
  DIRECTORY_PATH,
  directoryFilters,
  directoryHeader,
  directoryPager,
  directoryQuery,
  directoryRequest,
  directoryTabs,
  directoryTotal,
  disabledFilters,
  emptyMessage,
  schoolsListed,
} from '@/lib/schoolDirectory';

export const metadata: Metadata = { title: 'School Directory - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

/*
 * The School Directory, drawn from the gateway's answer, which Go reads
 * (SchoolDirectoryScreenService; docs/migration/12-school-directory.md).
 */
export default async function SchoolDirectoryPage({ searchParams }: { searchParams: Search }) {
  const query = directoryQuery(await searchParams);
  const answer = await asReader(async (token) => {
    try {
      return await gatewayClient(SchoolDirectoryScreenService, token).getSchoolDirectory(directoryRequest(query));
    } catch (error) {
      if (isNotFound(error)) notFound();
      throw error;
    }
  });
  const existingWebUrl = environment().existingWebUrl;
  const filters = directoryFilters(answer, query);
  const disabled = disabledFilters(filters);
  const tabs = directoryTabs(answer, query);
  const pager = directoryPager(answer, query);
  const exportQuery = new URLSearchParams({ ...(query as Record<string, string>), export: 'xlsx' }).toString();

  return (
    <div className="mx-auto max-w-[1500px] space-y-4 px-4 pb-5 pt-5 sm:px-6">
      <PageHeader
        header={directoryHeader(answer)}
        hrefOf={(action) => (action.key === 'export' ? `${existingWebUrl}${DIRECTORY_PATH}?${exportQuery}` : `${existingWebUrl}${DIRECTORY_PATH}`)}
      />
      <FilterBar
        action={DIRECTORY_PATH}
        label="Directory filters"
        clearHref={DIRECTORY_PATH}
        hidden={filters.hidden}
        filters={filters.filters.map((filter) => ({
          name: filter.name,
          label: filter.label,
          value: filter.value,
          options: filter.options.map(({ value, label }) => ({ value, label })),
          disabled: disabled.includes(filter.name),
        }))}
      />
      <Card flush label="Schools">
        <div className="border-b border-[var(--edify-border)] px-4 py-4">
          <TabRail rail={tabs} counts={tabs.counts} />
        </div>
        <DirectoryList
          schools={answer.schools}
          readOnly={answer.readOnly}
          mayOpenProfile={answer.mayOpenProfile}
          listed={schoolsListed(directoryTotal(answer))}
          emptyMessage={emptyMessage(answer, query)}
          existingWebUrl={existingWebUrl}
          fy={filters.filters[0]?.value ?? ''}
        />
        {pager ? <Pager pager={pager} /> : null}
      </Card>
    </div>
  );
}
