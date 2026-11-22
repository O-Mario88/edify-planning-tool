import type { Metadata } from 'next';

import { IdentityService } from '@/gen/edify/identity/v1/identity_pb';
import { FeedPage } from '@/components/page/FeedPage';
import { NotMovedYet } from '@/components/page/NotMovedYet';
import { CountryMapView } from '@/components/pages/CountryMapView';
import { asReader } from '@/lib/auth';
import { buildDashboardMapTabs, fetchCountryMapData, loadUgandaGeoJSON } from '@/lib/countryMapData';
import { environment } from '@/lib/environment';
import { drawerPageHref, pageQuery } from '@/lib/feedPage';
import { gatewayClient } from '@/lib/gateway';

export const metadata: Metadata = { title: 'Dashboard — Edify' };

type Search = Promise<Record<string, string | string[] | undefined>>;

function dashboardHeaderForRole(role: string): { title: string; description: string } {
  switch (role) {
    case 'Program Lead':
      return {
        title: 'Program Lead Dashboard',
        description:
          'Set direction, lead and coach your CCEOs, roll out training, SSA and spiritual transformation, and work with the Regional Lead, Country Director and training partners.',
      };
    case 'CCEO':
      return {
        title: 'CCEO Dashboard',
        description: 'Plan school visits, track cluster coverage, and monitor sub-region delivery across your districts.',
      };
    case 'CountryDirector':
      return {
        title: 'Country Director Dashboard',
        description: 'Monitor national school reach, sub-region performance, and delivery health across Uganda.',
      };
    case 'ImpactAssessment':
      return {
        title: 'Impact Assessment Dashboard',
        description: 'Inspect country-wide school cohorts, SSA coverage, and sub-region performance.',
      };
    default:
      return {
        title: 'Country Map Dashboard',
        description: 'Explore school reach, cohorts, and sub-region coverage across Uganda.',
      };
  }
}

export default async function DashboardPage({ searchParams }: { searchParams: Search }) {
  const query = pageQuery(await searchParams);

  // Preserve every existing Home / Dashboard view untouched; rebuild only the Map view.
  if ((query.view ?? '').trim().toLowerCase() !== 'map') {
    return <FeedPage path="/dashboard" alsoAs={['/dashboard/']} query={query} />;
  }

  const [session, data] = await Promise.all([
    asReader((token) => gatewayClient(IdentityService, token).getSession({})),
    fetchCountryMapData(query.fy),
  ]);

  const existingHref = drawerPageHref(environment().existingWebUrl, '/dashboard', query);
  if (!data) return <NotMovedYet href={existingHref} />;

  const role = session.session?.activeRole || 'Program Lead';
  const hdr = dashboardHeaderForRole(role);
  const geo = loadUgandaGeoJSON();

  return (
    <CountryMapView
      data={data}
      geo={geo}
      mode="dashboard"
      eyebrow="Dashboard"
      title={hdr.title}
      description={hdr.description}
      basePath="/dashboard"
      tabs={buildDashboardMapTabs(role, data.fy)}
    />
  );
}
