import fs from 'node:fs';
import path from 'node:path';
import { redirect } from 'next/navigation';

import { accessToken, currentPath } from './auth';
import { environment } from './environment';

export interface MapSchoolTotals {
  readonly schools: number;
  readonly clients: number;
  readonly core: number;
  readonly champions: number;
  readonly core_trained: number;
  readonly core_graduates: number;
}

export interface MapSubRegionRow {
  readonly name: string;
  readonly districts: number;
  readonly schools: number;
  readonly clients: number;
  readonly core: number;
  readonly champions: number;
  readonly core_trained: number;
  readonly core_graduates: number;
  readonly activities_planned: number;
  readonly activities_completed: number;
  readonly covered_schools: number;
  readonly coverage_pct: number;
  readonly avg_ssa?: number;
}

export interface MapDistrictRow {
  readonly id: string;
  readonly name: string;
  readonly sub_region: string;
  readonly schools: number;
  readonly clients: number;
  readonly core: number;
  readonly champions: number;
  readonly core_trained: number;
  readonly core_graduates: number;
}

export interface MapSchoolPin {
  readonly id: string;
  readonly school_id: string;
  readonly name: string;
  readonly district: string;
  readonly sub_region: string;
  readonly school_type: string;
  readonly lat: number;
  readonly lng: number;
  readonly href: string;
}

export interface CountryMapData {
  readonly fy: string;
  readonly fy_options: readonly string[];
  readonly scope_label: string;
  readonly cceos: number;
  readonly district_count: number;
  readonly sub_region_count: number;
  readonly totals: MapSchoolTotals;
  readonly sub_regions: readonly MapSubRegionRow[];
  readonly districts: readonly MapDistrictRow[];
  readonly pins: readonly MapSchoolPin[];
}

export interface UgandaDistrictFeature {
  readonly properties: {
    readonly d: string;
    readonly s: string;
    readonly r: string;
    readonly lat: number;
    readonly lon: number;
  };
  readonly geometry: {
    readonly type: 'Polygon' | 'MultiPolygon';
    readonly coordinates: number[][][] | number[][][][];
  };
}

export interface UgandaDistrictGeoJSON {
  readonly type: 'FeatureCollection';
  readonly features: readonly UgandaDistrictFeature[];
}

export interface MapNavTab {
  readonly id: string;
  readonly label: string;
  readonly href: string;
  readonly active?: boolean;
  readonly icon: 'week' | 'map' | 'priorities' | 'team' | 'coaching' | 'programmes' | 'collaboration' | 'schools' | 'chart';
}

export function buildDashboardMapTabs(role: string, fy: string): readonly MapNavTab[] {
  const qs = fy ? `fy=${encodeURIComponent(fy)}&` : '';
  if (role === 'CCEO') {
    return [
      { id: 'week', label: 'This Week', href: `/dashboard?${qs}view=week`, icon: 'week' },
      { id: 'operations', label: 'Urgent schools', href: `/dashboard?${qs}view=operations`, icon: 'priorities' },
      { id: 'map', label: 'Map', href: `/dashboard?${qs}view=map`, active: true, icon: 'map' },
    ];
  }
  return [
    { id: 'week', label: 'This Week', href: `/dashboard?${qs}view=week`, icon: 'week' },
    { id: 'map', label: 'Map', href: `/dashboard?${qs}view=map`, active: true, icon: 'map' },
    { id: 'priorities', label: 'Priorities', href: `/dashboard?${qs}view=priorities`, icon: 'priorities' },
    { id: 'team', label: 'Team', href: `/dashboard?${qs}view=team`, icon: 'team' },
    { id: 'coaching', label: 'Coaching', href: `/dashboard?${qs}view=coaching`, icon: 'coaching' },
    { id: 'programmes', label: 'Programmes', href: `/dashboard?${qs}view=programmes`, icon: 'programmes' },
    { id: 'collaboration', label: 'Collaboration', href: `/dashboard?${qs}view=collaboration`, icon: 'collaboration' },
  ];
}

export function buildCountryMapTabs(fy: string): readonly MapNavTab[] {
  const qs = fy ? `?fy=${encodeURIComponent(fy)}` : '';
  return [
    { id: 'map', label: 'Map', href: `/country-map${qs}`, active: true, icon: 'map' },
    {
      id: 'portfolio',
      label: 'Country Portfolio',
      href: `/team-planning-oversight/?view=portfolio${fy ? `&fy=${encodeURIComponent(fy)}` : ''}`,
      icon: 'programmes',
    },
    {
      id: 'coverage',
      label: 'Schools & Coverage',
      href: `/team-planning-oversight/?view=coverage${fy ? `&fy=${encodeURIComponent(fy)}` : ''}`,
      icon: 'chart',
    },
    { id: 'clusters', label: 'Cluster Oversight', href: `/cluster-oversight/${qs}`, icon: 'team' },
    { id: 'schools', label: 'School Directory', href: '/schools', icon: 'schools' },
  ];
}

let cachedGeo: UgandaDistrictGeoJSON | null = null;

/** Reads the bundled UBOS district GeoJSON once on the server for instant SSR rendering. */
export function loadUgandaGeoJSON(): UgandaDistrictGeoJSON {
  if (cachedGeo) return cachedGeo;
  const geoPath = path.join(process.cwd(), 'public', 'geo', 'uganda_districts.geojson');
  if (fs.existsSync(/*turbopackIgnore: true*/ geoPath)) {
    const parsed = JSON.parse(fs.readFileSync(/*turbopackIgnore: true*/ geoPath, 'utf8')) as UgandaDistrictGeoJSON;
    cachedGeo = parsed;
    return parsed;
  }
  return { type: 'FeatureCollection', features: [] };
}

/** Fetches the live Go-computed country map analytics dataset as the signed-in reader. */
export async function fetchCountryMapData(fy?: string): Promise<CountryMapData | null> {
  const token = await accessToken();
  const url = new URL('/api/v1/country-map/data', environment().gatewayUrl);
  if (fy && fy.trim()) url.searchParams.set('fy', fy.trim());

  const res = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
    cache: 'no-store',
  });

  if (res.status === 401) {
    redirect(`/auth/refresh?next=${encodeURIComponent(await currentPath())}`);
  }
  if (res.status === 403 || res.status === 404) {
    return null;
  }
  if (!res.ok) {
    return null;
  }
  return (await res.json()) as CountryMapData;
}
