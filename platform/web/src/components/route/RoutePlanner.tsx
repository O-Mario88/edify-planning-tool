'use client';

/*
 * The Smart Route Planner (owner design, 2026-11-14): the day's planned
 * schools on a map by their stored coordinates, the recommended order with
 * each leg, the field day's totals, and the eligible schools near the route.
 * Reordering, selecting and optimising only change this view; the official
 * plan changes through the existing Schedule visit drawer (Add to Plan).
 */
import { create, fromJson, toJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  GetFieldDayResponseSchema,
  GetSchoolDistanceResponseSchema,
  GetSchoolPinsResponseSchema,
  PlanRouteRequestSchema,
  PlanRouteResponseSchema,
} from '@/gen/edify/routes/v1/routes_pb';
import type { GetSchoolDistanceResponse, Itinerary, SchoolPin, Suggestion } from '@/gen/edify/routes/v1/routes_pb';
import { directionsUrl, hoursMinutes, km, legFigures, placedStops, totalFigures } from '@/lib/routePlanner';

import { RouteMap } from './RouteMap';
import { DayVerdict, KpiRow, NearbyCard, RouteList, RouteSummary, UnplacedNote } from './RouteParts';
import { RouteIcon } from './RouteIcons';

const card = 'rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[0_1px_2px_rgba(15,23,42,0.04)]';

async function ask(op: 'plan' | 'pins' | 'distance', request: JsonValue): Promise<JsonValue> {
  const res = await fetch('/route-planner', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op, request }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(typeof body?.error === 'string' && body.error.length > 3 ? body.error : 'The route could not be worked out.');
  return body;
}

const savedKey = (date: string) => `edify.route.${date}`;

export interface RoutePlannerProps {
  day: JsonValue;
  existingWebUrl: string;
  district: string;
  cluster: string;
}

