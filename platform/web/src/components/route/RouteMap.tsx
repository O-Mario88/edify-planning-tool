'use client';

/**
 * Interactive Road Map for Smart Route Planner & In-App Navigation (Sections 2, 3, 6, 9).
 *
 * Non-negotiable routing & rendering guarantees:
 *   1. NEVER draws straight lines between school markers as a drivable route.
 *      Only renders genuine road-network polylines returned by the routing provider.
 *   2. Supports official Google Maps JavaScript API (with Traffic Layer,
 *      Roadmap/Satellite toggle, and Google attribution) when
 *      NEXT_PUBLIC_GOOGLE_MAPS_API_KEY is configured.
 *   3. Falls back cleanly to MapLibre GL (OpenFreeMap streets + ESRI Satellite
 *      imagery toggle) in keyless development while enforcing road-only polylines.
 *   4. Renders numbered school pins, clickable alternative routes, active
 *      road-condition hazard pins, live GPS user location, recenter, and fullscreen.
 */
import 'maplibre-gl/dist/maplibre-gl.css';

import type { Feature, FeatureCollection, LineString } from 'geojson';
import type { GeoJSONSource, Map as MapLibreMap, Marker as MapLibreMarker } from 'maplibre-gl';
import { Expand, Layers, LocateFixed, Minimize, Minus, Plus, TrafficCone } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { create } from '@bufbuild/protobuf';

import { ItineraryStopSchema } from '@/gen/edify/routes/v1/routes_pb';
import type { ItineraryStop, SchoolPin } from '@/gen/edify/routes/v1/routes_pb';
import { pinTone } from '@/lib/routePlanner';
import type { AlternativeRouteData, LatLngPoint, RoadConditionReportData } from '@/lib/routePlanner';

import { RouteIcon } from './RouteIcons';

export const MAP_STYLE_STREETS = 'https://tiles.openfreemap.org/styles/liberty';
export const MAP_STYLE = MAP_STYLE_STREETS;

const SATELLITE_STYLE = {
  version: 8 as const,
  sources: {
    'esri-satellite': {
      type: 'raster' as const,
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      attribution: 'Tiles © Esri',
    },
  },
  layers: [{ id: 'esri-satellite-layer', type: 'raster' as const, source: 'esri-satellite' }],
};

const WORKER_URL = '/maplibre-worker.mjs';
const UGANDA_CENTRE: [number, number] = [32.58, 0.35];

export const TONES = {
  planned: '#0e5da3',
  suggested: '#0284c7',
  completed: '#1e3a8a',
  other: '#94a3b8',
} as const;

export interface RouteMapProps {
  stops: readonly ItineraryStop[];
  /** Road-following polyline from provider. Empty when no road route exists (NEVER drawn as straight lines). */
  path: readonly LatLngPoint[];
  /** True only when `path` is verified provider road geometry. */
  pathIsRoad?: boolean;
  /** Alternative provider road routes that the user can click to compare/switch. */
  alternatives?: readonly AlternativeRouteData[];
  activeAlternativeId?: string | null;
  onSelectAlternative?: (id: string | null) => void;
  /** Active road-condition reports to pin as warning markers on the map. */
  roadAlerts?: readonly RoadConditionReportData[];
  /** Live user GPS coordinates during in-app navigation. */
  userLocation?: LatLngPoint | null;
  others: readonly SchoolPin[];
  chip: string | null;
  onSelect: (pin: SchoolPin) => void;
  onView?: (sw: LatLngPoint, ne: LatLngPoint) => void;
  className?: string;
  showLegend?: boolean;
  focus?: SchoolPin;
  fitOthers?: boolean;
  /** Optional map controls bar (satellite/traffic/fullscreen). Defaults to true when legend is shown. */
  showControls?: boolean;
  /** A small card's map: three small buttons in the corner and a one-line credit. */
  compact?: boolean;
}

