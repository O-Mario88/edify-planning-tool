'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Building2,
  Calendar,
  Check,
  ChevronRight,
  Compass,
  Download,
  Flag,
  GraduationCap,
  Handshake,
  Info,
  Layers,
  LocateFixed,
  Map as MapIcon,
  Maximize2,
  Minimize2,
  Minus,
  Plus,
  Trophy,
  Users,
  X,
  Zap,
} from 'lucide-react';

import type {
  CountryMapData,
  MapDistrictRow,
  MapNavTab,
  MapSchoolPin,
  UgandaDistrictFeature,
  UgandaDistrictGeoJSON,
} from '@/lib/countryMapData';
import { DonutChart, PageHeroHeader } from './EdifyDashboardChrome';
import type { DonutSlice } from './EdifyDashboardChrome';

/* ── Canonical UBOS Sub-Region Palette & Map Projection ────────────────── */

const SUB_REGION_COLORS: Readonly<Record<string, { fill: string; swatch: string; donut: string }>> = {
  'West Nile': { fill: '#f6b3a8', swatch: '#f6a89b', donut: '#ef6c5b' },
  Acholi: { fill: '#b3c2fc', swatch: '#9db1fa', donut: '#6366f1' },
  Karamoja: { fill: '#f3aad7', swatch: '#ed94cc', donut: '#ec4899' },
  Lango: { fill: '#fce89b', swatch: '#f9db74', donut: '#8b5cf6' },
  Teso: { fill: '#90ead7', swatch: '#64dec5', donut: '#14b8a6' },
  Elgon: { fill: '#fbcfe8', swatch: '#f4a8d4', donut: '#f472b6' },
  Western: { fill: '#9bc7fb', swatch: '#7bb5f9', donut: '#38bdf8' },
  'East Central': { fill: '#fab884', swatch: '#f7a161', donut: '#34d399' },
  Central: { fill: '#c4f177', swatch: '#a7e649', donut: '#0e5da3' },
  'South Western': { fill: '#f7b3e0', swatch: '#f094d1', donut: '#a855f7' },
};

const DEFAULT_SR_COLOR = { fill: '#cbd5e1', swatch: '#94a3b8', donut: '#94a3b8' };

function subRegionColor(name: string): { fill: string; swatch: string; donut: string } {
  return SUB_REGION_COLORS[name] ?? DEFAULT_SR_COLOR;
}

type SchoolTypeKey = 'core' | 'client' | 'champion' | 'core_trained' | 'core_graduate';

const SCHOOL_TYPE_META: readonly {
  readonly key: SchoolTypeKey;
  readonly label: string;
  readonly color: string;
  readonly countKey: keyof CountryMapData['totals'];
}[] = [
  { key: 'core', label: 'Core', color: '#ea580c', countKey: 'core' },
  { key: 'client', label: 'Client', color: '#0e5da3', countKey: 'clients' },
  { key: 'champion', label: 'Champion', color: '#16a34a', countKey: 'champions' },
  { key: 'core_trained', label: 'Core Trained', color: '#854d0e', countKey: 'core_trained' },
  { key: 'core_graduate', label: 'Core Graduate', color: '#7c3aed', countKey: 'core_graduates' },
];

const SCHOOL_PIN_COLORS: Readonly<Record<string, string>> = {
  core: '#ea580c',
  client: '#0e5da3',
  champion: '#16a34a',
  core_trained: '#854d0e',
  core_graduate: '#7c3aed',
};

// Uganda geographic bounding box (matches UBOS uganda_districts.geojson)
const MAP_W = 650;
const MAP_H = 490;
const LON_MIN = 29.45;
const LON_MAX = 35.15;
const LAT_MIN = -1.58;
const LAT_MAX = 4.35;
const PAD_L = 28;
const PAD_R = 200; // leaves clean room on right for floating Legend / Map Layers card
const PAD_T = 20;
const PAD_B = 20;

function projectPoint(lon: number, lat: number): [number, number] {
  const usableW = MAP_W - PAD_L - PAD_R;
  const usableH = MAP_H - PAD_T - PAD_B;
  const lonSpan = LON_MAX - LON_MIN;
  const latSpan = LAT_MAX - LAT_MIN;
  const scale = Math.min(usableW / lonSpan, usableH / latSpan);
  const offsetX = PAD_L + (usableW - lonSpan * scale) / 2;
  const offsetY = PAD_T + (usableH - latSpan * scale) / 2;
  const x = offsetX + (lon - LON_MIN) * scale;
  const y = offsetY + (LAT_MAX - lat) * scale;
  return [x, y];
}

