'use client';

/*
 * The Smart Route Planner (owner design, 2026-11-14): the day's planned
 * schools on a map by their stored coordinates, the recommended order with
 * each leg, the field day's totals, and the eligible schools near the route.
 * Reordering, selecting and optimising only change this view; the official
 * plan changes through the existing Schedule visit drawer (Add to Plan).
 * Save Plan keeps the reader's order for the day on the server, so the
 * planner opens on it on any device; Start Field Day records the day's start,
 * each stop's arrival and departure, and its end (2026-11-16). Neither
 * schedules, moves or completes an activity.
 */
import { create, fromJson, toJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  GetFieldDayResponseSchema,
  GetSchoolDistanceResponseSchema,
  ListLocationChangesResponseSchema,
  GetSchoolPinsResponseSchema,
  PlanRouteRequestSchema,
  PlanRouteResponseSchema,
  RecordFieldDayResponseSchema,
  SaveFieldDayResponseSchema,
} from '@/gen/edify/routes/v1/routes_pb';
import type { GetSchoolDistanceResponse, Itinerary, SavedFieldDay, SchoolPin, Suggestion } from '@/gen/edify/routes/v1/routes_pb';
import { dayClock, directionsUrl, fieldDayState, hoursMinutes, kampalaToday, km, legFigures, placedStops, totalFigures } from '@/lib/routePlanner';

import { RouteMap } from './RouteMap';
import { DayVerdict, KpiRow, NearbyCard, RouteList, RouteSummary, UnplacedNote } from './RouteParts';
import { RouteIcon } from './RouteIcons';

const card = 'rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[0_1px_2px_rgba(15,23,42,0.04)]';

const post = (op: string, request: JsonValue) =>
  fetch('/route-planner', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ op, request }) });

/**
 * Renews an expired session (/auth/refresh sets the new cookies and sends
 * the reader back); false when the reader has to sign in again.
 */
async function renewSession(): Promise<boolean> {
  const answer = await fetch(`/auth/refresh?next=${encodeURIComponent(window.location.pathname)}`, { credentials: 'same-origin' });
  return answer.ok && !new URL(answer.url).pathname.startsWith('/login');
}