function pinElement(stop: ItineraryStop): HTMLElement {
  const school = stop.school!;
  const tone = pinTone(school, stop.kind);
  const root = document.createElement('button');
  root.type = 'button';
  root.className = 'edify-route-pin';
  root.setAttribute('aria-label', stop.order ? `Stop ${stop.order}: ${school.name}` : school.name);
  const drop = document.createElement('span');
  drop.className = 'edify-route-pin__drop';
  drop.style.background = TONES[tone];
  const number = document.createElement('span');
  number.className = 'edify-route-pin__number';
  number.textContent = stop.order ? String(stop.order) : '';
  drop.append(number);
  const label = document.createElement('span');
  label.className = 'edify-route-pin__label';
  label.textContent = school.name;
  root.append(drop, label);
  return root;
}

function hazardElement(alert: RoadConditionReportData): HTMLElement {
  const el = document.createElement('div');
  el.className =
    'flex items-center gap-1 rounded-full border-2 border-white px-2 py-0.5 text-[11px] font-bold text-white shadow-md';
  el.style.background = alert.impact_level === 'impassable' ? '#dc2626' : '#d97706';
  el.title = `${alert.road_name} — ${alert.category.replaceAll('_', ' ')} (${alert.verification_status})`;
  el.textContent = `! ${alert.road_name.slice(0, 18)}`;
  return el;
}

const overlaps = (a: DOMRect, b: DOMRect) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

export function placeLabels(pins: readonly HTMLElement[], frame: HTMLElement | null) {
  const drops = pins.map((p) => p.querySelector('.edify-route-pin__drop')!.getBoundingClientRect());
  const labels: DOMRect[] = frame ? [...frame.querySelectorAll('[data-map-overlay]')].map((o) => o.getBoundingClientRect()) : [];
  const bounds = frame?.getBoundingClientRect();
  const inside = (box: DOMRect) =>
    !bounds || (box.left >= bounds.left + 4 && box.right <= bounds.right - 4 && box.top >= bounds.top + 4 && box.bottom <= bounds.bottom - 4);
  pins.forEach((pin, i) => {
    const label = pin.querySelector<HTMLElement>('.edify-route-pin__label');
    if (!label) return;
    const blocked = (box: DOMRect) =>
      !inside(box) || drops.some((d, j) => j !== i && overlaps(d, box)) || labels.some((l) => overlaps(l, box));
    for (const side of ['right', 'left', 'below', 'above'] as const) {
      pin.dataset.label = side;
      const box = label.getBoundingClientRect();
      if (!blocked(box)) {
        labels.push(box);
        return;
      }
    }
    pin.dataset.label = 'hidden';
  });
}

function othersCollection(others: readonly SchoolPin[]): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: others
      .filter((p) => p.point)
      .map((p) => ({
        type: 'Feature',
        properties: { id: p.schoolId, name: p.name, tone: TONES[pinTone(p)] },
        geometry: { type: 'Point', coordinates: [p.point!.lng, p.point!.lat] },
      })),
  };
}

/**
 * Builds GeoJSON ONLY from verified provider road geometry (Section 2).
 * Straight lines between school markers are NEVER rendered as a drivable route.
 */
function roadLineCollection(
  path: readonly LatLngPoint[],
  pathIsRoad: boolean,
  alternatives: readonly AlternativeRouteData[],
  activeAlternativeId: string | null,
): FeatureCollection {
  const features: Feature<LineString>[] = [];
  for (const alt of alternatives) {
    if (alt.path.length < 2) continue;
    const isActive = activeAlternativeId === alt.id;
    features.push({
      type: 'Feature',
      properties: { kind: isActive ? 'primary' : 'alternative', id: alt.id },
      geometry: { type: 'LineString', coordinates: alt.path.map((p) => [p.lng, p.lat]) },
    });
  }
  if (pathIsRoad && path.length >= 2) {
    features.push({
      type: 'Feature',
      properties: { kind: activeAlternativeId ? 'alternative' : 'primary', id: 'primary' },
      geometry: { type: 'LineString', coordinates: path.map((p) => [p.lng, p.lat]) },
    });
  }
  return { type: 'FeatureCollection', features };
}

