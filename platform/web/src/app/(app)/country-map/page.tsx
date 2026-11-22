import type { Metadata } from 'next';

import { askFirst } from '@/components/page/FeedPage';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { CountryMapView } from '@/components/pages/CountryMapView';
import { buildCountryMapTabs, fetchCountryMapData, loadUgandaGeoJSON } from '@/lib/countryMapData';
import { environment } from '@/lib/environment';
import { drawerPageHref, pageQuery } from '@/lib/feedPage';
import { requestView } from '@/lib/requestView';

export const metadata: Metadata = { title: 'Country Map — Edify' };

type Search = Promise<Record<string, string | string[] | undefined>>;

export default async function CountryMapPage({ searchParams }: { searchParams: Search }) {
  const query = pageQuery(await searchParams);
  const existingWebUrl = environment().existingWebUrl;
  const phone = (await requestView()) === 'phone';
  const existingHref = drawerPageHref(existingWebUrl, '/country-map/', query);

  // Enforce the canonical Go RBAC gate before rendering the interactive map.
  const answer = await askFirst(['/country-map/', '/country-map'], query, !phone);
  if (!answer) return <NotMovedYet href={existingHref} />;

  const data = await fetchCountryMapData(query.fy);
  if (!data) return <NotMovedYet href={existingHref} />;

  const geo = loadUgandaGeoJSON();
  return (
    <CountryMapView
      data={data}
      geo={geo}
      mode="country-map"
      eyebrow={answer.header?.eyebrow || 'Country Oversight'}
      title={answer.header?.title || 'Country Map'}
      description={
        answer.header?.description ||
        "Where the country's delivery, backlog and coverage sit across every UBOS sub-region and district."
      }
      basePath="/country-map"
      tabs={buildCountryMapTabs(data.fy)}
    />
  );
}