async function ask(op: 'plan' | 'pins' | 'distance' | 'changes' | 'save' | 'record', request: JsonValue): Promise<JsonValue> {
  let res = await post(op, request);
  if (res.status === 401) {
    if (!(await renewSession())) throw new Error('Your session has ended. Sign in again to carry on.');
    res = await post(op, request);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(typeof body?.error === 'string' && body.error.length > 3 ? body.error : 'The route could not be worked out.');
  return body;
}

/** How often an open planner checks for location changes. */
const LOCATION_CHANGES_EVERY_MS = 60_000;

export interface RoutePlannerProps {
  day: JsonValue;
  existingWebUrl: string;
  district: string;
  cluster: string;
  /** Find Nearby Schools: the school the suggestions are around. */
  near?: string;
}

export function RoutePlanner({ day: dayJson, existingWebUrl: _existingWebUrl, district, cluster, near = '' }: RoutePlannerProps) {
  void _existingWebUrl;
  const router = useRouter();
  const day = useMemo(() => fromJson(GetFieldDayResponseSchema, dayJson), [dayJson]);
  const [itinerary, setItinerary] = useState<Itinerary | undefined>(day.recommended);
  const [saved, setSaved] = useState<SavedFieldDay | undefined>(day.saved);
  const fieldDay = fieldDayState(saved, day.date, kampalaToday());
  const [view, setView] = useState<'map' | 'list'>('map');
  const [show, setShow] = useState({ planned: true, suggested: true, nearby: false });
  const [nearbyPins, setNearbyPins] = useState<SchoolPin[]>([]);
  const [selected, setSelected] = useState<SchoolPin | null>(null);
  const [pair, setPair] = useState<GetSchoolDistanceResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(day.provider?.message || null);
  const focus = day.focus;
  // Around one school, every nearby school is listed at once.
  const [allNearby, setAllNearby] = useState(Boolean(day.focus));
  // On a phone the filters fold away under their heading; wider, they stay open.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const lastSelected = useRef<SchoolPin | null>(null);
  const viewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // A school's location accepted elsewhere (a capture in the field, a
  // review) refreshes the day, so pins and distances use the new point.
  useEffect(() => {
    const shown = new Set([
      ...day.planned.map((p) => p.schoolId),
      ...day.suggestions.map((s) => s.school?.schoolId ?? ''),
      ...(day.focus ? [day.focus.schoolId] : []),
    ]);
    let since = new Date().toISOString();
    const timer = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      ask('changes', { since })
        .then((json) => {
          const answer = fromJson(ListLocationChangesResponseSchema, json);
          if (answer.now) since = answer.now;
          if (answer.changes.some((c) => shown.has(c.schoolId))) {
            setMessage('A school’s location was updated. The map now uses the new point.');
            router.refresh();
          }
        })
        .catch(() => undefined);
    }, LOCATION_CHANGES_EVERY_MS);
    return () => clearInterval(timer);
  }, [day, router]);

  const go = useCallback(
    (next: Record<string, string>) => {
      const q = new URLSearchParams({ date: day.date, district, cluster, near, ...next });
      for (const [k, v] of [...q.entries()]) if (!v) q.delete(k);
      router.push(`/my-plan/smart-route?${q.toString()}`);
    },
    [router, day.date, district, cluster, near],
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

  // Save Plan: the order on screen, kept on the server for this day.
  const save = async () => {
    setBusy(true);
    try {
      const answer = fromJson(SaveFieldDayResponseSchema, await ask('save', { date: day.date, schoolIds: ids(itinerary) }));
      setSaved(answer.saved);
      setMessage(`Plan saved at ${dayClock(answer.saved?.savedAt ?? '')}. It opens in this order on any device. Your official plan is unchanged; use Add to Plan to schedule a school.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'The plan could not be saved. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  // Start Field Day, a stop's arrival or departure, and the day's end.
  const record = async (event: 'start' | 'arrive' | 'leave' | 'end', schoolId = '') => {
    setBusy(true);
    try {
      const request = { date: day.date, event, schoolId, schoolIds: event === 'start' ? ids(itinerary) : [] };
      const answer = fromJson(RecordFieldDayResponseSchema, await ask('record', request));
      setSaved(answer.saved);
      setMessage(event === 'start' ? `Field day started at ${dayClock(answer.saved?.startedAt ?? '')}. Mark each school as you arrive and leave.` : null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'The field day could not be saved. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const onPick = async (pin: SchoolPin) => {
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
    return `/schools/${encodeURIComponent(pin.code || pin.schoolId)}`;
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
          <RouteIcon name="pin" className="mt-1 h-12 w-12 text-[var(--brand-primary)]" strokeWidth={0} fill="currentColor" />
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
          <FieldDayButtons fieldDay={fieldDay} saved={saved} busy={busy} hasStops={Boolean(itinerary?.stops.length)} onSave={save} onRecord={record} />
        </div>
      </header>

      {focus ? (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-[12px] border border-[var(--brand-primary)]/40 bg-blue-50 px-4 py-3" role="status">
          <p className="text-[15px] text-slate-800">
            <strong>Schools near {focus.name}</strong> (ID {focus.code}):{' '}
            {focus.point
              ? `the eligible schools around it, nearest first, on the map and below.`
              : 'this school has no usable location, so nearby schools cannot be found. It still appears in every list and plan.'}
          </p>
          <button type="button" onClick={() => go({ near: '' })} className="h-10 rounded-[8px] border border-[var(--brand-primary)] px-4 text-[14px] font-semibold text-[var(--brand-primary)]">
            Show my day
          </button>
        </div>
      ) : null}

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
                  className={`flex h-12 items-center justify-center gap-2 rounded-[10px] text-[14px] font-semibold ${view === key ? 'bg-[var(--brand-primary)] text-white' : 'border border-[var(--edify-border)] text-[var(--edify-text)]'}`}
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
                <button type="button" onClick={() => { setShow({ planned: true, suggested: true, nearby: false }); go({ district: '', cluster: '' }); }} className="text-[14px] font-medium text-[var(--brand-primary)]">
                  Clear All
                </button>
              </div>
              <div className={`${filtersOpen ? 'block' : 'hidden'} md:block`}>
              <label className="mt-4 block text-[14px] font-semibold">
                District
                <select value={district} onChange={(e) => go({ district: e.target.value })} className="mt-2 h-12 w-full card px-3 text-[14px] font-normal">
                  <option value="">All Districts</option>
                  {day.districts.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                </select>
              </label>
              <label className="mt-4 block text-[14px] font-semibold">
                Cluster
                <select value={cluster} onChange={(e) => go({ cluster: e.target.value })} className="mt-2 h-12 w-full card px-3 text-[14px] font-normal">
                  <option value="">All Clusters</option>
                  {day.clusters.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </label>
              <fieldset className="mt-4">
                <legend className="text-[14px] font-semibold">Status</legend>
                {(
                  [
                    ['planned', 'Planned', 'accent-[var(--brand-primary)]'],
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
              <RouteMap
                stops={stops}
                path={show.planned ? path : []}
                others={others}
                chip={chip}
                onSelect={onPick}
                onView={onView}
                className="absolute inset-0"
                focus={focus}
                fitOthers={Boolean(focus)}
              />
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
                <RouteIcon name="trophy" className="h-7 w-7 text-amber-500" /> {fieldDay.phase === 'unsaved' ? 'Recommended Route' : 'Your Saved Route'}
              </h2>
              {itinerary?.stops.length ? (
                <span className="flex items-center gap-2 rounded-full bg-green-50 px-3 py-1.5 text-[14px] font-semibold text-green-700">
                  <RouteIcon name="check" className="h-4 w-4 rounded-full bg-green-600 p-0.5 text-white" strokeWidth={3} /> {fieldDay.phase === 'unsaved' ? 'Recommended' : 'Saved'}
                </span>
              ) : null}
            </header>
            <div className="mt-2">
              <RouteList itinerary={itinerary} onFocus={onPick} fieldDay={fieldDay.running || fieldDay.phase === 'ended' ? saved : undefined} running={fieldDay.running} busy={busy} onRecord={record} />
            </div>
            <RouteSummary itinerary={itinerary} />
            <div className="mt-5 grid grid-cols-2 gap-3 px-6">
              <button
                type="button"
                disabled={busy || !itinerary?.stops.length || !fieldDay.canSave}
                onClick={() => plan(ids(itinerary), 'fastest')}
                className="flex h-14 items-center justify-center gap-3 rounded-[12px] border-2 border-[var(--brand-primary)] text-[16px] font-semibold text-[var(--brand-primary)] hover:bg-blue-50 disabled:opacity-50"
              >
                <RouteIcon name="optimize" className="h-6 w-6" /> {busy ? 'Working…' : 'Optimize Route'}
              </button>
              <a
                href={directions ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
                aria-disabled={!directions}
                className={`flex h-14 items-center justify-center gap-3 rounded-[12px] bg-[var(--brand-primary)] text-[16px] font-semibold text-white hover:bg-[var(--brand-primary-hover)] ${directions ? '' : 'pointer-events-none opacity-50'}`}
              >
                <RouteIcon name="navigate" className="h-6 w-6" /> Get Directions
              </a>
            </div>
          </section>
        </aside>

        <NearbyCard
          suggestions={day.suggestions}
          onAdd={addHref}
          onFocus={onPick}
          around={focus}
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
          <button type="button" onClick={onSelectForRoute} className="h-11 rounded-[10px] border border-[var(--brand-primary)] text-[var(--brand-primary)]">
            Select for Route
          </button>
        ) : null}
        {pin.status !== 'planned' && pin.status !== 'completed' ? (
          <a href={addHref} className="flex h-11 items-center justify-center rounded-[10px] border border-[var(--brand-primary)] text-[var(--brand-primary)]">
            Add to Plan
          </a>
        ) : null}
        {directions ? (
          <a href={directions} target="_blank" rel="noopener noreferrer" className="flex h-11 items-center justify-center rounded-[10px] bg-[var(--brand-primary)] text-white">
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


/** Save Plan, Start Field Day and End Field Day, with when each happened. */
function FieldDayButtons({
  fieldDay,
  saved,
  busy,
  hasStops,
  onSave,
  onRecord,
}: {
  fieldDay: ReturnType<typeof fieldDayState>;
  saved: SavedFieldDay | undefined;
  busy: boolean;
  hasStops: boolean;
  onSave: () => void;
  onRecord: (event: 'start' | 'end') => void;
}) {
  const quiet = 'flex h-14 items-center gap-3 rounded-[12px] border-2 border-[var(--brand-primary)] px-5 text-[16px] font-semibold text-[var(--brand-primary)] hover:bg-blue-50 disabled:opacity-50';
  const solid = 'flex h-14 items-center gap-3 rounded-[12px] bg-[var(--brand-primary)] px-6 text-[16px] font-semibold text-white hover:bg-[var(--brand-primary-hover)] disabled:opacity-50';
  if (fieldDay.phase === 'ended') {
    return (
      <span className="flex h-14 items-center gap-2 rounded-[12px] bg-green-50 px-5 text-[15px] font-semibold text-green-700" role="status">
        <RouteIcon name="check" className="h-5 w-5" /> Field day ended {dayClock(saved?.endedAt ?? '')}
      </span>
    );
  }
  if (fieldDay.running) {
    return (
      <>
        <span className="flex h-14 items-center gap-2 rounded-[12px] bg-green-50 px-5 text-[15px] font-semibold text-green-700" role="status">
          <span className="h-2.5 w-2.5 rounded-full bg-green-600" aria-hidden="true" /> Field day started {dayClock(saved?.startedAt ?? '')}
        </span>
        <button type="button" disabled={busy} onClick={() => onRecord('end')} className={solid}>
          <RouteIcon name="check" className="h-6 w-6" /> End Field Day
        </button>
      </>
    );
  }
  return (
    <>
      {fieldDay.phase === 'saved' ? (
        <span className="text-[14px] font-medium text-[var(--edify-text-muted)]" role="status">
          Saved {dayClock(saved?.savedAt ?? '')}
        </span>
      ) : null}
      <button type="button" disabled={busy || !hasStops} onClick={onSave} className={fieldDay.canStart ? quiet : solid}>
        <RouteIcon name="save" className="h-6 w-6" /> Save Plan
      </button>
      {fieldDay.canStart ? (
        <button type="button" disabled={busy || !hasStops} onClick={() => onRecord('start')} className={solid}>
          <RouteIcon name="navigate" className="h-6 w-6" /> Start Field Day
        </button>
      ) : null}
    </>
  );
}