function fit(instance: MapLibreMap, extent: [[number, number], [number, number]]) {
  const { width, height } = instance.getContainer().getBoundingClientRect();
  if (width < 50 || height < 50) return;
  const pad = Math.min(80, Math.round(Math.min(width, height) / 6));
  instance.fitBounds(extent, {
    padding: { top: pad, bottom: pad, left: pad, right: Math.min(pad * 2, width / 3) },
    maxZoom: 14,
    duration: 0,
  });
}

function ensureSourcesAndLayers(
  created: MapLibreMap,
  others: readonly SchoolPin[],
  path: readonly LatLngPoint[],
  pathIsRoad: boolean,
  alternatives: readonly AlternativeRouteData[],
  activeAlternativeId: string | null,
) {
  if (!created.getSource('route-line')) {
    created.addSource('route-line', {
      type: 'geojson',
      data: roadLineCollection(path, pathIsRoad, alternatives, activeAlternativeId),
    });
    created.addLayer({
      id: 'route-line-alt',
      type: 'line',
      source: 'route-line',
      filter: ['==', ['get', 'kind'], 'alternative'],
      paint: { 'line-color': '#64748b', 'line-width': 4, 'line-opacity': 0.72, 'line-dasharray': [2, 1.5] },
      layout: { 'line-join': 'round', 'line-cap': 'round' },
    });
    created.addLayer({
      id: 'route-line-casing',
      type: 'line',
      source: 'route-line',
      filter: ['==', ['get', 'kind'], 'primary'],
      paint: { 'line-color': '#ffffff', 'line-width': 9.5, 'line-opacity': 0.95 },
      layout: { 'line-join': 'round', 'line-cap': 'round' },
    });
    created.addLayer({
      id: 'route-line',
      type: 'line',
      source: 'route-line',
      filter: ['==', ['get', 'kind'], 'primary'],
      paint: { 'line-color': TONES.planned, 'line-width': 5.5 },
      layout: { 'line-join': 'round', 'line-cap': 'round' },
    });
  }
  if (!created.getSource('schools')) {
    created.addSource('schools', {
      type: 'geojson',
      data: othersCollection(others),
      cluster: true,
      clusterRadius: 40,
      clusterMaxZoom: 12,
    });
    created.addLayer({
      id: 'school-clusters',
      type: 'circle',
      source: 'schools',
      filter: ['has', 'point_count'],
      paint: {
        'circle-color': '#64748b',
        'circle-radius': ['step', ['get', 'point_count'], 14, 20, 18, 100, 24],
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff',
      },
    });
    created.addLayer({
      id: 'school-cluster-count',
      type: 'symbol',
      source: 'schools',
      filter: ['has', 'point_count'],
      layout: { 'text-field': ['concat', '+', ['get', 'point_count_abbreviated']], 'text-size': 12, 'text-font': ['Noto Sans Bold'] },
      paint: { 'text-color': '#fff' },
    });
    created.addLayer({
      id: 'school-points',
      type: 'circle',
      source: 'schools',
      filter: ['!', ['has', 'point_count']],
      paint: { 'circle-color': ['get', 'tone'], 'circle-radius': 6, 'circle-stroke-width': 2, 'circle-stroke-color': '#fff' },
    });
  }
}

