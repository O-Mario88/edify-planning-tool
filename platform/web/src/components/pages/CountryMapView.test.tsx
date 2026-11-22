import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { buildCountryMapTabs, buildDashboardMapTabs } from '@/lib/countryMapData';
import type { CountryMapData, UgandaDistrictGeoJSON } from '@/lib/countryMapData';
import { CountryMapView } from './CountryMapView';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

const SAMPLE_DATA: CountryMapData = {
  fy: '2027',
  fy_options: ['2027', '2026'],
  scope_label: 'Country-wide system data',
  cceos: 20,
  district_count: 136,
  sub_region_count: 10,
  totals: {
    schools: 700,
    clients: 558,
    core: 103,
    champions: 39,
    core_trained: 14,
    core_graduates: 9,
  },
  sub_regions: [
    {
      name: 'Central',
      districts: 26,
      schools: 700,
      clients: 558,
      core: 103,
      champions: 39,
      core_trained: 14,
      core_graduates: 9,
      activities_planned: 240,
      activities_completed: 180,
      covered_schools: 210,
      coverage_pct: 30,
    },
    {
      name: 'Western',
      districts: 17,
      schools: 0,
      clients: 0,
      core: 0,
      champions: 0,
      core_trained: 0,
      core_graduates: 0,
      activities_planned: 0,
      activities_completed: 0,
      covered_schools: 0,
      coverage_pct: 0,
    },
  ],
  districts: [
    {
      id: 'd1',
      name: 'Mukono',
      sub_region: 'Central',
      schools: 700,
      clients: 558,
      core: 103,
      champions: 39,
      core_trained: 14,
      core_graduates: 9,
    },
  ],
  pins: [
    {
      id: 's1',
      school_id: 'SCH-001',
      name: 'Mukono Christian Primary',
      district: 'Mukono',
      sub_region: 'Central',
      school_type: 'core',
      lat: 0.3533,
      lng: 32.7553,
      href: '/schools/s1',
    },
  ],
};

const SAMPLE_GEO: UgandaDistrictGeoJSON = {
  type: 'FeatureCollection',
  features: [
    {
      properties: { d: 'Mukono', s: 'Central', r: 'Central', lat: 0.35, lon: 32.75 },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [32.6, 0.2],
            [32.9, 0.2],
            [32.9, 0.5],
            [32.6, 0.5],
            [32.6, 0.2],
          ],
        ],
      },
    },
  ],
};

describe('CountryMapView', () => {
  it('renders Program Lead Dashboard Map layout with KPIs, choropleth, legend, donut, top districts, sub-region table, and quick actions', () => {
    const html = renderToStaticMarkup(
      <CountryMapView
        data={SAMPLE_DATA}
        geo={SAMPLE_GEO}
        mode="dashboard"
        eyebrow="Dashboard"
        title="Program Lead Dashboard"
        description="Set direction, lead and coach your CCEOs."
        basePath="/dashboard"
        tabs={buildDashboardMapTabs('Program Lead', '2027')}
      />,
    );

    expect(html).toContain('Program Lead Dashboard');
    expect(html).toContain('20 CCEOs · 700 schools');
    expect(html).toContain('FY 2027');
    expect(html).toContain('This Week');
    expect(html).toContain('Priorities');
    expect(html).toContain('Collaboration');
    expect(html).toContain('Performance by Sub-Region');
    expect(html).toContain('UBOS boundaries');
    expect(html).toContain('Country-wide system data');
    expect(html).toContain('CENTRAL');
    expect(html).toContain('Map Layers');
    expect(html).toContain('Legend');
    expect(html).toContain('Distribution by Sub-Region');
    expect(html).toContain('Top 5 Districts (by Schools)');
    expect(html).toContain('Mukono');
    expect(html).toContain('Quick Actions');
    expect(html).toContain('View School Directory');
    expect(html).toContain('Compare Sub-Regions');
    expect(html).toContain('Export Map Data');
  });

  it('renders Country Map route with Oversight tabs', () => {
    const html = renderToStaticMarkup(
      <CountryMapView
        data={SAMPLE_DATA}
        geo={SAMPLE_GEO}
        mode="country-map"
        eyebrow="Country Oversight"
        title="Country Map"
        description="Country delivery map."
        basePath="/country-map"
        tabs={buildCountryMapTabs('2027')}
      />,
    );

    expect(html).toContain('Country Map');
    expect(html).toContain('Country Portfolio');
    expect(html).toContain('Schools &amp; Coverage');
    expect(html).toContain('Core Trained');
    expect(html).toContain('Core Graduates');
  });
});