export function RoutePlanner({ day: dayJson, existingWebUrl, district, cluster }: RoutePlannerProps) {
  const router = useRouter();
  const day = useMemo(() => fromJson(GetFieldDayResponseSchema, dayJson), [dayJson]);
  const [itinerary, setItinerary] = useState<Itinerary | undefined>(day.recommended);
  const [view, setView] = useState<'map' | 'list'>('map');
  const [show, setShow] = useState({ planned: true, suggested: true, nearby: false });
  const [nearbyPins, setNearbyPins] = useState<SchoolPin[]>([]);
  const [selected, setSelected] = useState<SchoolPin | null>(null);
  const [pair, setPair] = useState<GetSchoolDistanceResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(day.provider?.message || null);
  const [allNearby, setAllNearby] = useState(false);
  // On a phone the filters fold away under their heading; wider, they stay open.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const lastSelected = useRef<SchoolPin | null>(null);
  const viewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const go = useCallback(
    (next: Record<string, string>) => {
      const q = new URLSearchParams({ date: day.date, district, cluster, ...next });
      for (const [k, v] of [...q.entries()]) if (!v) q.delete(k);
      router.push(`/my-plan/smart-route?${q.toString()}`);
    },
    [router, day.date, district, cluster],
  );

  const plan = useCallback(
    async (ids: string[], mode: 'fastest' | 'as_given') => {
      if (ids.length === 0) return;
      setBusy(true);
      try {
        const answer = fromJson(
          PlanRouteResponseSchema,
          await ask('plan', toJson(PlanRouteRequestSchema, create(PlanRouteRequestSchema, { date: day.date, schoolIds: ids, mode }))),
        );
        setItinerary(answer.itinerary);
        setMessage(answer.provider?.message || null);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : 'The route could not be worked out.');
      } finally {
        setBusy(false);
      }
    },
    [day.date],
  );

  const ids = (it: Itinerary | undefined) => (it?.stops ?? []).map((s) => s.school!.schoolId).concat((it?.unplaced ?? []).map((p) => p.schoolId));

  // A route order this reader saved for the day comes back when they return.
  useEffect(() => {
    let saved: unknown = null;
    try {
      saved = JSON.parse(window.localStorage.getItem(savedKey(day.date)) ?? 'null');
    } catch {
      return undefined; // no saved order on this device
    }
    const current = ids(day.recommended);
    if (!Array.isArray(saved) || saved.length !== current.length || !saved.every((id) => current.includes(id)) || saved.join() === current.join()) {
      return undefined;
    }
    const order = saved as string[];
    const timer = setTimeout(() => void plan(order, 'as_given'), 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day]);

  const save = () => {
    try {
      window.localStorage.setItem(savedKey(day.date), JSON.stringify(ids(itinerary)));
      setMessage('Route order saved on this device. Your official plan is unchanged; use Add to Plan to schedule a school.');
    } catch {
      setMessage('This browser could not save the route order.');
    }
  };

  const focus = async (pin: SchoolPin) => {
    setSelected(pin);
    setPair(null);
    const previous = lastSelected.current;
    lastSelected.current = pin;
    if (previous && previous.schoolId !== pin.schoolId) {
      try {
        const answer = fromJson(GetSchoolDistanceResponseSchema, await ask('distance', { fromSchoolId: previous.schoolId, toSchoolId: pin.schoolId }));
        setPair(answer);
      } catch {
        setPair(null);
      }
    }
  };

  const onView = useCallback(
    (sw: { lat: number; lng: number }, ne: { lat: number; lng: number }) => {
      if (!show.nearby) return;
      if (viewTimer.current) clearTimeout(viewTimer.current);
      viewTimer.current = setTimeout(async () => {
        try {
          const answer = fromJson(
            GetSchoolPinsResponseSchema,
            await ask('pins', { southWest: sw, northEast: ne, date: day.date, districtId: district, clusterId: cluster }),
          );
          setNearbyPins(answer.pins);
        } catch {
          setNearbyPins([]);
        }
      }, 350);
    },
    [show.nearby, day.date, district, cluster],
  );

  const stops = useMemo(
    () => (itinerary?.stops ?? []).filter((s) => (s.kind === 'recommended' ? show.suggested : show.planned)),
    [itinerary, show.planned, show.suggested],
  );
  const path = useMemo(() => (itinerary?.stops[0]?.leg?.path ?? []).map((p) => ({ lat: p.lat, lng: p.lng })), [itinerary]);
  const stopIds = new Set((itinerary?.stops ?? []).map((s) => s.school?.schoolId ?? ''));
  const others = useMemo(() => {
    const suggested = show.suggested ? day.suggestions.map((s) => s.school!).filter((p) => !stopIds.has(p.schoolId)) : [];
    const near = show.nearby ? nearbyPins.filter((p) => !stopIds.has(p.schoolId)) : [];
    const seen = new Set<string>();
    return [...suggested, ...near].filter((p) => (seen.has(p.schoolId) ? false : (seen.add(p.schoolId), true)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day.suggestions, nearbyPins, show.suggested, show.nearby, itinerary]);

  const total = totalFigures(itinerary?.totals);
  const chip = itinerary?.stops.length ? `${km(total.meters)}  |  ${hoursMinutes(total.seconds)}` : null;
  const directions = directionsUrl(placedStops(itinerary));
  const addHref = (s: Suggestion | SchoolPin) => {
    const pin = s.$typeName === 'edify.routes.v1.Suggestion' ? s.school! : s;
    return `${existingWebUrl}/schools/${encodeURIComponent(pin.code || pin.schoolId)}`;
  };

  const move = (index: number, by: number) => {
    const order = ids(itinerary);
    const to = index + by;
    if (to < 0 || to >= (itinerary?.stops.length ?? 0)) return;
    const here = order[index]!;
    order[index] = order[to]!;
    order[to] = here;
    void plan(order, 'as_given');
  };

  return (
    <div className="mx-auto max-w-[1680px] px-4 pb-10 pt-4 sm:px-6" data-page="smart-route">
      <nav className="flex items-center gap-3 text-[15px]" aria-label="Breadcrumb">
        <Link href="/my-plan" className="text-[var(--edify-text-muted)] hover:underline">My Plan</Link>
        <RouteIcon name="arrowRight" className="h-4 w-4 text-slate-400" />
        <span className="font-semibold text-[var(--edify-text)]">Smart Route Planner</span>
      </nav>

      <header className="mt-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <RouteIcon name="pin" className="mt-1 h-12 w-12 text-[#1d6fe0]" strokeWidth={0} fill="currentColor" />
          <div>
            <h1 className="text-[22px] font-bold leading-tight text-[var(--edify-text)] sm:text-[28px]">Smart Route Planner</h1>
            <p className="mt-1 text-[16px] text-[var(--edify-text-muted)]">Optimise your field visits with the most efficient route</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="relative flex h-14 items-center gap-3 rounded-[12px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-5 text-[16px] font-medium">
            <RouteIcon name="calendar" className="h-6 w-6" />
            <span>{day.dateLabel}</span>
            <RouteIcon name="chevronDown" className="h-5 w-5" />
            <input
              type="date"
              value={day.date}
              onChange={(e) => e.target.value && go({ date: e.target.value })}
              className="absolute inset-0 cursor-pointer opacity-0"
              aria-label="Field day date"
            />
          </label>
          <button type="button" onClick={save} className="flex h-14 items-center gap-3 rounded-[12px] bg-[#1d6fe0] px-6 text-[16px] font-semibold text-white hover:bg-[#1760c4]">
            <RouteIcon name="save" className="h-6 w-6" /> Save Plan
          </button>
        </div>
      </header>

      <div className="mt-6">
        <KpiRow itinerary={itinerary} />
      </div>

      {message ? (
        <p className="mt-4 rounded-[12px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-4 py-3 text-[14px]" role="status">
          {message}
        </p>
      ) : null}
      <div className="mt-4">
        <UnplacedNote itinerary={itinerary} />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,460px)]">
        <section className={`${card} grid min-h-[600px] grid-cols-1 overflow-hidden md:grid-cols-[230px_minmax(0,1fr)]`} aria-label="Route map">
          <div className="flex flex-col gap-4 border-b border-[var(--edify-border)] p-4 md:border-b-0 md:border-r">
            <div className="grid grid-cols-2 gap-2" role="tablist" aria-label="Map or list">
              {(
                [
                  ['map', 'Map View', 'map'],
                  ['list', 'List View', 'list'],
                ] as const
              ).map(([key, label, icon]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={view === key}
                  onClick={() => setView(key)}
                  className={`flex h-12 items-center justify-center gap-2 rounded-[10px] text-[14px] font-semibold ${view === key ? 'bg-[#1d6fe0] text-white' : 'border border-[var(--edify-border)] text-[var(--edify-text)]'}`}
                >
                  <RouteIcon name={icon} className="h-5 w-5" /> {label}
                </button>
              ))}
            </div>
            <div className="rounded-[12px] border border-[var(--edify-border)] p-4">
              <div className="flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setFiltersOpen(!filtersOpen)}
                  aria-expanded={filtersOpen}
                  className="flex items-center gap-2 text-[16px] font-semibold md:pointer-events-none"
                >
                  <RouteIcon name="filter" className="h-5 w-5" /> Filters
                  <RouteIcon name="chevronDown" className={`h-4 w-4 md:hidden ${filtersOpen ? 'rotate-180' : ''}`} />
                </button>
                <button type="button" onClick={() => { setShow({ planned: true, suggested: true, nearby: false }); go({ district: '', cluster: '' }); }} className="text-[14px] font-medium text-[#1d6fe0]">
                  Clear All
                </button>
              </div>
              <div className={`${filtersOpen ? 'block' : 'hidden'} md:block`}>
              <label className="mt-4 block text-[14px] font-semibold">
                District
                <select value={district} onChange={(e) => go({ district: e.target.value })} className="mt-2 h-12 w-full rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-3 text-[14px] font-normal">
                  <option value="">All Districts</option>
                  {day.districts.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                </select>
              </label>
              <label className="mt-4 block text-[14px] font-semibold">
                Cluster
                <select value={cluster} onChange={(e) => go({ cluster: e.target.value })} className="mt-2 h-12 w-full rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-3 text-[14px] font-normal">
                  <option value="">All Clusters</option>
                  {day.clusters.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </label>
              <fieldset className="mt-4">
                <legend className="text-[14px] font-semibold">Status</legend>
                {(
                  [
                    ['planned', 'Planned', 'accent-[#1d6fe0]'],
                    ['suggested', 'Suggested', 'accent-sky-600'],
                    ['nearby', 'Nearby', 'accent-slate-500'],
                  ] as const
                ).map(([key, label, accent]) => (
                  <label key={key} className="mt-2.5 flex items-center gap-3 text-[15px]">
                    <input type="checkbox" checked={show[key]} onChange={(e) => setShow({ ...show, [key]: e.target.checked })} className={`h-6 w-6 ${accent}`} />
                    {label}
                  </label>
                ))}
              </fieldset>
              </div>
            </div>
          </div>
          {view === 'map' ? (
            <div className="relative min-h-[440px] md:min-h-[520px]">
              <RouteMap stops={stops} path={show.planned ? path : []} others={others} chip={chip} onSelect={focus} onView={onView} className="absolute inset-0" />
              {selected ? (
                <SchoolPanel
                  pin={selected}
                  pair={pair}
                  onClose={() => setSelected(null)}
                  onSelectForRoute={() => {
                    void plan([...ids(itinerary).filter((id) => id !== selected.schoolId), selected.schoolId], 'fastest');
                    setSelected(null);
                  }}
                  inRoute={stopIds.has(selected.schoolId)}
                  addHref={addHref(selected)}
                />
              ) : null}
            </div>
          ) : (
            <ListView itinerary={itinerary} onMove={move} busy={busy} />
          )}
        </section>

        <aside className="flex flex-col gap-5">
          <section className={`${card} pb-5`} aria-labelledby="recommended-title">
            <header className="flex items-center justify-between px-6 pt-5">
              <h2 id="recommended-title" className="flex items-center gap-3 sm:whitespace-nowrap text-[20px] font-semibold text-[var(--edify-text)]">
                <RouteIcon name="trophy" className="h-7 w-7 text-amber-500" /> Recommended Route
              </h2>
              {itinerary?.stops.length ? (
                <span className="flex items-center gap-2 rounded-full bg-green-50 px-3 py-1.5 text-[14px] font-semibold text-green-700">
                  <RouteIcon name="check" className="h-4 w-4 rounded-full bg-green-600 p-0.5 text-white" strokeWidth={3} /> Recommended
                </span>
              ) : null}
            </header>
            <div className="mt-2">
              <RouteList itinerary={itinerary} onFocus={focus} />
            </div>
            <RouteSummary itinerary={itinerary} />
            <div className="mt-5 grid grid-cols-2 gap-3 px-6">
              <button
                type="button"
                disabled={busy || !itinerary?.stops.length}
                onClick={() => plan(ids(itinerary), 'fastest')}
                className="flex h-14 items-center justify-center gap-3 rounded-[12px] border-2 border-[#1d6fe0] text-[16px] font-semibold text-[#1d6fe0] hover:bg-blue-50 disabled:opacity-50"
              >
                <RouteIcon name="optimize" className="h-6 w-6" /> {busy ? 'Working…' : 'Optimize Route'}
              </button>
              <a
                href={directions ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
                aria-disabled={!directions}
                className={`flex h-14 items-center justify-center gap-3 rounded-[12px] bg-[#1d6fe0] text-[16px] font-semibold text-white hover:bg-[#1760c4] ${directions ? '' : 'pointer-events-none opacity-50'}`}
              >
                <RouteIcon name="navigate" className="h-6 w-6" /> Get Directions
              </a>
            </div>
          </section>
        </aside>

        <NearbyCard
          suggestions={day.suggestions}
          onAdd={addHref}
          onFocus={focus}
          onViewAll={() => setAllNearby(!allNearby)}
          showAll={allNearby}
          inRoute={stopIds}
        />
        <div className="self-start">
          <DayVerdict itinerary={itinerary} />
        </div>
      </div>
    </div>
  );
}

function SchoolPanel({
  pin,
  pair,
  onClose,
  onSelectForRoute,
  inRoute,
  addHref,
}: {
  pin: SchoolPin;
  pair: GetSchoolDistanceResponse | null;
  onClose: () => void;
  onSelectForRoute: () => void;
  inRoute: boolean;
  addHref: string;
}) {
  const directions = directionsUrl([pin]);
  const leg = legFigures(pair?.leg);
  return (
    <div className="absolute left-3 top-3 z-10 w-[min(360px,calc(100%-24px))] rounded-[14px] bg-white p-4 shadow-xl" role="dialog" aria-label={pin.name}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[16px] font-semibold leading-snug text-slate-900">{pin.name}</p>
          <p className="mt-0.5 text-[14px] text-slate-500">
            ID {pin.code} · {pin.district || 'District not set'}
            {pin.cluster ? ` · ${pin.cluster}` : ''}
          </p>
          <p className="mt-1 text-[13px] text-slate-500">
            {pin.category} · {pin.status === 'other' ? 'Not planned' : pin.status.charAt(0).toUpperCase() + pin.status.slice(1)} ·{' '}
            {pin.locationStatus === 'verified' ? 'Verified location' : 'Directory location (not verified)'}
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-slate-500" aria-label="Close">
          ✕
        </button>
      </div>
      {pair && leg ? (
        <p className="mt-3 rounded-[10px] bg-slate-50 px-3 py-2 text-[14px] text-slate-700">
          From {pair.from?.name}: {pair.leg?.roadAvailable ? `${km(leg.meters)} by road • ${hoursMinutes(leg.seconds)}` : `${km(leg.meters)} straight line (road distance unavailable)`}
        </p>
      ) : null}
      <div className="mt-3 grid grid-cols-2 gap-2 text-[14px] font-semibold">
        {pin.canOpenProfile ? (
          <a href={`/schools/${encodeURIComponent(pin.schoolId)}`} className="flex h-11 items-center justify-center rounded-[10px] border border-slate-300">
            View School
          </a>
        ) : null}
        {!inRoute ? (
          <button type="button" onClick={onSelectForRoute} className="h-11 rounded-[10px] border border-[#1d6fe0] text-[#1d6fe0]">
            Select for Route
          </button>
        ) : null}
        {pin.status !== 'planned' && pin.status !== 'completed' ? (
          <a href={addHref} className="flex h-11 items-center justify-center rounded-[10px] border border-[#1d6fe0] text-[#1d6fe0]">
            Add to Plan
          </a>
        ) : null}
        {directions ? (
          <a href={directions} target="_blank" rel="noopener noreferrer" className="flex h-11 items-center justify-center rounded-[10px] bg-[#1d6fe0] text-white">
            Get Directions
          </a>
        ) : null}
      </div>
    </div>
  );
}

function ListView({ itinerary, onMove, busy }: { itinerary: Itinerary | undefined; onMove: (index: number, by: number) => void; busy: boolean }) {
  const stops = itinerary?.stops ?? [];
  return (
    <div className="overflow-x-auto p-4">
      <table className="w-full text-left text-[14px]">
        <caption className="sr-only">The day&apos;s visits in order</caption>
        <thead className="text-[13px] uppercase tracking-wide text-[var(--edify-text-muted)]">
          <tr>
            <th className="py-2 pr-3">#</th>
            <th className="py-2 pr-3">School</th>
            <th className="py-2 pr-3">From previous</th>
            <th className="py-2 pr-3">Arrive</th>
            <th className="py-2 pr-3">Leave</th>
            <th className="py-2">Order</th>
          </tr>
        </thead>
        <tbody>
          {stops.map((s, i) => {
            const f = legFigures(s.leg);
            return (
              <tr key={s.school?.schoolId} className="border-t border-[var(--edify-border)]">
                <td className="py-3 pr-3 font-semibold">{s.order}</td>
                <td className="py-3 pr-3">
                  <span className="font-semibold">{s.school?.name}</span>
                  <span className="block text-[13px] text-[var(--edify-text-muted)]">
                    ID {s.school?.code} · {s.kind === 'recommended' ? 'Suggested' : 'Planned'} · {s.visitMinutes} min visit
                  </span>
                  {s.conflict ? <span className="block text-[13px] text-[var(--edify-danger-text)]">{s.conflict}</span> : null}
                </td>
                <td className="py-3 pr-3">{f ? `${km(f.meters)} • ${hoursMinutes(f.seconds)}${f.measure === 'road' ? '' : ' (straight line)'}` : 'First stop'}</td>
                <td className="py-3 pr-3">{s.arrival}</td>
                <td className="py-3 pr-3">{s.departure}</td>
                <td className="py-3">
                  <span className="flex gap-1">
                    <button type="button" disabled={busy || i === 0} onClick={() => onMove(i, -1)} className="h-9 w-9 rounded-[8px] border border-[var(--edify-border)] disabled:opacity-40" aria-label={`Move ${s.school?.name} earlier`}>
                      ↑
                    </button>
                    <button type="button" disabled={busy || i === stops.length - 1} onClick={() => onMove(i, 1)} className="h-9 w-9 rounded-[8px] border border-[var(--edify-border)] disabled:opacity-40" aria-label={`Move ${s.school?.name} later`}>
                      ↓
                    </button>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {stops.length === 0 ? <p className="py-6 text-center text-[var(--edify-text-muted)]">No school visits are planned on this day.</p> : null}
      <p className="mt-3 text-[13px] text-[var(--edify-text-muted)]">Moving a visit changes this route only; the official plan changes through the Schedule visit drawer.</p>
    </div>
  );
}