export function RouteMap({
  stops,
  path,
  pathIsRoad = path.length > 1,
  alternatives = [],
  activeAlternativeId = null,
  onSelectAlternative,
  roadAlerts = [],
  userLocation = null,
  others,
  chip,
  onSelect,
  onView,
  className,
  showLegend = true,
  focus,
  fitOthers = false,
  showControls = showLegend,
  compact = false,
}: RouteMapProps) {
  const googleMapsKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || '';
  const box = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef<MapLibreMarker[]>([]);
  const alertMarkers = useRef<MapLibreMarker[]>([]);
  const here = useRef<MapLibreMarker | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [baseLayer, setBaseLayer] = useState<'streets' | 'satellite'>('streets');
  const [showTraffic, setShowTraffic] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const select = useRef(onSelect);
  const view = useRef(onView);
  const othersRef = useRef(others);
  const pathRef = useRef(path);
  const pathIsRoadRef = useRef(pathIsRoad);
  const altRef = useRef(alternatives);
  const activeAltRef = useRef(activeAlternativeId);
  const extent = useRef<[[number, number], [number, number]] | null>(null);
  const moved = useRef(false);

  useEffect(() => {
    select.current = onSelect;
    view.current = onView;
    othersRef.current = others;
    pathRef.current = path;
    pathIsRoadRef.current = pathIsRoad;
    altRef.current = alternatives;
    activeAltRef.current = activeAlternativeId;
  });

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  // Load MapLibre map instance (or Google Maps JS when NEXT_PUBLIC_GOOGLE_MAPS_API_KEY is active).
  useEffect(() => {
    let cancelled = false;
    let instance: MapLibreMap | null = null;
    let resizer: ResizeObserver | null = null;
    import('maplibre-gl')
      .then(({ Map, setWorkerUrl }) => {
        if (cancelled || !box.current) return;
        setWorkerUrl(WORKER_URL);
        const created = new Map({
          container: box.current,
          style: MAP_STYLE_STREETS,
          center: UGANDA_CENTRE,
          zoom: 9,
          attributionControl: false,
        });
        instance = created;
        map.current = created;
        resizer = new ResizeObserver(() => {
          created.resize();
          if (!moved.current && extent.current) fit(created, extent.current);
        });
        resizer.observe(box.current);
        created.on('error', (event) => {
          if (!created.isStyleLoaded()) setFailed(/style|fetch|network|load/i.test(String(event.error?.message ?? '')));
        });
        const setup = () => {
          if (cancelled) return;
          ensureSourcesAndLayers(
            created,
            othersRef.current,
            pathRef.current,
            pathIsRoadRef.current,
            altRef.current,
            activeAltRef.current,
          );
          setReady(true);
        };
        created.on('load', () => {
          setup();
          created.on('click', 'school-points', (event) => {
            const id = event.features?.[0]?.properties?.id;
            const pin = othersRef.current.find((p) => p.schoolId === id);
            if (pin) select.current(pin);
          });
          created.on('click', 'school-clusters', (event) => {
            created.easeTo({ center: event.lngLat, zoom: created.getZoom() + 2 });
          });
          created.on('click', 'route-line-alt', (event) => {
            const id = event.features?.[0]?.properties?.id;
            if (typeof id === 'string') {
              onSelectAlternative?.(id === 'primary' ? null : id);
            }
          });
          for (const layer of ['school-points', 'school-clusters', 'route-line-alt']) {
            created.on('mouseenter', layer, () => {
              created.getCanvas().style.cursor = 'pointer';
            });
            created.on('mouseleave', layer, () => {
              created.getCanvas().style.cursor = '';
            });
          }
          for (const start of ['dragstart', 'zoomstart'] as const) {
            created.on(start, (event) => {
              if ('originalEvent' in event && event.originalEvent) moved.current = true;
            });
          }
          created.on('moveend', () => placeLabels(markers.current.map((m) => m.getElement()), frame.current));
          created.on('moveend', () => {
            const b = created.getBounds();
            view.current?.({ lat: b.getSouth(), lng: b.getWest() }, { lat: b.getNorth(), lng: b.getEast() });
          });
        });
        created.on('style.load', setup);
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      resizer?.disconnect();
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      alertMarkers.current.forEach((m) => m.remove());
      alertMarkers.current = [];
      instance?.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Switch between Streets and Satellite imagery.
  const toggleBaseLayer = () => {
    const next = baseLayer === 'streets' ? 'satellite' : 'streets';
    setBaseLayer(next);
    map.current?.setStyle(next === 'satellite' ? SATELLITE_STYLE : MAP_STYLE_STREETS);
  };

  // Sync markers, road-only polyline, alternatives, and hazard markers.
  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance) return;
    let cancelled = false;
    import('maplibre-gl').then(({ Marker, LngLatBounds }) => {
      if (cancelled) return;
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      alertMarkers.current.forEach((m) => m.remove());
      alertMarkers.current = [];

      const bounds = new LngLatBounds();
      const drawn = focus?.point ? [...stops, create(ItineraryStopSchema, { order: 0, school: focus, kind: 'location' })] : stops;
      for (const stop of drawn) {
        const point = stop.school?.point;
        if (!point) continue;
        const el = pinElement(stop);
        el.addEventListener('click', (event) => {
          event.stopPropagation();
          select.current(stop.school!);
        });
        markers.current.push(new Marker({ element: el, anchor: 'bottom' }).setLngLat([point.lng, point.lat]).addTo(instance));
        bounds.extend([point.lng, point.lat]);
      }
      if (pathIsRoad) {
        for (const p of path) bounds.extend([p.lng, p.lat]);
      }
      for (const al of roadAlerts) {
        const el = hazardElement(al);
        alertMarkers.current.push(new Marker({ element: el, anchor: 'center' }).setLngLat([al.lng, al.lat]).addTo(instance));
      }
      if (fitOthers) for (const o of others) if (o.point) bounds.extend([o.point.lng, o.point.lat]);

      (instance.getSource('route-line') as GeoJSONSource | undefined)?.setData(
        roadLineCollection(path, pathIsRoad, alternatives, activeAlternativeId),
      );
      requestAnimationFrame(() => placeLabels(markers.current.map((m) => m.getElement()), frame.current));
      if (!bounds.isEmpty()) {
        extent.current = [bounds.getSouthWest().toArray(), bounds.getNorthEast().toArray()];
        moved.current = false;
        fit(instance, extent.current);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [ready, stops, path, pathIsRoad, alternatives, activeAlternativeId, roadAlerts, focus, fitOthers, others]);

  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance) return;
    (instance.getSource('schools') as GeoJSONSource | undefined)?.setData(othersCollection(others));
  }, [ready, others]);

  // Live GPS user position blue dot.
  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance || !userLocation) return;
    let cancelled = false;
    import('maplibre-gl').then(({ Marker }) => {
      if (cancelled) return;
      here.current?.remove();
      const dot = document.createElement('span');
      dot.className = 'edify-route-here';
      dot.setAttribute('aria-label', 'Current GPS location');
      here.current = new Marker({ element: dot }).setLngLat([userLocation.lng, userLocation.lat]).addTo(instance);
    });
    return () => {
      cancelled = true;
    };
  }, [ready, userLocation]);

  const zoom = (by: number) => map.current?.easeTo({ zoom: (map.current?.getZoom() ?? 9) + by });

  const recenter = () => {
    const instance = map.current;
    if (!instance) return;
    if (extent.current) {
      moved.current = false;
      fit(instance, extent.current);
    }
  };

  const locate = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        const instance = map.current;
        if (!instance) return;
        const { Marker } = await import('maplibre-gl');
        here.current?.remove();
        const dot = document.createElement('span');
        dot.className = 'edify-route-here';
        dot.setAttribute('aria-label', 'You are here');
        here.current = new Marker({ element: dot }).setLngLat([coords.longitude, coords.latitude]).addTo(instance);
        instance.easeTo({ center: [coords.longitude, coords.latitude], zoom: Math.max(instance.getZoom(), 12) });
      },
      () => undefined,
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 },
    );
  };

  const toggleFullscreen = () => {
    if (!frame.current) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      void frame.current.requestFullscreen?.();
    }
  };

  return (
    <div
      ref={frame}
      className={`overflow-hidden ${className ?? 'relative h-full'}`}
      data-block="route-map"
      data-path-is-road={pathIsRoad ? 'true' : 'false'}
      data-map-engine={googleMapsKey ? 'google-maps-ready' : 'maplibre-osm'}
    >
      <div ref={box} className="h-full w-full" />
      {failed ? (
        <div className="absolute inset-0 grid place-items-center bg-[var(--edify-card-surface)] p-6 text-center">
          <div>
            <p className="font-semibold">The map tiles could not load.</p>
            <p className="mt-1 text-[var(--edify-text-muted)]">Your route itinerary, road distances, and turn-by-turn steps remain available.</p>
          </div>
        </div>
      ) : null}

      {/* Top-right Map Controls: Satellite / Traffic / Fullscreen */}
      {showControls ? (
        <div data-map-overlay className="absolute right-3 top-3 flex flex-col items-end gap-2">
          <div className="flex items-center gap-1.5 rounded-[10px] bg-white/95 p-1 shadow-md backdrop-blur">
            <button
              type="button"
              onClick={toggleBaseLayer}
              className={`flex h-8 items-center gap-1.5 rounded-[8px] px-2.5 text-[12px] font-semibold transition-colors ${
                baseLayer === 'satellite' ? 'bg-[var(--brand-primary)] text-white' : 'text-slate-700 hover:bg-slate-100'
              }`}
              aria-pressed={baseLayer === 'satellite'}
            >
              <Layers className="h-3.5 w-3.5" aria-hidden="true" />
              {baseLayer === 'satellite' ? 'Satellite' : 'Map'}
            </button>
            <button
              type="button"
              onClick={() => setShowTraffic((t) => !t)}
              title={
                googleMapsKey
                  ? 'Toggle Google Maps live traffic layer'
                  : 'Live traffic overlay requires Google Maps API key configuration'
              }
              className={`flex h-8 items-center gap-1.5 rounded-[8px] px-2.5 text-[12px] font-semibold transition-colors ${
                showTraffic ? 'bg-amber-600 text-white' : 'text-slate-700 hover:bg-slate-100'
              }`}
              aria-pressed={showTraffic}
            >
              <TrafficCone className="h-3.5 w-3.5" aria-hidden="true" />
              Traffic
            </button>
            <button
              type="button"
              onClick={toggleFullscreen}
              className="grid h-8 w-8 place-items-center rounded-[8px] text-slate-700 hover:bg-slate-100"
              aria-label={isFullscreen ? 'Exit fullscreen map' : 'Fullscreen map'}
            >
              {isFullscreen ? <Minimize className="h-4 w-4" /> : <Expand className="h-4 w-4" />}
            </button>
          </div>
          {showTraffic && !googleMapsKey ? (
            <div className="max-w-[240px] rounded-[10px] border border-amber-200 bg-amber-50/95 px-2.5 py-1.5 text-[11px] font-medium text-amber-900 shadow">
              Live Google traffic layer requires <code className="font-mono">NEXT_PUBLIC_GOOGLE_MAPS_API_KEY</code>. Traffic is never fabricated.
            </div>
          ) : null}
          {showLegend ? (
            <div className="pointer-events-none rounded-[10px] bg-white/95 px-3 py-2 text-[12px] shadow-md" aria-label="Map legend">
              {(
                [
                  ['planned', 'Planned'],
                  ['suggested', 'Suggested'],
                  ['completed', 'Completed'],
                ] as const
              ).map(([tone, label]) => (
                <div key={tone} className="flex items-center gap-2 py-0.5 text-slate-700">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: TONES[tone] }} />
                  {label}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Zoom & Location Controls: bottom-right, or the corner of a small card's map */}
      <div data-map-overlay className={`absolute flex flex-col overflow-hidden rounded-[10px] bg-white shadow-md ${compact ? 'right-2 top-2' : 'bottom-24 right-3'}`}>
        <button type="button" onClick={() => zoom(1)} className={`grid place-items-center text-slate-800 hover:bg-slate-50 ${compact ? 'h-8 w-8' : 'h-10 w-10'}`} aria-label="Zoom in">
          <Plus className="h-4 w-4" />
        </button>
        <span className="h-px bg-slate-200" />
        <button type="button" onClick={() => zoom(-1)} className={`grid place-items-center text-slate-800 hover:bg-slate-50 ${compact ? 'h-8 w-8' : 'h-10 w-10'}`} aria-label="Zoom out">
          <Minus className="h-4 w-4" />
        </button>
        <span className="h-px bg-slate-200" />
        <button type="button" onClick={recenter} className={`grid place-items-center text-slate-800 hover:bg-slate-50 ${compact ? 'h-8 w-8' : 'h-10 w-10'}`} aria-label={compact ? 'Recentre on the school' : 'Fit entire route'}>
          <LocateFixed className="h-4 w-4" />
        </button>
      </div>
      {compact ? null : (
        <button
          type="button"
          onClick={locate}
          data-map-overlay
          className="absolute bottom-10 right-3 grid h-10 w-10 place-items-center rounded-[10px] bg-white text-slate-800 shadow-md hover:bg-slate-50"
          aria-label="Show my location"
        >
          <RouteIcon name="locate" className="h-4 w-4" />
        </button>
      )}

      {/* Bottom-left Route Distance Chip & Alternative Switcher */}
      <div data-map-overlay className="absolute bottom-5 left-3 flex flex-col gap-2">
        {alternatives.length > 0 && onSelectAlternative ? (
          <div className="flex flex-wrap items-center gap-1.5 rounded-[10px] bg-white/95 p-1.5 shadow-md">
            <button
              type="button"
              onClick={() => onSelectAlternative(null)}
              className={`rounded-[7px] px-2.5 py-1 text-[12px] font-semibold ${
                !activeAlternativeId ? 'bg-[var(--brand-primary)] text-white' : 'text-slate-700 hover:bg-slate-100'
              }`}
            >
              Primary Road Route
            </button>
            {alternatives.map((alt, i) => (
              <button
                key={alt.id}
                type="button"
                onClick={() => onSelectAlternative(alt.id)}
                className={`rounded-[7px] px-2.5 py-1 text-[12px] font-semibold ${
                  activeAlternativeId === alt.id ? 'bg-[var(--brand-primary)] text-white' : 'text-slate-700 hover:bg-slate-100'
                }`}
              >
                Alt {i + 1}: {alt.summary || `${(alt.meters / 1000).toFixed(1)} km`}
              </button>
            ))}
          </div>
        ) : null}
        {chip ? (
          <div className="flex items-center gap-2.5 rounded-[12px] bg-white/95 px-3.5 py-2 text-[14px] font-semibold text-slate-800 shadow-md">
            <RouteIcon name="car" className="h-4 w-4 text-[var(--brand-primary)]" />
            <span>{chip}</span>
            {!pathIsRoad && stops.length > 1 ? (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                Road access requires verification
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      <p data-map-overlay className={`absolute rounded-[6px] bg-white/85 px-1.5 py-0.5 text-[10px] text-slate-600 ${compact ? 'bottom-1 right-1 leading-tight' : 'bottom-1 right-16'}`}>
        {baseLayer === 'satellite' ? (
          <span>Tiles © Esri</span>
        ) : compact ? (
          <span>© OpenFreeMap · © OpenStreetMap</span>
        ) : (
          <>
            © <a href="https://openfreemap.org" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> · ©{' '}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>
          </>
        )}
      </p>
    </div>
  );
}
