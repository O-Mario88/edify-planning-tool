'use client';

/*
 * The Route Planner's map: OpenFreeMap tiles through MapLibre (no key, no
 * account). The day's stops are numbered pins with their names beside them;
 * other schools are a label layer MapLibre keeps apart (overlapping names
 * are hidden, dense pins cluster), with every school's full name one tap
 * away. The road line is the provider's; with no road figure the stops are
 * joined by a dashed straight line, so a straight line never looks like a
 * road.
 */
import 'maplibre-gl/dist/maplibre-gl.css';

import type { FeatureCollection } from 'geojson';
import type { GeoJSONSource, Map as MapLibreMap, Marker as MapLibreMarker } from 'maplibre-gl';
import { useEffect, useRef, useState } from 'react';

import type { ItineraryStop, SchoolPin } from '@/gen/edify/routes/v1/routes_pb';
import { pinTone } from '@/lib/routePlanner';

import { RouteIcon } from './RouteIcons';

/** Keyless vector tiles (openfreemap.org). */
export const MAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty';

/** MapLibre's worker, served by this app (app/maplibre-worker.mjs). */
const WORKER_URL = '/maplibre-worker.mjs';

const UGANDA_CENTRE: [number, number] = [32.58, 0.35];

export const TONES = {
  planned: '#1d6fe0',
  suggested: '#16a34a',
  completed: '#15803d',
  other: '#94a3b8',
} as const;

export interface RouteMapProps {
  stops: readonly ItineraryStop[];
  /** The road line, when the provider returned one. */
  path: readonly { lat: number; lng: number }[];
  /** Schools that are not stops (nearby, when asked for). */
  others: readonly SchoolPin[];
  chip: string | null;
  onSelect: (pin: SchoolPin) => void;
  /** The viewport, when the reader moves the map (for nearby schools). */
  onView?: (sw: { lat: number; lng: number }, ne: { lat: number; lng: number }) => void;
  /** Positions the map (absolute inset-0 inside a sized box); relative by default. */
  className?: string;
}

function pinElement(stop: ItineraryStop): HTMLElement {
  const school = stop.school!;
  const tone = pinTone(school, stop.kind);
  const root = document.createElement('button');
  root.type = 'button';
  root.className = 'edify-route-pin';
  root.setAttribute('aria-label', `Stop ${stop.order}: ${school.name}`);
  const drop = document.createElement('span');
  drop.className = 'edify-route-pin__drop';
  drop.style.background = TONES[tone];
  const number = document.createElement('span');
  number.className = 'edify-route-pin__number';
  number.textContent = String(stop.order);
  drop.append(number);
  const label = document.createElement('span');
  label.className = 'edify-route-pin__label';
  label.textContent = school.name;
  root.append(drop, label);
  return root;
}

const overlaps = (a: DOMRect, b: DOMRect) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

/**
 * Names never cover each other or a pin: each stop's name goes right of its
 * pin, else left, below or above, else it is hidden (the full name shows on hover and when
 * the school is opened). Earlier stops choose first.
 */
export function placeLabels(pins: readonly HTMLElement[], frame: HTMLElement | null) {
  const drops = pins.map((p) => p.querySelector('.edify-route-pin__drop')!.getBoundingClientRect());
  // The map's own overlays (legend, zoom, distance chip) are in the way too.
  const labels: DOMRect[] = frame ? [...frame.querySelectorAll('[data-map-overlay]')].map((o) => o.getBoundingClientRect()) : [];
  const bounds = frame?.getBoundingClientRect();
  const inside = (box: DOMRect) => !bounds || (box.left >= bounds.left + 4 && box.right <= bounds.right - 4 && box.top >= bounds.top + 4 && box.bottom <= bounds.bottom - 4);
  pins.forEach((pin, i) => {
    const label = pin.querySelector<HTMLElement>('.edify-route-pin__label');
    if (!label) return;
    // Another stop's pin, or a name already placed (a pin's own drop is not in the way).
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

function lineCollection(stops: readonly ItineraryStop[], path: RouteMapProps['path']): FeatureCollection {
  const road = path.length > 1;
  const coords = road
    ? path.map((p) => [p.lng, p.lat])
    : stops.filter((s) => s.school?.point).map((s) => [s.school!.point!.lng, s.school!.point!.lat]);
  if (coords.length < 2) return { type: 'FeatureCollection', features: [] };
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: { road }, geometry: { type: 'LineString', coordinates: coords } }],
  };
}