function ringToPath(ring: readonly number[][]): string {
  if (!ring.length) return '';
  let d = '';
  for (let i = 0; i < ring.length; i += 1) {
    const pt = ring[i];
    if (!pt || pt.length < 2) continue;
    const [x, y] = projectPoint(pt[0] ?? 0, pt[1] ?? 0);
    d += `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }
  return d ? `${d}Z` : '';
}

function featureToPath(feature: UgandaDistrictFeature): string {
  const { type, coordinates } = feature.geometry;
  if (type === 'Polygon') {
    return (coordinates as number[][][]).map(ringToPath).join(' ');
  }
  return (coordinates as number[][][][])
    .flatMap((poly) => poly.map(ringToPath))
    .join(' ');
}

function formatCompact(n: number): string {
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}K`;
  if (n >= 1_000) return `${(n / 1000).toFixed(1)}K`;
  return n.toLocaleString('en-US');
}

function formatNumber(n: number): string {
  return n.toLocaleString('en-US');
}

function normalizeName(v: string): string {
  return v.trim().toLowerCase();
}

/* ── Sub-Region Centroid Overrides for Crisp Non-Overlapping Labels ───── */

const LABEL_NUDGE: Readonly<Record<string, [number, number]>> = {
  'West Nile': [-8, -6],
  Acholi: [2, -6],
  Karamoja: [14, -4],
  Lango: [0, 4],
  Teso: [6, 2],
  Elgon: [18, 6],
  Western: [-12, 8],
  'East Central': [16, 16],
  Central: [-4, 16],
  'South Western': [-4, 8],
};

/* ── Tab Icons ────────────────────────────────────────────────────────── */

function TabIcon({ kind }: { readonly kind: MapNavTab['icon'] }) {
  const cls = 'h-3.5 w-3.5 shrink-0';
  switch (kind) {
    case 'map':
      return <MapIcon className={cls} />;
    case 'priorities':
      return <Flag className={cls} />;
    case 'team':
      return <Users className={cls} />;
    case 'coaching':
      return <BookOpen className={cls} />;
    case 'programmes':
      return <Layers className={cls} />;
    case 'collaboration':
      return <Handshake className={cls} />;
    case 'schools':
      return <Building2 className={cls} />;
    case 'chart':
      return <BarChart3 className={cls} />;
    default:
      return null;
  }
}

/* ── Main Interactive Country Map View ────────────────────────────────── */

export function CountryMapView({
  data,
  geo,
  mode = 'country-map',
  eyebrow,
  title,
  description,
  basePath,
  tabs,
}: {
  readonly data: CountryMapData;
  readonly geo: UgandaDistrictGeoJSON;
  readonly mode?: 'country-map' | 'dashboard';
  readonly eyebrow: string;
  readonly title: string;
  readonly description: string;
  readonly basePath: string;
  readonly tabs: readonly MapNavTab[];
}) {
  const router = useRouter();
  const mapCardRef = useRef<HTMLDivElement | null>(null);
  const tableCardRef = useRef<HTMLDivElement | null>(null);

  // Interactive filter & map state
  const allSubRegionNames = data.sub_regions.map((sr) => sr.name);
  const [visibleSubRegions, setVisibleSubRegions] = useState<readonly string[]>(allSubRegionNames);
  const [visibleSchoolTypes, setVisibleSchoolTypes] = useState<readonly SchoolTypeKey[]>([
    'core',
    'client',
    'champion',
    'core_trained',
    'core_graduate',
  ]);
  const [panelTab, setPanelTab] = useState<'layers' | 'legend'>('legend');
  const [showBoundaries, setShowBoundaries] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [showPins, setShowPins] = useState(true);
  const [dimEmpty, setDimEmpty] = useState(false);

  // Map zoom / pan / selection
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [hoveredDistrict, setHoveredDistrict] = useState<string | null>(null);
  const [selectedSubRegion, setSelectedSubRegion] = useState<string | null>(null);
  const [selectedDistrict, setSelectedDistrict] = useState<string | null>(null);
  const [selectedPin, setSelectedPin] = useState<MapSchoolPin | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [showAllDistricts, setShowAllDistricts] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [compareMode, setCompareMode] = useState(false);
  const [sortBy, setSortBy] = useState<'schools' | 'coverage' | 'districts' | 'clients'>('schools');

  useEffect(() => {
    const onFs = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onFs);
    return () => document.removeEventListener('fullscreenchange', onFs);
  }, []);

  // Build quick lookup maps from real Go data
  const districtByName = new Map<string, MapDistrictRow>();
  for (const d of data.districts) {
    districtByName.set(normalizeName(d.name), d);
  }

  const visibleSRSet = new Set(visibleSubRegions.map(normalizeName));
  const visibleTypeSet = new Set(visibleSchoolTypes);

  // Compute sub-region label anchors directly from GeoJSON feature centroids
  const srCentroids = new Map<string, { sumLon: number; sumLat: number; count: number; name: string }>();
  for (const ft of geo.features) {
    const sr = ft.properties.s;
    const key = normalizeName(sr);
    const cur = srCentroids.get(key) ?? { sumLon: 0, sumLat: 0, count: 0, name: sr };
    cur.sumLon += ft.properties.lon;
    cur.sumLat += ft.properties.lat;
    cur.count += 1;
    srCentroids.set(key, cur);
  }
  const srLabels = Array.from(srCentroids.values()).map((entry) => {
    const [px, py] = projectPoint(entry.sumLon / entry.count, entry.sumLat / entry.count);
    const nudge = LABEL_NUDGE[entry.name] ?? [0, 0];
    return {
      name: entry.name,
      x: px + nudge[0],
      y: py + nudge[1],
    };
  });

  // Filter pins by visible sub-regions, school types, and active selection
  const filteredPins = data.pins.filter((pin) => {
    if (!visibleSRSet.has(normalizeName(pin.sub_region))) return false;
    const t = pin.school_type.toLowerCase() as SchoolTypeKey;
    if (!visibleTypeSet.has(t)) return false;
    if (selectedSubRegion && normalizeName(pin.sub_region) !== normalizeName(selectedSubRegion)) return false;
    if (selectedDistrict && normalizeName(pin.district) !== normalizeName(selectedDistrict)) return false;
    return true;
  });

  // Search matches across sub-regions, districts, and schools
  const q = searchQuery.trim().toLowerCase();
  const searchResults = q
    ? [
        ...data.sub_regions
          .filter((sr) => sr.name.toLowerCase().includes(q))
          .slice(0, 3)
          .map((sr) => ({ kind: 'Sub-Region' as const, label: sr.name, meta: `${formatNumber(sr.schools)} schools`, id: sr.name })),
        ...data.districts
          .filter((d) => d.name.toLowerCase().includes(q))
          .slice(0, 5)
          .map((d) => ({ kind: 'District' as const, label: d.name, meta: `${d.sub_region} · ${formatNumber(d.schools)} schools`, id: d.name })),
        ...data.pins
          .filter((p) => p.name.toLowerCase().includes(q) || p.school_id.toLowerCase().includes(q))
          .slice(0, 5)
          .map((p) => ({ kind: 'School' as const, label: p.name, meta: `${p.district} · ${p.school_type.replace('_', ' ')}`, id: p.id, pin: p })),
      ]
    : [];

  // Donut slices (top 5 sub-regions + Others)
  const totalSchools = data.totals.schools;
  const sortedBySchools = [...data.sub_regions].sort((a, b) => b.schools - a.schools || b.districts - a.districts);
  const top5SR = sortedBySchools.slice(0, 5);
  const otherSRs = sortedBySchools.slice(5);
  const othersSchools = otherSRs.reduce((acc, r) => acc + r.schools, 0);
  const othersDistricts = otherSRs.reduce((acc, r) => acc + r.districts, 0);
  const donutUseDistrictFallback = totalSchools === 0;
  const donutDenom = donutUseDistrictFallback ? Math.max(1, data.district_count) : Math.max(1, totalSchools);

  const donutSlices: DonutSlice[] = [
    ...top5SR.map((sr) => {
      const val = donutUseDistrictFallback ? sr.districts : sr.schools;
      const pct = Math.round((val * 100) / donutDenom);
      return {
        label: sr.name,
        value: val > 0 ? val : 0,
        color: subRegionColor(sr.name).donut,
        detail: `${pct}%`,
      };
    }),
    ...(otherSRs.length > 0
      ? [
          {
            label: 'Others',
            value: donutUseDistrictFallback ? othersDistricts : othersSchools,
            color: '#cbd5e1',
            detail: `${Math.round(((donutUseDistrictFallback ? othersDistricts : othersSchools) * 100) / donutDenom)}%`,
          },
        ]
      : []),
  ];

  // Districts list for Top 5 / View All
  const topDistricts = showAllDistricts ? data.districts.slice(0, 40) : data.districts.slice(0, 5);

  // Sorted sub-region breakdown rows for bottom table
  const sortedSubRegions = [...data.sub_regions].sort((a, b) => {
    if (sortBy === 'coverage') return b.coverage_pct - a.coverage_pct || b.schools - a.schools;
    if (sortBy === 'districts') return b.districts - a.districts || b.schools - a.schools;
    if (sortBy === 'clients') return b.clients - a.clients || b.schools - a.schools;
    return b.schools - a.schools || b.districts - a.districts;
  });

  // Map focus & zoom helpers
  const focusPoint = (lon: number, lat: number, nextZoom: number) => {
    const [px, py] = projectPoint(lon, lat);
    const cx = (MAP_W - PAD_R + PAD_L) / 2;
    const cy = MAP_H / 2;
    setZoom(nextZoom);
    setPan({ x: (cx - px) * nextZoom, y: (cy - py) * nextZoom });
  };

  const focusSubRegion = (srName: string) => {
    if (selectedSubRegion && normalizeName(selectedSubRegion) === normalizeName(srName)) {
      resetView();
      return;
    }
    setSelectedSubRegion(srName);
    setSelectedDistrict(null);
    setSelectedPin(null);
    if (!visibleSRSet.has(normalizeName(srName))) {
      setVisibleSubRegions((prev) => [...prev, srName]);
    }
    const c = srCentroids.get(normalizeName(srName));
    if (c) focusPoint(c.sumLon / c.count, c.sumLat / c.count, 1.85);
  };

  const focusDistrict = (districtName: string) => {
    setSelectedDistrict(districtName);
    setSelectedPin(null);
    const ft = geo.features.find((f) => normalizeName(f.properties.d) === normalizeName(districtName));
    if (ft) {
      setSelectedSubRegion(ft.properties.s);
      if (!visibleSRSet.has(normalizeName(ft.properties.s))) {
        setVisibleSubRegions((prev) => [...prev, ft.properties.s]);
      }
      focusPoint(ft.properties.lon, ft.properties.lat, 2.6);
    }
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSelectedSubRegion(null);
    setSelectedDistrict(null);
    setSelectedPin(null);
  };

  const toggleSubRegion = (name: string) => {
    setVisibleSubRegions((prev) =>
      prev.includes(name) ? prev.filter((item) => item !== name) : [...prev, name],
    );
  };

  const toggleSchoolType = (key: SchoolTypeKey) => {
    setVisibleSchoolTypes((prev) => {
      if (prev.includes(key)) {
        return prev.length === 1 ? ['core', 'client', 'champion', 'core_trained', 'core_graduate'] : prev.filter((k) => k !== key);
      }
      return [...prev, key];
    });
  };

  const handleFYChange = (nextFY: string) => {
    const params = new URLSearchParams();
    params.set('fy', nextFY);
    if (mode === 'dashboard') params.set('view', 'map');
    router.push(`${basePath}?${params.toString()}`);
  };

  const handleFullscreen = async () => {
    if (!mapCardRef.current) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen().catch(() => {});
    } else {
      await mapCardRef.current.requestFullscreen?.().catch(() => {});
    }
  };

  const handleExportCSV = () => {
    const header = ['Sub-Region', 'Districts', 'Schools', 'Clients', 'Core', 'Champions', 'Core Trained', 'Core Graduates', 'Coverage (%)'];
    const lines = [
      header.join(','),
      ...data.sub_regions.map((r) =>
        [
          `"${r.name.replace(/"/g, '""')}"`,
          r.districts,
          r.schools,
          r.clients,
          r.core,
          r.champions,
          r.core_trained,
          r.core_graduates,
          r.coverage_pct,
        ].join(','),
      ),
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `edify-country-map-fy${data.fy}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const hoveredInfo = hoveredDistrict ? districtByName.get(normalizeName(hoveredDistrict)) : undefined;

  return (
    <div className="mx-auto w-full max-w-[1440px] space-y-4 pb-8" data-page={basePath} data-testid="country-map-view">
      {/* ── 1. Edify Hero Header ───────────────────────────────────────── */}
      <PageHeroHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
        icon={<Layers className="h-5 w-5" />}
        actions={
          <div className="flex flex-wrap items-center gap-2.5">
            <div
              className="inline-flex items-center gap-2 rounded-full border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-3.5 py-1.5 text-[12.5px] font-semibold text-[var(--edify-navy-950,#001d39)] shadow-xs dark:text-[var(--edify-text)]"
              data-testid="map-scope-pill"
            >
              <span className="h-2 w-2 rounded-full bg-[var(--edify-success)]" aria-hidden="true" />
              <span>
                {formatNumber(data.cceos)} {data.cceos === 1 ? 'CCEO' : 'CCEOs'} · {formatNumber(data.totals.schools)} schools
              </span>
            </div>

            <div className="inline-flex items-center gap-1.5">
              <Calendar className="h-4 w-4 shrink-0 text-[var(--edify-text-muted)]" aria-hidden="true" />
              <select
                aria-label="Fiscal year"
                value={data.fy}
                onChange={(e) => handleFYChange(e.target.value)}
                className="edify-select h-9 cursor-pointer rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] pl-3 pr-8 text-[13px] font-semibold text-[var(--edify-text)] shadow-xs"
              >
                {data.fy_options.map((y) => (
                  <option key={y} value={y}>
                    FY {y}
                  </option>
                ))}
              </select>
            </div>
          </div>
        }
      />

      {/* ── 2. Sub-Navigation Pill Tab Bar ─────────────────────────────── */}
      {tabs.length > 0 ? (
        <nav
          aria-label="Map views"
          className="flex items-center gap-1.5 overflow-x-auto rounded-[12px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-1.5 shadow-[var(--edify-shadow-xs)]"
        >
          {tabs.map((tab) => (
            <Link
              key={tab.id}
              href={tab.href}
              aria-current={tab.active ? 'page' : undefined}
              className={
                tab.active
                  ? 'inline-flex shrink-0 items-center gap-2 rounded-[9px] bg-[var(--brand-primary)] px-4 py-2 text-[13px] font-semibold text-white shadow-xs transition-colors'
                  : 'inline-flex shrink-0 items-center gap-2 rounded-[9px] px-3.5 py-2 text-[13px] font-semibold text-[var(--edify-text-muted)] transition-colors hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)]'
              }
            >
              <TabIcon kind={tab.icon} />
              <span>{tab.label}</span>
            </Link>
          ))}
        </nav>
      ) : null}

      {/* ── 3. Five Soft-Tinted KPI Stat Cards ─────────────────────────── */}
      <section aria-label="School classification summary" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {[
          {
            key: 'all' as const,
            label: 'Schools',
            value: data.totals.schools,
            icon: <Building2 className="h-5 w-5" />,
            cardCls: 'border-[#cfe2f7] bg-[linear-gradient(135deg,#f0f7ff_0%,#f8fbff_100%)] dark:border-[var(--edify-border)] dark:bg-[var(--edify-card-surface)]',
            iconCls: 'bg-[#dbeafe] text-[var(--brand-primary)]',
          },
          {
            key: 'client' as const,
            label: 'Clients',
            value: data.totals.clients,
            icon: <Users className="h-5 w-5" />,
            cardCls: 'border-[#ccebd8] bg-[linear-gradient(135deg,#eefcf4_0%,#f7fdf9_100%)] dark:border-[var(--edify-border)] dark:bg-[var(--edify-card-surface)]',
            iconCls: 'bg-[#dcfce7] text-[#15803d]',
          },
          {
            key: 'champion' as const,
            label: 'Champions',
            value: data.totals.champions,
            icon: <Trophy className="h-5 w-5" />,
            cardCls: 'border-[#f5e3b8] bg-[linear-gradient(135deg,#fffbeb_0%,#fffdf5_100%)] dark:border-[var(--edify-border)] dark:bg-[var(--edify-card-surface)]',
            iconCls: 'bg-[#fef3c7] text-[#b45309]',
          },
          {
            key: 'core_trained' as const,
            label: 'Core Trained',
            value: data.totals.core_trained,
            icon: <GraduationCap className="h-5 w-5" />,
            cardCls: 'border-[#e4d4fa] bg-[linear-gradient(135deg,#f7f2ff_0%,#fbf9ff_100%)] dark:border-[var(--edify-border)] dark:bg-[var(--edify-card-surface)]',
            iconCls: 'bg-[#f3e8ff] text-[#7c3aed]',
          },
          {
            key: 'core_graduate' as const,
            label: 'Core Graduates',
            value: data.totals.core_graduates,
            icon: <GraduationCap className="h-5 w-5" />,
            cardCls: 'border-[#d6dcf5] bg-[linear-gradient(135deg,#f2f4ff_0%,#f8f9ff_100%)] dark:border-[var(--edify-border)] dark:bg-[var(--edify-card-surface)]',
            iconCls: 'bg-[#e0e7ff] text-[#4338ca]',
          },
        ].map((kpi) => {
          const isFiltered = kpi.key !== 'all' && visibleSchoolTypes.length === 1 && visibleSchoolTypes[0] === kpi.key;
          return (
            <button
              key={kpi.label}
              type="button"
              onClick={() => {
                if (kpi.key === 'all') {
                  setVisibleSchoolTypes(['core', 'client', 'champion', 'core_trained', 'core_graduate']);
                } else {
                  setVisibleSchoolTypes(
                    isFiltered ? ['core', 'client', 'champion', 'core_trained', 'core_graduate'] : [kpi.key],
                  );
                }
              }}
              className={`flex items-center gap-3.5 rounded-[14px] border px-4 py-3.5 text-left shadow-[var(--edify-shadow-xs)] transition-all hover:shadow-[var(--edify-shadow-sm)] ${kpi.cardCls} ${
                isFiltered ? 'ring-2 ring-[var(--brand-primary)] ring-offset-1' : ''
              }`}
            >
              <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-[10px] ${kpi.iconCls}`} aria-hidden="true">
                {kpi.icon}
              </div>
              <div className="min-w-0">
                <div className="text-[22px] font-extrabold leading-tight tracking-[-0.02em] tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                  {formatNumber(kpi.value)}
                </div>
                <div className="text-[12.5px] font-semibold text-[var(--edify-text-muted)]">{kpi.label}</div>
              </div>
            </button>
          );
        })}
      </section>

      {/* ── 4. Main 2-Column Interactive Map + Right Analytics Rail ────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Left: Performance by Sub-Region Interactive UBOS Map */}
        <section
          ref={mapCardRef}
          aria-labelledby="map-card-heading"
          className="flex flex-col overflow-hidden rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-xs)] lg:col-span-8"
        >
          {/* Card Header */}
          <div className="flex flex-col gap-2.5 border-b border-[var(--edify-border)] px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-2.5">
              <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-[8px] bg-[var(--brand-primary-soft)] text-[var(--brand-primary)]">
                <MapIcon className="h-4 w-4" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <h2 id="map-card-heading" className="text-[15.5px] font-bold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                    Performance by Sub-Region
                  </h2>
                  <span
                    title="Click any sub-region or district to zoom and inspect live counts. Toggle school classifications or sub-regions in the legend."
                    className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[var(--edify-text-muted)] hover:text-[var(--brand-primary)]"
                  >
                    <Info className="h-3.5 w-3.5" />
                  </span>
                </div>
                <p className="text-[12px] text-[var(--edify-text-muted)]">
                  UBOS boundaries · sub-county detail on district zoom ·{' '}
                  <strong className="font-semibold text-[var(--edify-text)]">{data.scope_label}</strong>
                </p>
              </div>
            </div>

            {/* Search + Fullscreen */}
            <div className="relative flex items-center gap-2">
              <div className="relative w-full sm:w-[270px]">
                <input
                  type="search"
                  value={searchQuery}
                  onFocus={() => setSearchOpen(true)}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                    setSearchOpen(true);
                  }}
                  placeholder="Search sub-region, district, or school..."
                  aria-label="Search sub-region, district, or school"
                  className="h-9 w-full rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-surface)] !px-3 text-[12px] text-[var(--edify-text)] placeholder:text-[var(--edify-text-muted)] focus:border-[var(--brand-primary)] focus:outline-none"
                />
                {searchQuery ? (
                  <button
                    type="button"
                    aria-label="Clear search"
                    onClick={() => {
                      setSearchQuery('');
                      setSearchOpen(false);
                    }}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--edify-text-muted)] hover:text-[var(--edify-text)]"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                ) : null}

                {searchOpen && searchResults.length > 0 ? (
                  <div className="absolute right-0 top-full z-30 mt-1 w-full min-w-[260px] overflow-hidden rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] py-1 shadow-lg">
                    {searchResults.map((hit, idx) => (
                      <button
                        key={`${hit.kind}-${hit.id}-${idx}`}
                        type="button"
                        onClick={() => {
                          setSearchOpen(false);
                          setSearchQuery(hit.label);
                          if (hit.kind === 'Sub-Region') {
                            focusSubRegion(hit.label);
                          } else if (hit.kind === 'District') {
                            focusDistrict(hit.label);
                          } else if ('pin' in hit && hit.pin) {
                            setSelectedPin(hit.pin);
                            setSelectedDistrict(hit.pin.district);
                            setSelectedSubRegion(hit.pin.sub_region);
                            focusPoint(hit.pin.lng, hit.pin.lat, 3.0);
                          }
                        }}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[12.5px] hover:bg-[var(--brand-primary-soft)]"
                      >
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-[var(--edify-text)]">{hit.label}</div>
                          <div className="truncate text-[11px] text-[var(--edify-text-muted)]">{hit.meta}</div>
                        </div>
                        <span className="shrink-0 rounded-full bg-[var(--edify-surface-muted)] px-2 py-0.5 text-[10.5px] font-semibold text-[var(--edify-text-muted)]">
                          {hit.kind}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              <button
                type="button"
                onClick={handleFullscreen}
                aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen map'}
                title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen map'}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] text-[var(--edify-text-muted)] hover:border-[var(--brand-primary-border)] hover:text-[var(--brand-primary)]"
              >
                {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {/* Map Canvas + Floating Legend Overlay */}
          <div className="relative flex flex-1 flex-col bg-[linear-gradient(180deg,color-mix(in_srgb,var(--brand-primary)_2%,var(--edify-card-surface))_0%,var(--edify-card-surface)_100%)] sm:min-h-[488px]">
            {/* Top-left Zoom Controls */}
            <div className="absolute left-3.5 top-3.5 z-20 flex flex-col gap-1">
              <div className="flex flex-col overflow-hidden rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-sm">
                <button
                  type="button"
                  onClick={() => setZoom((z) => Math.min(4.5, Number((z + 0.45).toFixed(2))))}
                  aria-label="Zoom in"
                  className="grid h-8 w-8 place-items-center border-b border-[var(--edify-border)] text-[var(--edify-text)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary)]"
                >
                  <Plus className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setZoom((z) => Math.max(1, Number((z - 0.45).toFixed(2))))}
                  aria-label="Zoom out"
                  className="grid h-8 w-8 place-items-center text-[var(--edify-text)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary)]"
                >
                  <Minus className="h-4 w-4" />
                </button>
              </div>
              <button
                type="button"
                onClick={resetView}
                aria-label="Reset map view"
                title="Reset map view"
                className="grid h-8 w-8 place-items-center rounded-[9px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] text-[var(--edify-text)] shadow-sm hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary)]"
              >
                <LocateFixed className="h-4 w-4" />
              </button>
            </div>

            {/* Active Selection Breadcrumb Chip */}
            {selectedSubRegion || selectedDistrict ? (
              <div className="absolute left-14 top-3.5 z-20 inline-flex items-center gap-2 rounded-full border border-[var(--brand-primary-border)] bg-[var(--edify-card-surface)] px-3 py-1 text-[12px] font-semibold text-[var(--edify-navy-950,#001d39)] shadow-sm dark:text-[var(--edify-text)]">
                <Compass className="h-3.5 w-3.5 text-[var(--brand-primary)]" aria-hidden="true" />
                <span>
                  {selectedDistrict ? `${selectedDistrict} (${selectedSubRegion})` : selectedSubRegion}
                </span>
                <button
                  type="button"
                  onClick={resetView}
                  className="ml-0.5 rounded-full bg-[var(--brand-primary-soft)] px-1.5 py-0.5 text-[10.5px] font-bold text-[var(--brand-primary)] hover:underline"
                >
                  Reset
                </button>
              </div>
            ) : null}

            {/* Interactive SVG Uganda UBOS Choropleth + School Pins */}
            <div className="relative flex-1 overflow-hidden">
              <svg
                viewBox={`0 0 ${MAP_W} ${MAP_H}`}
                className="h-[340px] w-full select-none sm:h-[488px]"
                role="img"
                aria-label="Interactive Uganda sub-region performance map"
              >
                <g
                  style={{
                    transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                    transformOrigin: `${(MAP_W - PAD_R + PAD_L) / 2}px ${MAP_H / 2}px`,
                    transition: 'transform 220ms cubic-bezier(0.22, 1, 0.36, 1)',
                  }}
                >
                  {/* District Polygons */}
                  {geo.features.map((ft) => {
                    const dName = ft.properties.d;
                    const srName = ft.properties.s;
                    const srVisible = visibleSRSet.has(normalizeName(srName));
                    const stats = districtByName.get(normalizeName(dName));
                    const isHovered = hoveredDistrict !== null && normalizeName(hoveredDistrict) === normalizeName(dName);
                    const isSelectedDistrict = selectedDistrict !== null && normalizeName(selectedDistrict) === normalizeName(dName);
                    const isSelectedSR = selectedSubRegion !== null && normalizeName(selectedSubRegion) === normalizeName(srName);
                    const baseFill = subRegionColor(srName).fill;
                    const hasSchools = (stats?.schools ?? 0) > 0;
                    const dimmed =
                      !srVisible ||
                      (dimEmpty && !hasSchools) ||
                      (selectedSubRegion !== null && !isSelectedSR) ||
                      (selectedDistrict !== null && !isSelectedDistrict);

                    return (
                      <path
                        key={dName}
                        d={featureToPath(ft)}
                        fill={srVisible ? baseFill : '#e2e8f0'}
                        fillOpacity={dimmed ? 0.28 : isHovered || isSelectedDistrict ? 1 : 0.9}
                        stroke={isSelectedDistrict ? '#0e5da3' : isHovered ? '#073962' : showBoundaries ? '#ffffff' : baseFill}
                        strokeWidth={isSelectedDistrict ? 1.8 / zoom : isHovered ? 1.4 / zoom : 0.75 / zoom}
                        className="cursor-pointer transition-opacity duration-150"
                        onMouseEnter={() => setHoveredDistrict(dName)}
                        onMouseLeave={() => setHoveredDistrict((prev) => (prev === dName ? null : prev))}
                        onClick={() => focusDistrict(dName)}
                      >
                        <title>{`${dName} (${srName}): ${stats?.schools ?? 0} schools`}</title>
                      </path>
                    );
                  })}

                  {/* Geo-Located School Pins */}
                  {showPins
                    ? filteredPins.map((pin) => {
                        const [px, py] = projectPoint(pin.lng, pin.lat);
                        const color = SCHOOL_PIN_COLORS[pin.school_type.toLowerCase()] ?? '#0e5da3';
                        const active = selectedPin?.id === pin.id;
                        const r = (active ? 4.8 : zoom > 1.8 ? 2.7 : 2.9) / Math.sqrt(zoom);
                        return (
                          <circle
                            key={pin.id}
                            cx={px}
                            cy={py}
                            r={r}
                            fill={color}
                            stroke="#ffffff"
                            strokeWidth={(active ? 1.4 : 0.75) / Math.sqrt(zoom)}
                            className="cursor-pointer"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedPin(pin);
                            }}
                          >
                            <title>{`${pin.name} (${pin.district} · ${pin.school_type.replace('_', ' ')})`}</title>
                          </circle>
                        );
                      })
                    : null}

                  {/* Crisp White Sub-Region Pill Labels */}
                  {showLabels
                    ? srLabels.map((lbl) => {
                        if (!visibleSRSet.has(normalizeName(lbl.name))) return null;
                        if (selectedSubRegion && normalizeName(selectedSubRegion) !== normalizeName(lbl.name)) return null;
                        const text = lbl.name.toUpperCase();
                        const pillW = Math.max(46, text.length * 6.4 + 14) / Math.pow(zoom, 0.45);
                        const pillH = 18 / Math.pow(zoom, 0.45);
                        const fontSize = 8.6 / Math.pow(zoom, 0.45);
                        return (
                          <g
                            key={lbl.name}
                            transform={`translate(${lbl.x}, ${lbl.y})`}
                            className="cursor-pointer"
                            onClick={() => focusSubRegion(lbl.name)}
                          >
                            <rect
                              x={-pillW / 2}
                              y={-pillH / 2}
                              width={pillW}
                              height={pillH}
                              rx={4 / Math.pow(zoom, 0.45)}
                              fill="#ffffff"
                              fillOpacity={0.94}
                              stroke="#cbd5e1"
                              strokeWidth={0.7 / Math.pow(zoom, 0.45)}
                            />
                            <text
                              x={0}
                              y={fontSize * 0.34}
                              textAnchor="middle"
                              fontSize={fontSize}
                              fontWeight={800}
                              letterSpacing="0.03em"
                              fill="#073962"
                            >
                              {text}
                            </text>
                          </g>
                        );
                      })
                    : null}
                </g>
              </svg>

              {/* Hover Tooltip (bottom-left of map) */}
              {hoveredDistrict && !selectedPin ? (
                <div className="pointer-events-none absolute bottom-3.5 left-3.5 z-20 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)]/95 px-3 py-2 text-[12px] shadow-md backdrop-blur-xs">
                  <div className="font-bold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                    {hoveredDistrict}
                  </div>
                  <div className="text-[11px] text-[var(--edify-text-muted)]">
                    {hoveredInfo ? `${hoveredInfo.sub_region} Sub-Region` : 'Uganda UBOS District'} ·{' '}
                    <strong className="font-semibold text-[var(--edify-text)]">
                      {formatNumber(hoveredInfo?.schools ?? 0)} schools
                    </strong>
                  </div>
                </div>
              ) : null}

              {/* Selected School Pin Popup */}
              {selectedPin ? (
                <div className="absolute bottom-3.5 left-3.5 z-30 max-w-[270px] rounded-[12px] border border-[var(--brand-primary-border)] bg-[var(--edify-card-surface)] p-3 shadow-lg">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <Link
                        href={selectedPin.href}
                        className="block truncate text-[13px] font-bold text-[var(--brand-primary)] hover:underline"
                      >
                        {selectedPin.name}
                      </Link>
                      <p className="mt-0.5 text-[11.5px] text-[var(--edify-text-muted)]">
                        {selectedPin.district} · {selectedPin.sub_region}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedPin(null)}
                      aria-label="Close school popup"
                      className="text-[var(--edify-text-muted)] hover:text-[var(--edify-text)]"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2 text-[11px]">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--edify-surface-muted)] px-2 py-0.5 font-semibold capitalize text-[var(--edify-text)]">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: SCHOOL_PIN_COLORS[selectedPin.school_type.toLowerCase()] ?? '#0e5da3' }}
                      />
                      {selectedPin.school_type.replace('_', ' ')}
                    </span>
                    <Link href={selectedPin.href} className="inline-flex items-center gap-1 font-semibold text-[var(--brand-primary)] hover:underline">
                      Profile <ArrowRight className="h-3 w-3" />
                    </Link>
                  </div>
                </div>
              ) : null}
            </div>

            {/* Right Floating Overlay Panel: Map Layers | Legend */}
            <aside
              aria-label="Map layers and legend"
              className="z-20 m-3 rounded-[12px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)]/95 shadow-md backdrop-blur-xs sm:absolute sm:right-3.5 sm:top-3.5 sm:m-0 sm:w-[216px]"
            >
              {/* Panel Tabs */}
              <div className="grid grid-cols-2 border-b border-[var(--edify-border)] text-[12px] font-semibold">
                <button
                  type="button"
                  onClick={() => setPanelTab('layers')}
                  className={`py-2.5 text-center transition-colors ${
                    panelTab === 'layers'
                      ? 'border-b-2 border-[var(--brand-primary)] text-[var(--brand-primary)]'
                      : 'text-[var(--edify-text-muted)] hover:text-[var(--edify-text)]'
                  }`}
                >
                  Map Layers
                </button>
                <button
                  type="button"
                  onClick={() => setPanelTab('legend')}
                  className={`py-2.5 text-center transition-colors ${
                    panelTab === 'legend'
                      ? 'border-b-2 border-[var(--brand-primary)] text-[var(--brand-primary)]'
                      : 'text-[var(--edify-text-muted)] hover:text-[var(--edify-text)]'
                  }`}
                >
                  Legend
                </button>
              </div>

              {panelTab === 'legend' ? (
                <div className="space-y-3 p-3">
                  {/* SCHOOLS Section */}
                  <div>
                    <div className="mb-1.5 text-[10.5px] font-bold uppercase tracking-[0.06em] text-[var(--edify-text-muted)]">
                      Schools
                    </div>
                    <ul className="space-y-1">
                      {SCHOOL_TYPE_META.map((item) => {
                        const active = visibleTypeSet.has(item.key);
                        const count = data.totals[item.countKey];
                        return (
                          <li key={item.key}>
                            <button
                              type="button"
                              onClick={() => toggleSchoolType(item.key)}
                              className={`flex w-full items-center justify-between rounded-[6px] px-1.5 py-1 text-[12px] transition-opacity hover:bg-[var(--edify-surface-muted)] ${
                                active ? 'opacity-100' : 'opacity-40'
                              }`}
                            >
                              <span className="flex items-center gap-2 font-medium text-[var(--edify-text)]">
                                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: item.color }} />
                                {item.label}
                              </span>
                              <span className="font-bold tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                                {formatCompact(count)}
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>

                  {/* Sub-Regions Checkbox List */}
                  <div className="border-t border-[var(--edify-border)] pt-2.5">
                    <div className="mb-1.5 flex items-center justify-between">
                      <span className="text-[11.5px] font-bold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                        Sub-Regions ({data.sub_regions.length})
                      </span>
                      <button
                        type="button"
                        onClick={() =>
                          setVisibleSubRegions(
                            visibleSubRegions.length === allSubRegionNames.length ? [] : allSubRegionNames,
                          )
                        }
                        className="text-[10.5px] font-semibold text-[var(--brand-primary)] hover:underline"
                      >
                        {visibleSubRegions.length === allSubRegionNames.length ? 'Clear' : 'All'}
                      </button>
                    </div>
                    <ul className="max-h-[224px] space-y-0.5 overflow-y-auto pr-0.5">
                      {data.sub_regions.map((sr) => {
                        const checked = visibleSRSet.has(normalizeName(sr.name));
                        return (
                          <li key={sr.name}>
                            <label className="flex cursor-pointer items-center justify-between gap-2 rounded-[6px] px-1.5 py-0.5 text-[11.5px] hover:bg-[var(--edify-surface-muted)]">
                              <span className="flex min-w-0 items-center gap-2">
                                <span
                                  className="h-3 w-3.5 shrink-0 rounded-[3px]"
                                  style={{ backgroundColor: subRegionColor(sr.name).swatch }}
                                />
                                <span className="truncate font-medium text-[var(--edify-text)]">{sr.name}</span>
                              </span>
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleSubRegion(sr.name)}
                                className="sr-only"
                              />
                              <span
                                aria-hidden="true"
                                className={`grid h-4 w-4 shrink-0 place-items-center rounded-[4px] border transition-colors ${
                                  checked
                                    ? 'border-[var(--brand-primary)] bg-[var(--brand-primary)] text-white'
                                    : 'border-[var(--edify-border)] bg-[var(--edify-card-surface)]'
                                }`}
                              >
                                {checked ? <Check className="h-3 w-3 stroke-[3]" /> : null}
                              </span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="space-y-2.5 p-3 text-[12px]">
                  <div className="text-[10.5px] font-bold uppercase tracking-[0.06em] text-[var(--edify-text-muted)]">
                    Display Layers
                  </div>
                  {[
                    { label: 'District Boundaries', checked: showBoundaries, toggle: () => setShowBoundaries((v) => !v) },
                    { label: 'Sub-Region Labels', checked: showLabels, toggle: () => setShowLabels((v) => !v) },
                    { label: `School Pins (${formatNumber(filteredPins.length)})`, checked: showPins, toggle: () => setShowPins((v) => !v) },
                    { label: 'Dim Empty Districts', checked: dimEmpty, toggle: () => setDimEmpty((v) => !v) },
                  ].map((layer) => (
                    <label key={layer.label} className="flex cursor-pointer items-center justify-between gap-2 rounded-[6px] px-1.5 py-1.5 hover:bg-[var(--edify-surface-muted)]">
                      <span className="font-medium text-[var(--edify-text)]">{layer.label}</span>
                      <input type="checkbox" checked={layer.checked} onChange={layer.toggle} className="sr-only" />
                      <span
                        aria-hidden="true"
                        className={`grid h-4 w-4 shrink-0 place-items-center rounded-[4px] border transition-colors ${
                          layer.checked
                            ? 'border-[var(--brand-primary)] bg-[var(--brand-primary)] text-white'
                            : 'border-[var(--edify-border)] bg-[var(--edify-card-surface)]'
                        }`}
                      >
                        {layer.checked ? <Check className="h-3 w-3 stroke-[3]" /> : null}
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </aside>
          </div>
        </section>

        {/* Right Analytics Rail: Donut + Top 5 Districts */}
        <div className="flex flex-col gap-4 lg:col-span-4">
          {/* Distribution by Sub-Region Card */}
          <section
            aria-labelledby="distribution-heading"
            className="rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)]"
          >
            <h2 id="distribution-heading" className="text-[15px] font-bold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
              Distribution by Sub-Region
            </h2>
            <p className="mt-0.5 text-[12px] text-[var(--edify-text-muted)]">
              {formatNumber(data.district_count)} districts · {formatNumber(data.sub_region_count)} sub-regions ·{' '}
              {formatNumber(data.totals.schools)} schools
            </p>

            <div className="mt-4 flex items-center justify-between gap-4">
              <DonutChart
                slices={donutSlices}
                centerValue={formatNumber(data.totals.schools)}
                centerLabel="Schools"
                size={128}
                strokeWidth={19}
              />
              <ul className="min-w-0 flex-1 space-y-2 text-[12.5px]">
                {donutSlices.map((slice) => (
                  <li key={slice.label} className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: slice.color }} />
                      <span className="truncate font-medium text-[var(--edify-text)]">{slice.label}</span>
                    </span>
                    <span className="shrink-0 font-bold tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                      {slice.detail}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          {/* Top 5 Districts (by Schools) Card */}
          <section
            aria-labelledby="top-districts-heading"
            className="flex flex-1 flex-col rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)]"
          >
            <div className="flex items-center justify-between gap-2">
              <h2 id="top-districts-heading" className="text-[15px] font-bold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                {showAllDistricts ? 'All Districts (by Schools)' : 'Top 5 Districts (by Schools)'}
              </h2>
              {showAllDistricts ? (
                <button
                  type="button"
                  onClick={() => setShowAllDistricts(false)}
                  className="text-[12px] font-semibold text-[var(--brand-primary)] hover:underline"
                >
                  Show Top 5
                </button>
              ) : null}
            </div>

            <div className={`mt-3 overflow-x-auto ${showAllDistricts ? 'max-h-[260px] overflow-y-auto' : ''}`}>
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-[var(--edify-border)] text-left text-[11.5px] font-semibold text-[var(--edify-text-muted)]">
                    <th className="w-8 py-2 pr-2">#</th>
                    <th className="py-2 pr-2">District</th>
                    <th className="py-2 text-right">Schools</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--edify-table-divider)]">
                  {topDistricts.map((d, idx) => {
                    const active = selectedDistrict !== null && normalizeName(selectedDistrict) === normalizeName(d.name);
                    return (
                      <tr
                        key={d.id || d.name}
                        onClick={() => focusDistrict(d.name)}
                        className={`cursor-pointer transition-colors hover:bg-[var(--brand-primary-soft)] ${
                          active ? 'bg-[var(--brand-primary-soft)]' : ''
                        }`}
                      >
                        <td className="py-2 pr-2 font-semibold tabular-nums text-[var(--edify-text-muted)]">{idx + 1}</td>
                        <td className="py-2 pr-2 font-semibold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                          {d.name}
                        </td>
                        <td className="py-2 text-right font-bold tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                          {formatNumber(d.schools)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="mt-3 border-t border-[var(--edify-border)] pt-3">
              <button
                type="button"
                onClick={() => setShowAllDistricts((v) => !v)}
                className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[var(--brand-primary)] hover:underline"
              >
                <span>{showAllDistricts ? 'Collapse to Top 5' : 'View All Districts'}</span>
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          </section>
        </div>
      </div>

      {/* ── 5. Bottom 2-Column Row: Sub-Region Table + Quick Actions ───── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Left: Sub-Region Breakdown Table */}
        <section
          ref={tableCardRef}
          aria-label="Sub-Region Performance Table"
          className={`overflow-hidden rounded-[16px] border bg-[var(--edify-card-surface)] shadow-[var(--edify-shadow-xs)] lg:col-span-9 ${
            compareMode ? 'border-[var(--brand-primary)] ring-2 ring-[var(--brand-primary-soft)]' : 'border-[var(--edify-border)]'
          }`}
        >
          {compareMode ? (
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--edify-border)] bg-[var(--brand-primary-soft)] px-4 py-2 text-[12.5px]">
              <span className="font-semibold text-[var(--brand-primary-text)]">
                Comparing all {data.sub_regions.length} sub-regions — sort by metric or click any row to focus the map.
              </span>
              <div className="flex items-center gap-1.5">
                {(['schools', 'coverage', 'districts', 'clients'] as const).map((col) => (
                  <button
                    key={col}
                    type="button"
                    onClick={() => setSortBy(col)}
                    className={`rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold capitalize ${
                      sortBy === col
                        ? 'bg-[var(--brand-primary)] text-white'
                        : 'bg-[var(--edify-card-surface)] text-[var(--edify-text)]'
                    }`}
                  >
                    {col}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setCompareMode(false)}
                  aria-label="Close compare mode"
                  className="ml-1 text-[var(--edify-text-muted)] hover:text-[var(--edify-text)]"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          ) : null}

          <div className="overflow-x-auto">
            <table className="w-full table-auto border-collapse text-[12.5px]">
              <thead>
                <tr className="border-b border-[var(--edify-border)] bg-[var(--edify-surface)] text-left text-[11.5px] font-bold text-[var(--edify-navy-900,#073962)] dark:text-[var(--edify-text-muted)]">
                  <th className="whitespace-nowrap !px-3 !py-2.5">Sub-Region</th>
                  <th className="whitespace-nowrap !px-2 !py-2.5 text-right">
                    <button type="button" onClick={() => setSortBy('districts')} className="hover:text-[var(--brand-primary)]">
                      Districts
                    </button>
                  </th>
                  <th className="whitespace-nowrap !px-2 !py-2.5 text-right">
                    <button type="button" onClick={() => setSortBy('schools')} className="hover:text-[var(--brand-primary)]">
                      Schools
                    </button>
                  </th>
                  <th className="whitespace-nowrap !px-2 !py-2.5 text-right">
                    <button type="button" onClick={() => setSortBy('clients')} className="hover:text-[var(--brand-primary)]">
                      Clients
                    </button>
                  </th>
                  <th className="whitespace-nowrap !px-2 !py-2.5 text-right">Champions</th>
                  <th className="whitespace-nowrap !px-2 !py-2.5 text-right">Core Trained</th>
                  <th className="whitespace-nowrap !px-2 !py-2.5 text-right">Core Graduates</th>
                  <th className="whitespace-nowrap !px-3 !py-2.5 text-right">
                    <button type="button" onClick={() => setSortBy('coverage')} className="hover:text-[var(--brand-primary)]">
                      Coverage
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--edify-table-divider)]">
                {sortedSubRegions.map((sr) => {
                  const active = selectedSubRegion !== null && normalizeName(selectedSubRegion) === normalizeName(sr.name);
                  return (
                    <tr
                      key={sr.name}
                      onClick={() => focusSubRegion(sr.name)}
                      className={`cursor-pointer transition-colors hover:bg-[var(--brand-primary-soft)]/70 ${
                        active ? 'bg-[var(--brand-primary-soft)]' : ''
                      }`}
                    >
                      <td className="whitespace-nowrap !px-3 !py-2.5 font-semibold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                        <span className="inline-flex items-center gap-2">
                          <span
                            className="h-3 w-3 shrink-0 rounded-[3px]"
                            style={{ backgroundColor: subRegionColor(sr.name).swatch }}
                          />
                          <span>{sr.name}</span>
                        </span>
                      </td>
                      <td className="!px-2 !py-2.5 text-right tabular-nums text-[var(--edify-text)]">{formatNumber(sr.districts)}</td>
                      <td className="!px-2 !py-2.5 text-right font-bold tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                        {formatNumber(sr.schools)}
                      </td>
                      <td className="!px-2 !py-2.5 text-right tabular-nums text-[var(--edify-text)]">{formatNumber(sr.clients)}</td>
                      <td className="!px-2 !py-2.5 text-right tabular-nums text-[var(--edify-text)]">{formatNumber(sr.champions)}</td>
                      <td className="!px-2 !py-2.5 text-right tabular-nums text-[var(--edify-text)]">{formatNumber(sr.core_trained)}</td>
                      <td className="!px-2 !py-2.5 text-right tabular-nums text-[var(--edify-text)]">{formatNumber(sr.core_graduates)}</td>
                      <td className="whitespace-nowrap !px-3 !py-2.5">
                        <div className="flex items-center justify-end gap-2">
                          <span className="w-8 text-right text-[12px] font-bold tabular-nums text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                            {sr.coverage_pct}%
                          </span>
                          <div className="h-2 w-14 overflow-hidden rounded-full bg-[var(--edify-surface-muted)]">
                            <div
                              className="h-full rounded-full bg-[#2ea86f] transition-all"
                              style={{ width: `${Math.max(0, Math.min(100, sr.coverage_pct))}%` }}
                            />
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        {/* Right: Quick Actions Card */}
        <section
          aria-labelledby="quick-actions-heading"
          className="flex flex-col justify-between rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4 shadow-[var(--edify-shadow-xs)] lg:col-span-3"
        >
          <div>
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
              <h2 id="quick-actions-heading" className="text-[15px] font-bold text-[var(--edify-navy-950,#001d39)] dark:text-[var(--edify-text)]">
                Quick Actions
              </h2>
            </div>

            <div className="mt-3.5 space-y-2.5">
              <Link
                href="/schools"
                className="flex w-full items-center justify-between gap-2 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3.5 py-2.5 text-[13px] font-semibold text-[var(--edify-navy-950,#001d39)] transition-colors hover:border-[var(--brand-primary-border)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)] dark:text-[var(--edify-text)]"
              >
                <span className="flex items-center gap-2.5">
                  <BookOpen className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                  <span>View School Directory</span>
                </span>
                <ChevronRight className="h-4 w-4 text-[var(--edify-text-muted)]" aria-hidden="true" />
              </Link>

              <button
                type="button"
                onClick={() => {
                  setCompareMode(true);
                  setSortBy('coverage');
                  tableCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }}
                className="flex w-full items-center justify-between gap-2 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3.5 py-2.5 text-[13px] font-semibold text-[var(--edify-navy-950,#001d39)] transition-colors hover:border-[var(--brand-primary-border)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)] dark:text-[var(--edify-text)]"
              >
                <span className="flex items-center gap-2.5">
                  <BarChart3 className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                  <span>Compare Sub-Regions</span>
                </span>
                <ChevronRight className="h-4 w-4 text-[var(--edify-text-muted)]" aria-hidden="true" />
              </button>

              <button
                type="button"
                onClick={handleExportCSV}
                className="flex w-full items-center justify-between gap-2 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3.5 py-2.5 text-[13px] font-semibold text-[var(--edify-navy-950,#001d39)] transition-colors hover:border-[var(--brand-primary-border)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)] dark:text-[var(--edify-text)]"
              >
                <span className="flex items-center gap-2.5">
                  <Download className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                  <span>Export Map Data</span>
                </span>
                <ChevronRight className="h-4 w-4 text-[var(--edify-text-muted)]" aria-hidden="true" />
              </button>

              <div className="grid grid-cols-2 gap-2 pt-0.5">
                <a
                  href={`/exports/school_directory?format=xlsx&fy=${encodeURIComponent(data.fy)}`}
                  download
                  className="flex items-center justify-center gap-1.5 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 py-2 text-[12px] font-semibold text-[var(--edify-navy-950,#001d39)] transition-colors hover:border-[var(--brand-primary-border)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)] dark:text-[var(--edify-text)]"
                >
                  <Download className="h-3.5 w-3.5 text-[var(--brand-primary)]" aria-hidden="true" />
                  <span>Excel (.xlsx)</span>
                </a>
                <a
                  href={`/exports/school_directory?format=pdf&fy=${encodeURIComponent(data.fy)}`}
                  download
                  className="flex items-center justify-center gap-1.5 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 py-2 text-[12px] font-semibold text-[var(--edify-navy-950,#001d39)] transition-colors hover:border-[var(--brand-primary-border)] hover:bg-[var(--brand-primary-soft)] hover:text-[var(--brand-primary-text)] dark:text-[var(--edify-text)]"
                >
                  <Download className="h-3.5 w-3.5 text-[var(--brand-primary)]" aria-hidden="true" />
                  <span>PDF Report</span>
                </a>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