function fit(instance: MapLibreMap, extent: [[number, number], [number, number]]) {
  const { width, height } = instance.getContainer().getBoundingClientRect();
  if (width < 50 || height < 50) return;
  const pad = Math.min(80, Math.round(Math.min(width, height) / 6));
  instance.fitBounds(extent, { padding: { top: pad, bottom: pad, left: pad, right: Math.min(pad * 2, width / 3) }, maxZoom: 14, duration: 0 });
}

export function RouteMap({ stops, path, others, chip, onSelect, onView, className }: RouteMapProps) {
  const box = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef<MapLibreMarker[]>([]);
  const here = useRef<MapLibreMarker | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const select = useRef(onSelect);
  const view = useRef(onView);
  const othersRef = useRef(others);
  // The stops' extent, refitted while the reader has not moved the map.
  const extent = useRef<[[number, number], [number, number]] | null>(null);
  const moved = useRef(false);
  useEffect(() => {
    select.current = onSelect;
    view.current = onView;
    othersRef.current = others;
  });

  // The map library loads only when the map is shown.
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
          style: MAP_STYLE,
          center: UGANDA_CENTRE,
          zoom: 9,
          attributionControl: { compact: true },
        });
        instance = created;
        map.current = created;
        // The map follows its box (it is drawn before the page settles).
        resizer = new ResizeObserver(() => {
          created.resize();
          if (!moved.current && extent.current) fit(created, extent.current);
        });
        resizer.observe(box.current);
        created.on('error', (event) => {
          if (!created.isStyleLoaded()) setFailed(/style|fetch|network|load/i.test(String(event.error?.message ?? '')));
        });
        created.on('load', () => {
          if (cancelled) return;
          created.addSource('route-line', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
          created.addLayer({
            id: 'route-line-casing',
            type: 'line',
            source: 'route-line',
            paint: { 'line-color': '#ffffff', 'line-width': 9, 'line-opacity': 0.9 },
            layout: { 'line-join': 'round', 'line-cap': 'round' },
          });
          created.addLayer({
            id: 'route-line',
            type: 'line',
            source: 'route-line',
            filter: ['==', ['get', 'road'], true],
            paint: { 'line-color': '#1d6fe0', 'line-width': 5 },
            layout: { 'line-join': 'round', 'line-cap': 'round' },
          });
          created.addLayer({
            id: 'route-line-straight',
            type: 'line',
            source: 'route-line',
            filter: ['==', ['get', 'road'], false],
            paint: { 'line-color': '#1d6fe0', 'line-width': 4, 'line-dasharray': [1.5, 1.5] },
            layout: { 'line-join': 'round', 'line-cap': 'round' },
          });
          created.addSource('schools', {
            type: 'geojson',
            data: othersCollection(othersRef.current),
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
          created.addLayer({
            id: 'school-names',
            type: 'symbol',
            source: 'schools',
            filter: ['!', ['has', 'point_count']],
            minzoom: 11,
            layout: {
              'text-field': ['get', 'name'],
              'text-size': 12,
              'text-font': ['Noto Sans Regular'],
              'text-offset': [0.9, 0],
              'text-anchor': 'left',
              'text-max-width': 12,
            },
            paint: { 'text-color': '#1f2937', 'text-halo-color': '#ffffff', 'text-halo-width': 1.6 },
          });
          created.on('click', 'school-points', (event) => {
            const id = event.features?.[0]?.properties?.id;
            const pin = othersRef.current.find((p) => p.schoolId === id);
            if (pin) select.current(pin);
          });
          created.on('click', 'school-clusters', (event) => {
            created.easeTo({ center: event.lngLat, zoom: created.getZoom() + 2 });
          });
          for (const layer of ['school-points', 'school-clusters']) {
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
          setReady(true);
        });
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      resizer?.disconnect();
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      instance?.remove();
      map.current = null;
    };
  }, []);

  // The stops, their line, and the view fitted to them.
  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance) return;
    let cancelled = false;
    import('maplibre-gl').then(({ Marker, LngLatBounds }) => {
      if (cancelled) return;
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      const bounds = new LngLatBounds();
      for (const stop of stops) {
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
      (instance.getSource('route-line') as GeoJSONSource | undefined)?.setData(lineCollection(stops, path));
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
  }, [ready, stops, path]);

  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance) return;
    (instance.getSource('schools') as GeoJSONSource | undefined)?.setData(othersCollection(others));
  }, [ready, others]);

  const zoom = (by: number) => map.current?.easeTo({ zoom: (map.current?.getZoom() ?? 9) + by });

  // The device's location only when the reader asks for it, once.
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

  return (
    <div ref={frame} className={`overflow-hidden ${className ?? 'relative h-full'}`} data-block="route-map">
      <div ref={box} className="h-full w-full" />
      {failed ? (
        <div className="absolute inset-0 grid place-items-center bg-[var(--edify-card-surface)] p-6 text-center">
          <div>
            <p className="font-semibold">The map could not load.</p>
            <p className="mt-1 text-[var(--edify-text-muted)]">Your route is in List View, with every distance and time.</p>
          </div>
        </div>
      ) : null}
      <div data-map-overlay className="pointer-events-none absolute right-3 top-3 rounded-[12px] bg-white/95 px-4 py-3 text-[14px] shadow-md" aria-label="Map legend">
        {(
          [
            ['planned', 'Planned'],
            ['suggested', 'Suggested'],
            ['other', 'Other'],
          ] as const
        ).map(([tone, label]) => (
          <div key={tone} className="flex items-center gap-2.5 py-0.5 text-slate-700">
            <span className="h-3.5 w-3.5 rounded-full" style={{ background: TONES[tone] }} />
            {label}
          </div>
        ))}
      </div>
      <div data-map-overlay className="absolute bottom-24 right-3 flex flex-col overflow-hidden rounded-[10px] bg-white shadow-md">
        <button type="button" onClick={() => zoom(1)} className="grid h-11 w-11 place-items-center text-slate-800 hover:bg-slate-50" aria-label="Zoom in">
          <RouteIcon name="plus" className="h-5 w-5" />
        </button>
        <span className="h-px bg-slate-200" />
        <button type="button" onClick={() => zoom(-1)} className="grid h-11 w-11 place-items-center text-slate-800 hover:bg-slate-50" aria-label="Zoom out">
          <RouteIcon name="minus" className="h-5 w-5" />
        </button>
      </div>
      <button
        type="button"
        onClick={locate}
        data-map-overlay
        className="absolute bottom-8 right-3 grid h-11 w-11 place-items-center rounded-[10px] bg-white text-slate-800 shadow-md hover:bg-slate-50"
        aria-label="Show my location"
      >
        <RouteIcon name="locate" className="h-5 w-5" />
      </button>
      {chip ? (
        <div data-map-overlay className="absolute bottom-6 left-4 flex items-center gap-3 rounded-[12px] bg-white px-4 py-2.5 text-[15px] font-semibold text-slate-800 shadow-md">
          <RouteIcon name="car" className="h-5 w-5" />
          {chip}
        </div>
      ) : null}
    </div>
  );
}
