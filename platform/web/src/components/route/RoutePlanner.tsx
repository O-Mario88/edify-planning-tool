'use client';

/*
 * Enterprise Smart Route Planner & In-App Navigation Workspace (Sections 1–14):
 * - 3-panel collapsible desktop layout (Left: Configuration, Center: Dominant
 *   Road Map, Right: Recommended Itinerary & In-App Turn-by-Turn Navigation).
 * - Map-first mobile layout with accessible bottom-sheet summary.
 * - Real road-based routing & 5-mode optimization (Balanced, Fastest, Shortest,
 *   Maximum Schools, Priority Schools) with verified SSA priority integration.
 * - 100% in-app Get Directions (ZERO external Google Maps / Apple Maps / Waze
 *   redirects anywhere).
 * - Chevron-free, full-field clickable EdifyDatePicker with Uganda FY2027 &
 *   backend-enforced Sunday/holiday/leave scheduling policies.
 * - Staff road-condition reporting with explicit unverified vs verified labeling.
 */
import { create, fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Bike,
  Car,
  CheckCircle2,
  ChevronRight,
  Crown,
  Flag,
  List as ListIcon,
  LocateFixed,
  Lock,
  Map as MapIcon,
  MapPin,
  MoreVertical,
  Navigation,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  RotateCcw,
  Save,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  Unlock,
  X,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { EdifyDatePicker } from '@/components/ui/EdifyDatePicker';
import {
  GetFieldDayResponseSchema,
  GetSchoolDistanceResponseSchema,
  GetSchoolPinsResponseSchema,
  ItineraryStopSchema,
  ListLocationChangesResponseSchema,
  RecordFieldDayResponseSchema,
  SaveFieldDayResponseSchema,
  SchoolPinSchema,
} from '@/gen/edify/routes/v1/routes_pb';
import type { GetSchoolDistanceResponse, ItineraryStop, SavedFieldDay, SchoolPin, Suggestion } from '@/gen/edify/routes/v1/routes_pb';
import {
  dayClock,
  fieldDayState,
  hoursMinutes,
  kampalaToday,
  km,
  legFigures,
} from '@/lib/routePlanner';
import { optionOf, hasNoRoadLeg, routeNote } from '@/lib/routeView';
import type { RouteOption } from '@/lib/routeView';
import type {
  CalendarRulesData,
  InAppDirectionsData,
  LatLngPoint,
  RoadConditionReportData,
  SmartOptimizationMode,
  SmartRouteResultData,
  SmartStopData,
} from '@/lib/routePlanner';

import { GpsCaptureModal } from './GpsCaptureModal';
import { InAppNavigationPanel } from './InAppNavigationPanel';
import { RouteIcon } from './RouteIcons';
import { QuickSelect } from './QuickSelect';
import { RouteBottomRow, RouteKpiStrip, RouteSsaTab } from './RouteInsights';
import { RouteMap } from './RouteMap';
import { NearbyCard } from './RouteParts';
import './route.css';

const card = 'rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[0_1px_2px_rgba(15,23,42,0.04)]';

const MODES: ReadonlyArray<{ id: SmartOptimizationMode; label: string; short: string; desc: string }> = [
  { id: 'balanced', label: 'Balanced Route — Recommended', short: 'Balanced', desc: 'Balances SSA priority, feasible coverage & travel time' },
  { id: 'fastest', label: 'Fastest Route', short: 'Fastest', desc: 'Minimizes estimated road driving time' },
  { id: 'shortest', label: 'Shortest Route', short: 'Shortest', desc: 'Minimizes total road kilometres' },
  { id: 'max_schools', label: 'Maximum Schools', short: 'Max Schools', desc: 'Highest feasible schools within working hours' },
  { id: 'priority_schools', label: 'Priority Schools', short: 'Priority SSA', desc: 'Urgent verified SSA & Core obligations first' },
];

const START_PRESETS: Record<string, { label: string; point: LatLngPoint | null }> = {
  first_school: { label: 'Start at First School', point: null },
  kampala_office: { label: 'Edify Uganda Office (Kampala)', point: { lat: 0.3136, lng: 32.5811 } },
  current_gps: { label: 'My Current GPS Location', point: null },
};

const postLegacy = (op: string, request: JsonValue) =>
  fetch('/route-planner', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ op, request }) });

async function askLegacy(op: 'pins' | 'distance' | 'changes' | 'save' | 'record', request: JsonValue): Promise<JsonValue> {
  const res = await postLegacy(op, request);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(typeof body?.error === 'string' ? body.error : 'Request failed.');
  return body;
}

async function smartApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data?.error === 'string' ? data.error : 'Smart Route request failed.');
  }
  return data as T;
}

const LOCATION_CHANGES_EVERY_MS = 60_000;

/** The phone's itinerary sheet: how far it rests when peeking, half open and open, in rem. */
const SHEET_PEEK_REM = 15.5;
const SHEET_HALF_REM = 26;
const SHEET_FULL_REM = 40;
const REM_PX = 16;
/** The modes the Route Options card compares. */
const COMPARED_MODES: readonly SmartOptimizationMode[] = ['balanced', 'fastest', 'shortest'];

export interface RoutePlannerProps {
  day: JsonValue;
  existingWebUrl: string;
  district: string;
  cluster: string;
  near?: string;
  /** Optional comma-separated school IDs to launch In-App Navigation immediately (from School Profile Get Directions). */
  navigate?: string;
}

function smartStopToItineraryStop(st: SmartStopData): ItineraryStop {
  return create(ItineraryStopSchema, {
    order: st.order,
    kind: st.kind,
    arrival: st.arrival,
    departure: st.departure,
    visitMinutes: st.visit_minutes,
    locked: st.locked,
    conflict: st.conflict ?? '',
    school: create(SchoolPinSchema, {
      schoolId: st.school_id,
      code: st.school_code,
      name: st.school_name,
      district: st.district,
      cluster: st.cluster,
      category: st.category,
      status: st.status,
      activityId: st.planned_activity_id ?? '',
      locationStatus: st.location_status,
      locationVersion: st.location_version,
      canOpenProfile: true,
      ...(st.point ? { point: { lat: st.point.lat, lng: st.point.lng } } : {}),
      ...(st.entrance ? { entrance: { lat: st.entrance.lat, lng: st.entrance.lng } } : {}),
    }),
  });
}

function priorityBadgeStyle(band: string): { label: string; cls: string } {
  switch (band) {
    case 'critical':
      return { label: 'Critical SSA', cls: 'bg-red-50 text-red-700 border-red-200' };
    case 'high':
      return { label: 'High SSA Need', cls: 'bg-amber-50 text-amber-800 border-amber-200' };
    case 'missing_ssa':
      return { label: 'SSA Needed', cls: 'bg-violet-50 text-violet-700 border-violet-200' };
    case 'core':
      return { label: 'Core School', cls: 'bg-blue-50 text-blue-800 border-blue-200' };
    default:
      return { label: 'Routine', cls: 'bg-slate-100 text-slate-600 border-slate-200' };
  }
}

export function RoutePlanner({ day: dayJson, existingWebUrl: _existingWebUrl, district, cluster, near = '', navigate = '' }: RoutePlannerProps) {
  void _existingWebUrl;
  const router = useRouter();
  const day = useMemo(() => fromJson(GetFieldDayResponseSchema, dayJson), [dayJson]);

  // Collapsible 3-panel desktop layout
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [rightTab, setRightTab] = useState<'itinerary' | 'directions' | 'coverage'>(navigate ? 'directions' : 'itinerary');
  // On a phone: the map or the list, the configuration sheet, and how far the itinerary sheet is pulled up.
  const [phoneView, setPhoneView] = useState<'map' | 'list'>('map');
  const [configOpen, setConfigOpen] = useState(false);
  const [sheetRem, setSheetRem] = useState(SHEET_PEEK_REM);
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef<{ y: number; rem: number } | null>(null);
  const [options, setOptions] = useState<RouteOption[]>([]);
  const [comparing, setComparing] = useState(false);

  // Smart Route configuration state
  const [mode, setMode] = useState<SmartOptimizationMode>('balanced');
  const [transportMode, setTransportMode] = useState<'DRIVE' | 'TWO_WHEELER'>('DRIVE');
  const [workStart, setWorkStart] = useState('08:00');
  const [workEnd, setWorkEnd] = useState('17:00');
  const [visitMinutes, setVisitMinutes] = useState(60);
  const [startChoice, setStartChoice] = useState<'first_school' | 'kampala_office' | 'current_gps'>('first_school');
  const [returnToStart, setReturnToStart] = useState(false);
  const [gpsStart, setGpsStart] = useState<LatLngPoint | null>(null);
  const [lockedIds, setLockedIds] = useState<Set<string>>(() => new Set());

  // Live Smart Route backend data
  const [smartResult, setSmartResult] = useState<SmartRouteResultData | null>(null);
  const [originalOrder, setOriginalOrder] = useState<string[]>(() =>
    (day.recommended?.stops ?? []).map((s) => s.school?.schoolId ?? '').filter(Boolean),
  );
  const [selectedSchoolIds, setSelectedSchoolIds] = useState<string[]>(() =>
    (day.recommended?.stops ?? [])
      .map((s) => s.school?.schoolId ?? '')
      .concat((day.recommended?.unplaced ?? []).map((p) => p.schoolId))
      .filter(Boolean),
  );
  const [ownerMeta, setOwnerMeta] = useState<{ name: string; role: string }>({ name: '', role: '' });
  const [calendarRules, setCalendarRules] = useState<CalendarRulesData | null>(null);
  const [roadConditions, setRoadConditions] = useState<RoadConditionReportData[]>([]);
  const [syncWarnings, setSyncWarnings] = useState<string[]>([]);

  // In-app Navigation state (100% inside Edify — zero external map launches)
  const [directions, setDirections] = useState<InAppDirectionsData | null>(null);
  const [dirLoading, setDirLoading] = useState(false);
  const [dirError, setDirError] = useState<string | null>(null);
  const [activeAltId, setActiveAltId] = useState<string | null>(null);
  const [userGps, setUserGps] = useState<LatLngPoint | null>(null);

  // Field day / legacy interactive states
  const [saved, setSaved] = useState<SavedFieldDay | undefined>(day.saved);
  const fieldDay = fieldDayState(saved, day.date, kampalaToday());
  const [show, setShow] = useState({ planned: true, suggested: true, nearby: false });
  const [nearbyPins, setNearbyPins] = useState<SchoolPin[]>([]);
  const [selectedPin, setSelectedPin] = useState<SchoolPin | null>(null);
  const [pair, setPair] = useState<GetSchoolDistanceResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(day.provider?.message || null);
  const [allNearby, setAllNearby] = useState(Boolean(day.focus));
  const [showReportModal, setShowReportModal] = useState(false);
  const [openStop, setOpenStop] = useState('');
  const [gpsModalTarget, setGpsModalTarget] = useState<{
    schoolId: string;
    schoolCode: string;
    schoolName: string;
    existingPoint?: { lat: number; lng: number } | null;
    baseVersion?: number;
  } | null>(null);

  const lastSelected = useRef<SchoolPin | null>(null);
  const viewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const focus = day.focus;

  // Hydrate Smart Route day state, calendar rules (holidays/leave/FY2027), and My Plan sync status from Go API.
  useEffect(() => {
    let active = true;
    void smartApi<{
      owner_name: string;
      owner_role: string;
      result: SmartRouteResultData;
      road_conditions: RoadConditionReportData[];
      calendar_rules: CalendarRulesData;
    }>(`smart-route/day?date=${encodeURIComponent(day.date)}&mode=${encodeURIComponent(mode)}`)
      .then((payload) => {
        if (!active) return;
        setOwnerMeta({ name: payload.owner_name, role: payload.owner_role });
        setSmartResult(payload.result);
        setRoadConditions(payload.road_conditions ?? []);
        setCalendarRules(payload.calendar_rules ?? null);
        const ids = [
          ...payload.result.stops.map((s) => s.school_id),
          ...payload.result.excluded.map((e) => e.school_id),
        ];
        if (ids.length > 0) {
          setSelectedSchoolIds(ids);
          setOriginalOrder((prev) => (prev.length === 0 ? ids : prev));
        }
      })
      .catch(() => undefined);

    void smartApi<{ stale: boolean; reasons: string[] }>('smart-route/validate', {
      method: 'POST',
      body: JSON.stringify({ date: day.date }),
    })
      .then((val) => {
        if (active && val.stale) setSyncWarnings(val.reasons ?? []);
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day.date]);

  // Poll for accepted GPS corrections so map & route synchronize automatically.
  useEffect(() => {
    const shown = new Set([
      ...day.planned.map((p) => p.schoolId),
      ...day.suggestions.map((s) => s.school?.schoolId ?? ''),
      ...(day.focus ? [day.focus.schoolId] : []),
    ]);
    let since = new Date().toISOString();
    const timer = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      askLegacy('changes', { since })
        .then((json) => {
          const answer = fromJson(ListLocationChangesResponseSchema, json);
          if (answer.now) since = answer.now;
          if (answer.changes.some((c) => shown.has(c.schoolId))) {
            setMessage('A school location was verified and updated. Refreshing route coordinates.');
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

  const resolveStart = useCallback((): { point: LatLngPoint | null; label: string } => {
    if (startChoice === 'kampala_office') return START_PRESETS.kampala_office!;
    if (startChoice === 'current_gps' && gpsStart) return { point: gpsStart, label: 'Current GPS Location' };
    return { point: null, label: '' };
  }, [startChoice, gpsStart]);

  const runOptimize = useCallback(
    async (
      idsOverride?: string[],
      modeOverride?: SmartOptimizationMode,
      locksOverride?: ReadonlySet<string>,
    ) => {
      const idsToPlan = idsOverride ?? selectedSchoolIds;
      if (idsToPlan.length === 0) return;
      const chosenMode = modeOverride ?? mode;
      const locks = locksOverride ?? lockedIds;
      const startCfg = resolveStart();
      setBusy(true);
      setMessage(null);
      setActiveAltId(null);
      try {
        const res = await smartApi<{ result: SmartRouteResultData }>('smart-route/optimize', {
          method: 'POST',
          body: JSON.stringify({
            date: day.date,
            mode: chosenMode,
            transport_mode: transportMode,
            work_start: workStart,
            work_end: workEnd,
            visit_minutes: visitMinutes,
            break_minutes: 30,
            start: startCfg.point,
            start_label: startCfg.label,
            end: returnToStart ? startCfg.point : null,
            end_label: returnToStart ? startCfg.label : '',
            school_ids: idsToPlan,
            locked_school_ids: [...locks],
          }),
        });
        setSmartResult(res.result);
        setMode(chosenMode === 'as_given' ? mode : chosenMode);
        setSelectedSchoolIds([
          ...res.result.stops.map((s) => s.school_id),
          ...res.result.excluded.map((e) => e.school_id),
        ]);
        if (res.result.warnings.length > 0 && !res.result.path_is_road) {
          setMessage(res.result.warnings[0] ?? null);
        }
      } catch (err) {
        setMessage(err instanceof Error ? err.message : 'Route optimization failed.');
      } finally {
        setBusy(false);
      }
    },
    [day.date, lockedIds, mode, resolveStart, returnToStart, selectedSchoolIds, transportMode, visitMinutes, workEnd, workStart],
  );

  // Route Options: the same day's schools ordered each way, from real road figures. Each call is an
  // audited calculation, so this runs when asked for, never on its own.
  const compareRoutes = useCallback(async () => {
    if (selectedSchoolIds.length === 0) return;
    setComparing(true);
    const startCfg = resolveStart();
    try {
      const answers = await Promise.all(
        COMPARED_MODES.map((m) =>
          smartApi<{ result: SmartRouteResultData }>('smart-route/optimize', {
            method: 'POST',
            body: JSON.stringify({
              date: day.date,
              mode: m,
              transport_mode: transportMode,
              work_start: workStart,
              work_end: workEnd,
              visit_minutes: visitMinutes,
              break_minutes: 30,
              start: startCfg.point,
              start_label: startCfg.label,
              end: returnToStart ? startCfg.point : null,
              end_label: returnToStart ? startCfg.label : '',
              school_ids: selectedSchoolIds,
              locked_school_ids: [...lockedIds],
            }),
          }),
        ),
      );
      setOptions(answers.map((answer, index) => {
        const m = COMPARED_MODES[index]!;
        return optionOf(m, MODES.find((item) => item.id === m)?.short ?? m, answer.result);
      }));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'The routes could not be compared.');
    } finally {
      setComparing(false);
    }
  }, [day.date, lockedIds, resolveStart, returnToStart, selectedSchoolIds, transportMode, visitMinutes, workEnd, workStart]);

  // Launch 100% In-App Turn-by-Turn Navigation inside Edify (Section 6).
  const openInAppDirections = useCallback(
    async (schoolIds: string[], explicitOrigin?: LatLngPoint) => {
      if (schoolIds.length === 0) return;
      setRightOpen(true);
      setRightTab('directions');
      setDirLoading(true);
      setDirError(null);
      setActiveAltId(null);
      try {
        const startCfg = resolveStart();
        const origin = explicitOrigin ?? userGps ?? startCfg.point ?? undefined;
        const originLabel = explicitOrigin ? 'Current GPS Location' : userGps ? 'Current GPS Location' : startCfg.label;
        const data = await smartApi<InAppDirectionsData>('smart-route/directions', {
          method: 'POST',
          body: JSON.stringify({
            origin,
            origin_label: originLabel,
            school_ids: schoolIds,
            transport_mode: transportMode,
          }),
        });
        setDirections(data);
      } catch (err) {
        setDirError(err instanceof Error ? err.message : 'Could not calculate in-app directions.');
      } finally {
        setDirLoading(false);
      }
    },
    [resolveStart, transportMode, userGps],
  );

  // If navigated directly from a School Profile's "Get Directions" button (?navigate=schoolId)
  useEffect(() => {
    if (!navigate) return;
    const ids = navigate.split(',').map((s) => s.trim()).filter(Boolean);
    if (ids.length === 0) return;
    const open = window.setTimeout(() => void openInAppDirections(ids), 0);
    return () => window.clearTimeout(open);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate]);

  const saveRoute = async () => {
    const stopsToSave = smartResult?.stops ?? [];
    if (stopsToSave.length === 0) return;
    setBusy(true);
    try {
      const startCfg = resolveStart();
      const ans = await smartApi<{ route_id: string; route_version: number; saved_at: string }>('smart-route/save', {
        method: 'POST',
        body: JSON.stringify({
          date: day.date,
          optimization_mode: smartResult?.mode ?? mode,
          transport_mode: transportMode,
          start: startCfg.point,
          start_label: startCfg.label,
          end: returnToStart ? startCfg.point : null,
          end_label: returnToStart ? startCfg.label : '',
          estimated_meters: smartResult?.totals.road_meters ?? 0,
          estimated_seconds: smartResult?.totals.road_seconds ?? 0,
          visit_minutes: smartResult?.totals.visit_minutes ?? 0,
          field_minutes: smartResult?.totals.field_minutes ?? 0,
          input_hash: smartResult?.input_hash ?? '',
          alternatives_count: smartResult?.alternatives.length ?? 0,
          stops: stopsToSave,
        }),
      });
      const legacySaved = fromJson(
        SaveFieldDayResponseSchema,
        await askLegacy('save', { date: day.date, schoolIds: stopsToSave.map((s) => s.school_id) }),
      );
      setSaved(legacySaved.saved);
      setMessage(
        `Route v${ans.route_version} saved at ${dayClock(ans.saved_at)}. Stops remain linked to their My Plan activity IDs; official schedules are unchanged.`,
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'The route could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const recordFieldDay = async (event: 'start' | 'arrive' | 'leave' | 'end', schoolId = '') => {
    setBusy(true);
    try {
      const stopIds = (smartResult?.stops ?? []).map((s) => s.school_id);
      const answer = fromJson(
        RecordFieldDayResponseSchema,
        await askLegacy('record', { date: day.date, event, schoolId, schoolIds: event === 'start' ? stopIds : [] }),
      );
      setSaved(answer.saved);
      setMessage(
        event === 'start'
          ? `Field day started at ${dayClock(answer.saved?.startedAt ?? '')}. Mark arrivals and complete visits through My Plan.`
          : event === 'end'
            ? `Field day ended at ${dayClock(answer.saved?.endedAt ?? '')}.`
            : null,
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Could not update field day status.');
    } finally {
      setBusy(false);
    }
  };

  const onPickPin = async (pin: SchoolPin) => {
    setSelectedPin(pin);
    setPair(null);
    const previous = lastSelected.current;
    lastSelected.current = pin;
    if (previous && previous.schoolId !== pin.schoolId) {
      try {
        const answer = fromJson(GetSchoolDistanceResponseSchema, await askLegacy('distance', { fromSchoolId: previous.schoolId, toSchoolId: pin.schoolId }));
        setPair(answer);
      } catch {
        setPair(null);
      }
    }
  };

  const onView = useCallback(
    (sw: LatLngPoint, ne: LatLngPoint) => {
      if (!show.nearby) return;
      if (viewTimer.current) clearTimeout(viewTimer.current);
      viewTimer.current = setTimeout(async () => {
        try {
          const answer = fromJson(
            GetSchoolPinsResponseSchema,
            await askLegacy('pins', {
              southWest: { lat: sw.lat, lng: sw.lng },
              northEast: { lat: ne.lat, lng: ne.lng },
              date: day.date,
              districtId: district,
              clusterId: cluster,
            }),
          );
          setNearbyPins(answer.pins);
        } catch {
          setNearbyPins([]);
        }
      }, 350);
    },
    [show.nearby, day.date, district, cluster],
  );

  // Derive stops & road geometry for the center interactive map (NEVER straight-line fake roads!).
  const mapStops = useMemo<ItineraryStop[]>(() => {
    if (smartResult && smartResult.stops.length > 0) {
      return smartResult.stops
        .filter((s) => (s.kind === 'recommended' ? show.suggested : show.planned))
        .map(smartStopToItineraryStop);
    }
    return (day.recommended?.stops ?? []).filter((s) => (s.kind === 'recommended' ? show.suggested : show.planned));
  }, [smartResult, day.recommended, show.planned, show.suggested]);

  const prioritySchoolIds = useMemo(
    () => new Set((smartResult?.stops ?? []).filter((st) => (st.priority?.band ?? 'routine') !== 'routine').map((st) => st.school_id)),
    [smartResult],
  );

  const activePath = useMemo<LatLngPoint[]>(() => {
    if (rightTab === 'directions' && directions?.road_available && directions.path.length >= 2) {
      return directions.path;
    }
    if (smartResult?.path_is_road && smartResult.path.length >= 2) {
      return smartResult.path;
    }
    return [];
  }, [rightTab, directions, smartResult]);

  const activePathIsRoad = useMemo(() => {
    if (rightTab === 'directions' && directions) return Boolean(directions.road_available && directions.path.length >= 2);
    return Boolean(smartResult?.path_is_road && smartResult.path.length >= 2);
  }, [rightTab, directions, smartResult]);

  const activeAlternatives = useMemo(() => {
    if (rightTab === 'directions' && directions?.alternatives?.length) return directions.alternatives;
    return smartResult?.alternatives ?? [];
  }, [rightTab, directions, smartResult]);

  const stopIdSet = useMemo(() => new Set(mapStops.map((s) => s.school?.schoolId ?? '')), [mapStops]);

  const others = useMemo(() => {
    const suggested = show.suggested ? day.suggestions.map((s) => s.school!).filter((p) => !stopIdSet.has(p.schoolId)) : [];
    const nearPins = show.nearby ? nearbyPins.filter((p) => !stopIdSet.has(p.schoolId)) : [];
    const seen = new Set<string>();
    return [...suggested, ...nearPins].filter((p) => (seen.has(p.schoolId) ? false : (seen.add(p.schoolId), true)));
  }, [day.suggestions, nearbyPins, show.suggested, show.nearby, stopIdSet]);

  const moveStop = (index: number, delta: number) => {
    const currentIds = (smartResult?.stops ?? []).map((s) => s.school_id);
    const to = index + delta;
    if (to < 0 || to >= currentIds.length) return;
    const copy = [...currentIds];
    const item = copy[index]!;
    copy[index] = copy[to]!;
    copy[to] = item;
    void runOptimize(copy, 'as_given');
  };

  const removeStop = (schoolId: string) => {
    const next = selectedSchoolIds.filter((id) => id !== schoolId);
    setSelectedSchoolIds(next);
    if (next.length > 0) void runOptimize(next, mode);
  };

  const toggleLock = (schoolId: string) => {
    const next = new Set(lockedIds);
    if (next.has(schoolId)) next.delete(schoolId);
    else next.add(schoolId);
    setLockedIds(next);
  };

  const addHref = (s: Suggestion | SchoolPin) => {
    const pin = s.$typeName === 'edify.routes.v1.Suggestion' ? s.school! : s;
    return `/schools/${encodeURIComponent(pin.code || pin.schoolId)}`;
  };

  const requestCurrentGpsAsStart = () => {
    setStartChoice('current_gps');
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setMessage('Device GPS is unavailable in this browser.');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const pt = { lat: coords.latitude, lng: coords.longitude };
        setGpsStart(pt);
        setUserGps(pt);
        setMessage(`Starting point set to your current GPS (${pt.lat.toFixed(4)}, ${pt.lng.toFixed(4)}).`);
      },
      () => setMessage('Could not read device GPS. Choose Kampala Office or First School instead.'),
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  };

  const totals = smartResult?.totals;
  const chip =
    totals && totals.schools_included > 0
      ? totals.road_complete
        ? `${km(totals.road_meters)} by road  |  ${hoursMinutes(totals.road_seconds)}`
        : `${totals.schools_included} stop${totals.schools_included === 1 ? '' : 's'} · Road verification needed`
      : null;

  const planningPolicy = useMemo(
    () => ({
      mode: 'planning' as const,
      holidays: calendarRules?.holidays ?? [],
      approvedLeaveDates: calendarRules?.approved_leave_dates ?? [],
      blackoutDates: calendarRules?.blackout_dates ?? [],
    }),
    [calendarRules],
  );

  const checkIns = useMemo(() => new Map((saved?.stops ?? []).map((c) => [c.schoolId, c])), [saved]);
  const pickPhoneView = (view: 'map' | 'list') => {
    setPhoneView(view);
    setSheetRem(view === 'list' ? SHEET_FULL_REM : SHEET_PEEK_REM);
  };
  const startSheetDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStart.current = { y: event.clientY, rem: sheetRem };
    setIsDragging(true);
  };
  const moveSheetDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (!dragStart.current) return;
    const moved = (dragStart.current.y - event.clientY) / REM_PX;
    setSheetRem(Math.min(SHEET_FULL_REM, Math.max(SHEET_PEEK_REM, dragStart.current.rem + moved)));
  };
  const endSheetDrag = () => {
    if (!dragStart.current) return;
    dragStart.current = null;
    setIsDragging(false);
    // It rests at whichever stop is nearest.
    const nearest = [SHEET_PEEK_REM, SHEET_HALF_REM, SHEET_FULL_REM].reduce((best, rem) => (Math.abs(rem - sheetRem) < Math.abs(best - sheetRem) ? rem : best));
    setSheetRem(nearest);
    setPhoneView(nearest === SHEET_FULL_REM ? 'list' : 'map');
  };
  const cycleSheet = () => {
    const next = sheetRem < SHEET_HALF_REM ? SHEET_HALF_REM : sheetRem < SHEET_FULL_REM ? SHEET_FULL_REM : SHEET_PEEK_REM;
    setSheetRem(next);
    setPhoneView(next === SHEET_FULL_REM ? 'list' : 'map');
  };

  // Dynamic 3-panel desktop layout key (panels collapsible to maximize map)
  const layoutKey =
    leftOpen && rightOpen
      ? 'both'
      : leftOpen && !rightOpen
        ? 'left'
        : !leftOpen && rightOpen
          ? 'right'
          : 'map-only';

  return (
    <div className="mx-auto max-w-[1800px] px-3 pb-10 pt-3 sm:px-5" data-page="smart-route">
      {/* Breadcrumb, title and the day's actions */}
      <nav className="flex items-center gap-2 text-[13px]" aria-label="Breadcrumb">
        <Link href="/my-plan" className="text-[var(--edify-text-muted)] hover:text-[var(--brand-primary)] hover:underline">
          My Plan
        </Link>
        <RouteIcon name="arrowRight" className="h-3.5 w-3.5 text-[var(--edify-text-muted)]" />
        <span className="font-semibold text-[var(--edify-text)]">Smart Route Planner</span>
        {calendarRules ? (
          <span className="ml-auto hidden rounded-full bg-[var(--edify-surface-muted)] px-2.5 py-0.5 text-[11px] font-semibold text-[var(--edify-text-muted)] sm:inline">
            {calendarRules.current_fy}
          </span>
        ) : null}
      </nav>

      <header className="sr-header">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[12px] bg-[var(--brand-primary)] text-white">
            <MapPin className="h-6 w-6" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h1 className="text-[20px] font-bold leading-tight text-[var(--edify-text)] sm:text-[24px]">Smart Route Planner</h1>
            <p className="text-[13px] text-[var(--edify-text-muted)]">
              <span className="sr-long">Intelligent, road-network routing with SSA, coverage, traffic and field-day optimization.</span>
              <span className="sr-short">Intelligent, road-network routing for your school visits.</span>
            </p>
          </div>
        </div>

        <div className="sr-header__actions">
          <button
            type="button"
            onClick={() => setLeftOpen((v) => !v)}
            className="sr-desktop-btn h-10 items-center gap-1.5 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px] font-semibold text-[var(--edify-text)] hover:border-[var(--brand-primary)]"
            aria-pressed={leftOpen}
          >
            {leftOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
            Config
          </button>
          <button
            type="button"
            onClick={() => setRightOpen((v) => !v)}
            className="sr-desktop-btn h-10 items-center gap-1.5 rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[13px] font-semibold text-[var(--edify-text)] hover:border-[var(--brand-primary)]"
            aria-pressed={rightOpen}
          >
            {rightOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
            Itinerary
          </button>
          <button
            type="button"
            disabled={busy || !(smartResult?.stops.length)}
            onClick={() => void saveRoute()}
            className="inline-flex h-10 items-center gap-2 rounded-[10px] border border-[var(--brand-primary)] bg-[var(--edify-surface)] px-4 text-[13px] font-semibold text-[var(--brand-primary)] disabled:opacity-45"
          >
            <Save className="h-4 w-4" aria-hidden="true" /> Save Route
          </button>
          {fieldDay.running ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void recordFieldDay('end')}
              className="inline-flex h-10 items-center gap-2 rounded-[10px] bg-emerald-600 px-4 text-[13px] font-semibold text-white hover:bg-emerald-700"
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> End Field Day
            </button>
          ) : fieldDay.canStart ? (
            <button
              type="button"
              disabled={busy || !(smartResult?.stops.length)}
              onClick={() => void recordFieldDay('start')}
              className="inline-flex h-10 items-center gap-2 rounded-[10px] bg-[var(--brand-primary)] px-4 text-[13px] font-semibold text-white hover:bg-[var(--brand-primary-hover)] disabled:opacity-45"
            >
              <Navigation className="h-4 w-4" aria-hidden="true" /> Start Field Day
            </button>
          ) : (
            <button type="button" disabled title="Not available for this day" className="inline-flex h-10 items-center gap-2 rounded-[10px] bg-[var(--brand-primary)] px-4 text-[13px] font-semibold text-white opacity-45">
              <Navigation className="h-4 w-4" aria-hidden="true" /> Start Field Day
            </button>
          )}
        </div>
      </header>

      <RouteKpiStrip result={smartResult} plannedStops={mapStops.length} />

      {/* The phone's date, place and settings, then Map or List */}
      <div className="sr-quick">
        <EdifyDatePicker
          id="smart-route-date-phone"
          label="Planning date"
          value={day.date}
          displayStyle="medium"
          policy={planningPolicy}
          showFiscalYear
          size="md"
          onChange={(nextIso) => {
            if (nextIso && nextIso !== day.date) go({ date: nextIso });
          }}
        />
        <QuickSelect label="District" value={district} allWords="All Districts" options={day.districts} onChange={(value) => go({ district: value })} />
        <QuickSelect label="Cluster" value={cluster} allWords="All Clusters" options={day.clusters} onChange={(value) => go({ cluster: value })} />
        <button type="button" onClick={() => setConfigOpen(true)} aria-label="Route settings" className="grid h-10 w-10 place-items-center rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-surface)] text-[var(--edify-text)]">
          <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div className="sr-viewswitch" role="group" aria-label="Show the route as">
        <button type="button" aria-pressed={phoneView === 'map'} onClick={() => pickPhoneView('map')}><MapIcon className="h-4 w-4" aria-hidden="true" /> Map View</button>
        <button type="button" aria-pressed={phoneView === 'list'} onClick={() => pickPhoneView('list')}><ListIcon className="h-4 w-4" aria-hidden="true" /> List View</button>
      </div>

      {/* Banners: Focus, My Plan Sync Warning, Status Message */}
      {focus ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-[12px] border border-[var(--brand-primary)]/40 bg-blue-50 px-4 py-2.5 text-[13px]" role="status">
          <span>
            <strong>Schools near {focus.name}</strong> (ID {focus.code})
          </span>
          <button type="button" onClick={() => go({ near: '' })} className="rounded-[8px] border border-[var(--brand-primary)] bg-white px-3 py-1 font-semibold text-[var(--brand-primary)]">
            Show my day
          </button>
        </div>
      ) : null}

      {syncWarnings.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-amber-300 bg-amber-50 px-4 py-2.5 text-[13px] text-amber-950" role="status">
          <div>
            <p className="font-bold">My Plan synchronization notice</p>
            <p>{syncWarnings.join(' ')}</p>
          </div>
          <button
            type="button"
            onClick={() => void runOptimize()}
            className="rounded-[8px] bg-amber-700 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-amber-800"
          >
            Re-optimize now
          </button>
        </div>
      ) : null}

      {message ? (
        <p className="mt-3 rounded-[12px] border border-[var(--edify-border)] bg-white px-4 py-2.5 text-[13px] text-slate-700" role="status">
          {message}
        </p>
      ) : null}

      {/* ===================================================================== */}
      {/* MAIN 3-PANEL DESKTOP WORKSPACE (Map-First on Mobile)                  */}
      {/* ===================================================================== */}
      <div className="sr-workspace mt-3" data-layout={layoutKey}>
        {/* LEFT PANEL — Route Configuration */}
        {leftOpen ? (
          <aside className={`${card} sr-panel-config flex-col p-4`} aria-label="Route configuration" data-panel="route-config" data-open={configOpen || undefined}>
            <div className="sr-config-head">
              <h2>
                <SlidersHorizontal className="h-[18px] w-[18px] shrink-0 text-[var(--brand-primary)]" aria-hidden="true" />
                Route Configuration
              </h2>
              {ownerMeta.name ? <span className="sr-role-chip">{ownerMeta.role || 'Staff'}</span> : null}
              <button type="button" onClick={() => setConfigOpen(false)} aria-label="Close route settings" className="sr-config-close h-9 w-9 items-center justify-center rounded-full text-[var(--edify-text-muted)]">
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>

            <div className="sr-field" data-sr-geo>
              <label htmlFor="smart-route-date">Planning Date</label>
              <EdifyDatePicker
                id="smart-route-date"
                label="Planning date"
                value={day.date}
                displayStyle="weekday"
                policy={planningPolicy}
                showFiscalYear
                showQuickActions
                size="md"
                onChange={(nextIso) => {
                  if (nextIso && nextIso !== day.date) go({ date: nextIso });
                }}
              />
            </div>

            <div className="sr-field" data-sr-geo>
              <span className="sr-field__title">Geographic Scope</span>
              <div className="sr-two">
                <div className="sr-boxed">
                  <span>District</span>
                  <QuickSelect label="District" value={district} allWords="All Districts" options={day.districts} onChange={(value) => go({ district: value })} />
                </div>
                <div className="sr-boxed">
                  <span>Cluster</span>
                  <QuickSelect label="Cluster" value={cluster} allWords="All Clusters" options={day.clusters} onChange={(value) => go({ cluster: value })} />
                </div>
              </div>
            </div>

            <label className="sr-field">
              <span className="sr-field__title">Start Location</span>
              <span className="sr-icon-field">
                <MapPin className="h-4 w-4" aria-hidden="true" />
                <select
                  value={startChoice}
                  onChange={(e) => {
                    const v = e.target.value as 'first_school' | 'kampala_office' | 'current_gps';
                    if (v === 'current_gps') requestCurrentGpsAsStart();
                    else setStartChoice(v);
                  }}
                >
                  <option value="first_school">Start at First School</option>
                  <option value="kampala_office">Edify Uganda Office (Kampala)</option>
                  <option value="current_gps">Use My Current GPS</option>
                </select>
              </span>
            </label>

            <div className="sr-field">
              <span className="sr-field__title">End Location <small>(optional)</small></span>
              <label className="sr-check-row" title={startChoice === 'first_school' ? 'Choose a start location to return to' : undefined}>
                <Flag className="h-4 w-4" aria-hidden="true" />
                <span>Return to Start</span>
                <input type="checkbox" disabled={startChoice === 'first_school'} checked={returnToStart && startChoice !== 'first_school'} onChange={(e) => setReturnToStart(e.target.checked)} />
              </label>
            </div>

            <div className="sr-two">
              <label className="sr-field">
                <span className="sr-field__title">Work Start</span>
                <input type="time" value={workStart} onChange={(e) => setWorkStart(e.target.value)} />
              </label>
              <label className="sr-field">
                <span className="sr-field__title">Work End</span>
                <input type="time" value={workEnd} onChange={(e) => setWorkEnd(e.target.value)} />
              </label>
            </div>

            <label className="sr-field">
              <span className="sr-field__title">Visit Duration <small>(minutes per school)</small></span>
              <input type="number" min={15} max={240} step={15} value={visitMinutes} onChange={(e) => setVisitMinutes(Number(e.target.value) || 60)} />
            </label>

            <div className="sr-field">
              <span className="sr-field__title"><Car className="h-4 w-4" aria-hidden="true" /> Vehicle Type</span>
              <div className="sr-two">
                {(
                  [
                    ['DRIVE', 'Vehicle', Car],
                    ['TWO_WHEELER', 'Motorcycle', Bike],
                  ] as const
                ).map(([tm, lbl, VehicleIcon]) => (
                  <button key={tm} type="button" onClick={() => setTransportMode(tm)} aria-pressed={transportMode === tm} className="sr-pill">
                    <VehicleIcon className="h-4 w-4" aria-hidden="true" /> {lbl}
                  </button>
                ))}
              </div>
            </div>

            <label className="sr-field">
              <span className="sr-field__title">Optimization Mode</span>
              <select value={mode} onChange={(e) => setMode(e.target.value as SmartOptimizationMode)} title={MODES.find((m) => m.id === mode)?.desc}>
                {MODES.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
            </label>

            <button
              type="button"
              role="switch"
              aria-checked={mode === 'priority_schools'}
              onClick={() => setMode(mode === 'priority_schools' ? 'balanced' : 'priority_schools')}
              className="sr-switch-row"
            >
              <Sparkles className="h-4 w-4 shrink-0 text-[var(--brand-primary)]" aria-hidden="true" />
              <span>Include SSA Priority Schools</span>
              <i aria-hidden="true" />
            </button>

            <button
              type="button"
              disabled={busy || selectedSchoolIds.length === 0}
              onClick={() => {
                setConfigOpen(false);
                void runOptimize();
              }}
              data-action="optimize-route"
              className="sr-optimize flex h-11 w-full items-center justify-center gap-2 rounded-[10px] bg-[var(--brand-primary)] text-[14px] font-bold text-white shadow-sm hover:bg-[var(--brand-primary-hover)] disabled:opacity-50"
            >
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              {busy ? 'Optimizing Road Route…' : 'Optimize Route'}
            </button>
          </aside>
        ) : null}

        {/* CENTER PANEL — Dominant Interactive Road Map */}
        <section className={`${card} sr-panel-map relative overflow-hidden`} aria-label="Interactive road map">
          <RouteMap
            stops={mapStops}
            path={show.planned ? activePath : []}
            pathIsRoad={activePathIsRoad}
            alternatives={activeAlternatives}
            activeAlternativeId={activeAltId}
            onSelectAlternative={setActiveAltId}
            roadAlerts={smartResult?.road_alerts ?? roadConditions}
            prioritySchoolIds={prioritySchoolIds}
            layers={
              <div className="sr-layer-list">
                {(
                  [
                    ['planned', 'Planned'],
                    ['suggested', 'Suggested'],
                    ['nearby', 'Nearby'],
                  ] as const
                ).map(([k, lbl]) => (
                  <label key={k}>
                    <input type="checkbox" checked={show[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} />
                    {lbl}
                  </label>
                ))}
              </div>
            }
            userLocation={userGps}
            others={others}
            chip={chip}
            onSelect={onPickPin}
            onView={onView}
            className="absolute inset-0"
            focus={focus}
            fitOthers={Boolean(focus)}
          />
          {smartResult?.stops.length ? (
            <button type="button" className="sr-rec-card" onClick={() => pickPhoneView('list')}>
              <Crown className="h-5 w-5 shrink-0 text-[var(--brand-primary)]" aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <strong>{smartResult.is_recommended ? 'Recommended Route' : MODES.find((m) => m.id === smartResult.mode)?.short ?? 'Route'}</strong>
                <span>{totals?.road_complete && totals.road_meters > 0 ? `${km(totals.road_meters)} • ${hoursMinutes(totals.road_seconds)}` : `${smartResult.stops.length} school${smartResult.stops.length === 1 ? '' : 's'}`}</span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />
            </button>
          ) : null}

          {selectedPin ? (
            <SchoolPopupCard
              pin={selectedPin}
              pair={pair}
              inRoute={stopIdSet.has(selectedPin.schoolId)}
              addHref={addHref(selectedPin)}
              onClose={() => setSelectedPin(null)}
              onSelectForRoute={() => {
                const next = [...selectedSchoolIds.filter((id) => id !== selectedPin.schoolId), selectedPin.schoolId];
                setSelectedSchoolIds(next);
                void runOptimize(next, mode);
                setSelectedPin(null);
              }}
              onInAppDirections={() => {
                void openInAppDirections([selectedPin.schoolId]);
                setSelectedPin(null);
              }}
              onCaptureGps={() => {
                setGpsModalTarget({
                  schoolId: selectedPin.schoolId,
                  schoolCode: selectedPin.code,
                  schoolName: selectedPin.name,
                  existingPoint: selectedPin.point ? { lat: selectedPin.point.lat, lng: selectedPin.point.lng } : null,
                  baseVersion: selectedPin.locationVersion || 0,
                });
                setSelectedPin(null);
              }}
            />
          ) : null}

        </section>

        {/* RIGHT PANEL — Recommended Itinerary & In-App Directions */}
        {rightOpen ? (
          <aside
            className={`${card} sr-panel-itinerary flex flex-col gap-3 p-4`}
            aria-label="Recommended itinerary and navigation"
            data-panel="route-itinerary"
            data-dragging={isDragging || undefined}
            style={{ '--sr-sheet': `${sheetRem}rem` } as React.CSSProperties}
          >
            <button
              type="button"
              className="sr-sheet-handle"
              aria-label="Resize the itinerary"
              onPointerDown={startSheetDrag}
              onPointerMove={moveSheetDrag}
              onPointerUp={endSheetDrag}
              onPointerCancel={endSheetDrag}
              onClick={() => {
                if (!isDragging) cycleSheet();
              }}
            >
              <span />
            </button>
            {phoneView === 'list' ? (
              <button type="button" className="sr-sheet-mapback" onClick={() => pickPhoneView('map')}>
                <MapIcon className="h-4 w-4" aria-hidden="true" /> Back to Map
              </button>
            ) : null}
            {/* Itinerary, In-App Directions, SSA & Coverage */}
            <div className="sr-tabs" role="tablist" aria-label="Route details">
              <button
                type="button"
                role="tab"
                aria-selected={rightTab === 'itinerary'}
                onClick={() => setRightTab('itinerary')}
              >
                Itinerary ({smartResult?.stops.length ?? mapStops.length})
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={rightTab === 'directions'}
                onClick={() => {
                  setRightTab('directions');
                  if (!directions && (smartResult?.stops.length ?? 0) > 0) {
                    void openInAppDirections(smartResult!.stops.map((s) => s.school_id));
                  }
                }}
              >
                Directions
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={rightTab === 'coverage'}
                onClick={() => setRightTab('coverage')}
              >
                SSA &amp; Coverage
              </button>
            </div>

            <div className="sr-sheet-body" tabIndex={0} role="region" aria-label="Route details list">

            {rightTab === 'directions' ? (
              <InAppNavigationPanel
                directions={directions}
                loading={dirLoading}
                error={dirError}
                activeAlternativeId={activeAltId}
                onSelectAlternative={setActiveAltId}
                onRecalculateFromGps={(origin) => {
                  const targetIds = directions?.stops.map((s) => s.school_id) ?? (smartResult?.stops ?? []).map((s) => s.school_id);
                  if (targetIds.length > 0) void openInAppDirections(targetIds, origin);
                }}
                onUserLocationChange={setUserGps}
                onClose={() => setRightTab('itinerary')}
              />
            ) : rightTab === 'coverage' ? (
              <RouteSsaTab result={smartResult} />
            ) : (
              <>
                {/* Route Recommendation & Comparison Summary (Section 5.3) */}
                {smartResult ? (
                  <details data-sr-summary className="sr-summary">
                    <summary>
                      <span title={smartResult.objective_label}>{smartResult.objective_label}</span>
                      {smartResult.is_recommended ? <em>Recommended</em> : null}
                    </summary>
                    <p>{routeNote(smartResult)}</p>
                    {(smartResult.distance_saved_meters > 0 || smartResult.time_saved_seconds > 0) ? (
                      <p className="font-semibold text-[var(--edify-success-text)]">
                        Optimization saved {km(smartResult.distance_saved_meters)} and {hoursMinutes(smartResult.time_saved_seconds)} vs. initial order.
                      </p>
                    ) : null}
                    <p>Confidence: <strong className="uppercase">{smartResult.confidence}</strong> · {smartResult.provider.toUpperCase()} · Calculated {dayClock(smartResult.calculated_at)}</p>
                    {hasNoRoadLeg(smartResult) ? null : <p>{smartResult.confidence_note}</p>}
                  </details>
                ) : null}

                {/* Road Condition Alerts */}
                {smartResult && smartResult.road_alerts.length > 0 ? (
                  <div className="space-y-1.5 rounded-[12px] border border-amber-300 bg-amber-50 p-3 text-[12px] text-amber-950">
                    <p className="flex items-center gap-1.5 font-bold">
                      <ShieldAlert className="h-4 w-4 text-amber-700" aria-hidden="true" /> Active Road Warnings ({smartResult.road_alerts.length})
                    </p>
                    {smartResult.road_alerts.map((al) => (
                      <p key={al.id} className="text-[11px]">
                        <strong>{al.road_name}</strong> ({al.category.replaceAll('_', ' ')}, {al.verification_status}): {al.applicability_note}
                      </p>
                    ))}
                  </div>
                ) : null}

                {/* Ordered Stop Sequence */}
                {smartResult && smartResult.stops.length > 0 ? (
                  <ol className="sr-stops" aria-label="Optimized school stop sequence">
                    {smartResult.start_label ? (
                      <li className="sr-stop" data-kind="start">
                        <span className="sr-stop__num">1</span>
                        <div className="sr-stop__text"><p className="sr-stop__name">{smartResult.start_label} (Start)</p></div>
                        <span className="sr-stop__time">{smartResult.work_start}</span>
                      </li>
                    ) : null}
                    {smartResult.stops.map((st, idx) => {
                      const badge = priorityBadgeStyle(st.priority.band);
                      const ci = checkIns.get(st.school_id);
                      const isLocked = lockedIds.has(st.school_id);
                      const isOpen = openStop === st.school_id;
                      const leg = idx > 0 || smartResult.start
                        ? st.road_available ? `${km(st.road_meters)} • ${hoursMinutes(st.road_seconds)}` : st.road_status || 'Road access requires verification'
                        : 'First stop';
                      return (
                        <li key={st.school_id} className="sr-stop" data-kind={idx === 0 && !smartResult.start_label ? 'start' : undefined} data-priority={(st.priority?.band ?? 'routine') !== 'routine' || undefined}>
                          <span className="sr-stop__num">{smartResult.start_label ? st.order + 1 : st.order}</span>
                          <div className="sr-stop__text">
                            <p className="sr-stop__name" title={`${st.school_name} (${badge.label})`}>{st.school_name}<span className="sr-only"> ({badge.label})</span></p>
                            <p className="sr-stop__meta">{leg}</p>
                            {st.conflict ? (
                              <p className="sr-stop__conflict"><AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" /> {st.conflict}</p>
                            ) : null}
                          </div>
                          <span className="sr-stop__time">{st.arrival} – {st.departure}</span>
                          <span className="sr-stop__tools">
                            {fieldDay.running && !ci?.arrivedAt ? (
                              <button type="button" disabled={busy} onClick={() => void recordFieldDay('arrive', st.school_id)} className="sr-stop__check">Arrived</button>
                            ) : null}
                            {fieldDay.running && ci?.arrivedAt && !ci.leftAt ? (
                              <button type="button" disabled={busy} onClick={() => void recordFieldDay('leave', st.school_id)} className="sr-stop__check">Leaving</button>
                            ) : null}
                            <button type="button" aria-expanded={isOpen} aria-label={`Actions for ${st.school_name}`} onClick={() => setOpenStop(isOpen ? '' : st.school_id)} className="sr-stop__more">
                              <MoreVertical className="h-4 w-4" aria-hidden="true" />
                            </button>
                          </span>
                          {isOpen ? (
                            <div className="sr-stop__actions">
                              <span className="text-[11px] text-[var(--edify-text-muted)]">
                                ID {st.school_code} · {st.district} · Visit {st.visit_minutes}m
                              </span>
                              <button type="button" disabled={busy || idx === 0} onClick={() => moveStop(idx, -1)} aria-label={`Move ${st.school_name} earlier`}><ArrowUp className="h-3.5 w-3.5" aria-hidden="true" /></button>
                              <button type="button" disabled={busy || idx === smartResult.stops.length - 1} onClick={() => moveStop(idx, 1)} aria-label={`Move ${st.school_name} later`}><ArrowDown className="h-3.5 w-3.5" aria-hidden="true" /></button>
                              <button type="button" onClick={() => toggleLock(st.school_id)} aria-pressed={isLocked} aria-label={isLocked ? `Unlock ${st.school_name}` : `Lock ${st.school_name} position`}>
                                {isLocked ? <Lock className="h-3.5 w-3.5" aria-hidden="true" /> : <Unlock className="h-3.5 w-3.5" aria-hidden="true" />}
                              </button>
                              {smartResult.stops.length > 1 ? <button type="button" onClick={() => removeStop(st.school_id)}>Remove</button> : null}
                              <button type="button" onClick={() => void openInAppDirections([st.school_id])}><Navigation className="h-3 w-3" aria-hidden="true" /> Navigate</button>
                            </div>
                          ) : null}
                        </li>
                      );
                    })}
                    {smartResult.end_label ? (
                      <li className="sr-stop" data-kind="end">
                        <span className="sr-stop__num"><Flag className="h-3.5 w-3.5" aria-hidden="true" /></span>
                        <div className="sr-stop__text">
                          <p className="sr-stop__name">Return to {smartResult.end_label}</p>
                          {smartResult.return_leg_meters ? <p className="sr-stop__meta">{km(smartResult.return_leg_meters)} • {hoursMinutes(smartResult.return_leg_seconds ?? 0)}</p> : null}
                        </div>
                      </li>
                    ) : null}
                  </ol>
                ) : (
                  <p className="rounded-[12px] border border-dashed border-slate-200 py-8 text-center text-[13px] text-[var(--edify-text-muted)]">
                    No school visits scheduled on this date. Pick another date above or add a nearby eligible school below.
                  </p>
                )}

                {/* Excluded Schools (Missing GPS / Unroutable / Exceeds Working Hours) */}
                {smartResult && smartResult.excluded.length > 0 ? (
                  <div className="space-y-1.5 rounded-[12px] border border-amber-200 bg-amber-50/70 p-3 text-[12px] text-amber-950">
                    <p className="font-bold">Excluded Schools ({smartResult.excluded.length})</p>
                    {smartResult.excluded.map((ex) => (
                      <div key={ex.school_id} className="flex flex-wrap items-center justify-between gap-2 rounded-[8px] bg-white/85 px-2.5 py-1.5">
                        <div className="min-w-0 flex-1">
                          <p className="font-semibold">
                            {ex.school_name} <span className="font-normal text-slate-500">ID {ex.school_code}</span>
                          </p>
                          <p className="text-[11px] text-amber-900">{ex.reason}</p>
                        </div>
                        {ex.reason_code === 'missing_gps' || ex.reason_code === 'invalid_gps' ? (
                          <button
                            type="button"
                            data-action="add-school-gps"
                            onClick={() =>
                              setGpsModalTarget({
                                schoolId: ex.school_id,
                                schoolCode: ex.school_code,
                                schoolName: ex.school_name,
                                existingPoint: null,
                                baseVersion: 0,
                              })
                            }
                            className="inline-flex h-7 shrink-0 items-center gap-1 rounded-[7px] bg-[var(--brand-primary)] px-2.5 text-[11px] font-bold text-white hover:bg-[var(--brand-primary-hover)]"
                          >
                            <LocateFixed className="h-3 w-3" aria-hidden="true" /> Add School GPS
                          </button>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}

                {/* Primary Right-Panel Action Bar: 100% In-App Get Directions + Re-optimize / Revert */}
                <div className="sr-list-actions">
                  <button type="button" disabled={busy || !(smartResult?.stops.length)} data-action="get-directions-in-app" onClick={() => void openInAppDirections((smartResult?.stops ?? []).map((s) => s.school_id))} data-lead="">
                    <Navigation className="h-3.5 w-3.5" aria-hidden="true" /> Get Directions
                  </button>
                  <button type="button" disabled={busy || selectedSchoolIds.length === 0} onClick={() => void runOptimize()}>
                    <Sparkles className="h-3.5 w-3.5" aria-hidden="true" /> Re-optimize
                  </button>
                  <button type="button" disabled={busy || originalOrder.length === 0} onClick={() => void runOptimize(originalOrder, 'as_given')}>
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Revert
                  </button>
                </div>
              </>
            )}
            </div>
            {/* The phone's two main actions stay within reach. */}
            <div className="sr-sheet-actions">
              <button type="button" disabled={busy || selectedSchoolIds.length === 0} onClick={() => void runOptimize()} className="inline-flex h-11 items-center justify-center gap-1.5 rounded-[10px] border border-[var(--brand-primary)] text-[13px] font-bold text-[var(--brand-primary)] disabled:opacity-45">
                <Sparkles className="h-4 w-4" aria-hidden="true" /> Optimize Route
              </button>
              {fieldDay.running ? (
                <button type="button" disabled={busy} onClick={() => void recordFieldDay('end')} className="inline-flex h-11 items-center justify-center gap-1.5 rounded-[10px] bg-emerald-600 text-[13px] font-bold text-white">
                  <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> End Field Day
                </button>
              ) : (
                <button type="button" disabled={busy || !fieldDay.canStart || !(smartResult?.stops.length)} onClick={() => void recordFieldDay('start')} className="inline-flex h-11 items-center justify-center gap-1.5 rounded-[10px] bg-[var(--brand-primary)] text-[13px] font-bold text-white disabled:opacity-45">
                  <Navigation className="h-4 w-4" aria-hidden="true" /> Start Field Day
                </button>
              )}
            </div>
          </aside>
        ) : null}

        <RouteBottomRow
        result={smartResult}
        options={options}
        comparing={comparing}
        canCompare={selectedSchoolIds.length > 0 && !busy}
        activeMode={mode}
        onCompare={() => void compareRoutes()}
        onUse={(chosen) => {
          setMode(chosen);
          void runOptimize(undefined, chosen);
        }}
                reportCount={roadConditions.length}
          onReport={() => setShowReportModal(true)}
        />
      </div>

      {/* Schools Near Your Route */}
      <div className="mt-5">
        <NearbyCard
          suggestions={day.suggestions}
          onAdd={addHref}
          onFocus={onPickPin}
          around={focus}
          onViewAll={() => setAllNearby(!allNearby)}
          showAll={allNearby}
          inRoute={stopIdSet}
        />
      </div>

      {/* Staff Road Condition Report Modal (Section 7) */}
      {showReportModal ? (
        <RoadConditionModal
          defaultPoint={smartResult?.stops[0]?.point ?? { lat: 0.3476, lng: 32.5825 }}
          onClose={() => setShowReportModal(false)}
          onCreated={(rep) => {
            setRoadConditions((prev) => [rep, ...prev]);
            setShowReportModal(false);
            setMessage(`Road condition report recorded for "${rep.road_name}" (status: unverified staff report).`);
          }}
        />
      ) : null}

      {/* Mobile-First School GPS Coordinate Capture Modal (Sections 1–8) */}
      {gpsModalTarget ? (
        <GpsCaptureModal
          schoolId={gpsModalTarget.schoolId}
          schoolCode={gpsModalTarget.schoolCode}
          schoolName={gpsModalTarget.schoolName}
          existingPoint={gpsModalTarget.existingPoint}
          baseVersion={gpsModalTarget.baseVersion}
          capturedByName={ownerMeta.name || 'Authenticated Staff'}
          onClose={() => setGpsModalTarget(null)}
          onSaved={(res) => {
            setGpsModalTarget(null);
            setMessage(res.message);
            if (res.outcome === 'saved') {
              void runOptimize();
              router.refresh();
            }
          }}
        />
      ) : null}
    </div>
  );
}

function SchoolPopupCard({
  pin,
  pair,
  onClose,
  onSelectForRoute,
  onInAppDirections,
  onCaptureGps,
  inRoute,
  addHref,
}: {
  pin: SchoolPin;
  pair: GetSchoolDistanceResponse | null;
  onClose: () => void;
  onSelectForRoute: () => void;
  onInAppDirections: () => void;
  onCaptureGps: () => void;
  inRoute: boolean;
  addHref: string;
}) {
  const leg = legFigures(pair?.leg);
  return (
    <div className="absolute left-3 top-3 z-20 w-[min(340px,calc(100%-24px))] rounded-[14px] border border-slate-200 bg-white p-4 shadow-xl" role="dialog" aria-label={pin.name}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[15px] font-bold leading-snug text-slate-900">{pin.name}</p>
          <p className="mt-0.5 text-[12px] text-slate-500">
            ID {pin.code} · {pin.district || 'District not set'}
            {pin.cluster ? ` · ${pin.cluster}` : ''}
          </p>
          <p className="mt-1 text-[12px] text-slate-500">
            {pin.category} · {pin.locationStatus === 'verified' ? 'Verified GPS' : 'Directory GPS (unverified)'}
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-800" aria-label="Close">
          ✕
        </button>
      </div>
      {pair && leg ? (
        <p className="mt-2.5 rounded-[8px] bg-slate-50 px-2.5 py-1.5 text-[12px] text-slate-700">
          From {pair.from?.name}: {pair.leg?.roadAvailable ? `${km(leg.meters)} by road · ${hoursMinutes(leg.seconds)}` : 'Road access requires verification'}
        </p>
      ) : null}
      <div className="mt-3 grid grid-cols-2 gap-2 text-[13px] font-semibold">
        {pin.canOpenProfile ? (
          <Link href={`/schools/${encodeURIComponent(pin.schoolId)}`} className="flex h-9 items-center justify-center rounded-[8px] border border-slate-300 text-slate-700 hover:bg-slate-50">
            View School
          </Link>
        ) : null}
        {!inRoute ? (
          <button type="button" onClick={onSelectForRoute} className="h-9 rounded-[8px] border border-[var(--brand-primary)] text-[var(--brand-primary)] hover:bg-blue-50">
            Add to Route
          </button>
        ) : null}
        {pin.status !== 'planned' && pin.status !== 'completed' ? (
          <Link href={addHref} className="flex h-9 items-center justify-center rounded-[8px] border border-[var(--brand-primary)] text-[var(--brand-primary)] hover:bg-blue-50">
            Add to Plan
          </Link>
        ) : null}
        <button
          type="button"
          data-action="popup-gps-capture"
          onClick={onCaptureGps}
          className="flex h-9 items-center justify-center gap-1 rounded-[8px] border border-slate-300 text-slate-700 hover:bg-slate-50"
        >
          <LocateFixed className="h-3.5 w-3.5" aria-hidden="true" />
          {pin.point ? 'Update GPS' : 'Add School GPS'}
        </button>
        {pin.point ? (
          <button
            type="button"
            onClick={onInAppDirections}
            className="col-span-2 flex h-9 items-center justify-center gap-1 rounded-[8px] bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-primary-hover)]"
          >
            <Navigation className="h-3.5 w-3.5" aria-hidden="true" /> Get Directions
          </button>
        ) : null}
      </div>
    </div>
  );
}

function RoadConditionModal({
  defaultPoint,
  onClose,
  onCreated,
}: {
  defaultPoint: LatLngPoint;
  onClose: () => void;
  onCreated: (report: RoadConditionReportData) => void;
}) {
  const [roadName, setRoadName] = useState('');
  const [category, setCategory] = useState('road_closed');
  const [impact, setImpact] = useState('impassable');
  const [notes, setNotes] = useState('');
  const [lat, setLat] = useState(defaultPoint.lat.toFixed(5));
  const [lng, setLng] = useState(defaultPoint.lng.toFixed(5));
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setErr('');
    try {
      const res = await smartApi<{ report: RoadConditionReportData }>('smart-route/road-conditions', {
        method: 'POST',
        body: JSON.stringify({
          road_name: roadName,
          category,
          impact_level: impact,
          notes,
          lat: Number(lat),
          lng: Number(lng),
          radius_meters: 1500,
          expires_hours: 72,
        }),
      });
      onCreated(res.report);
    } catch (error) {
      setErr(error instanceof Error ? error.message : 'Could not save road condition report.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/50 p-4" role="dialog" aria-modal="true" aria-label="Report road condition">
      <form onSubmit={submit} className="w-full max-w-md space-y-3.5 rounded-[16px] bg-white p-5 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-[17px] font-bold text-[#0f172a]">Report Road Condition</h2>
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-800" aria-label="Close modal">
            ✕
          </button>
        </div>
        <p className="text-[12px] text-slate-600">
          Staff reports are recorded as <strong>Unverified</strong> until reviewed by an authorized supervisor and warn field staff near this road segment.
        </p>
        <label className="block text-[12px] font-semibold text-slate-700">
          Road / Bridge / Segment Name *
          <input
            type="text"
            required
            value={roadName}
            onChange={(e) => setRoadName(e.target.value)}
            placeholder="e.g., Sezibwa Bridge, Mukono–Kayunga Rd"
            className="mt-1 h-9 w-full rounded-[8px] border border-[var(--edify-border)] px-3 text-[13px]"
          />
        </label>
        <div className="grid grid-cols-2 gap-2.5">
          <label className="block text-[12px] font-semibold text-slate-700">
            Condition Category
            <select value={category} onChange={(e) => setCategory(e.target.value)} className="mt-1 h-9 w-full rounded-[8px] border border-[var(--edify-border)] px-2 text-[13px]">
              <option value="road_closed">Road closed</option>
              <option value="road_flooded">Road flooded</option>
              <option value="bridge_damaged">Bridge damaged</option>
              <option value="under_construction">Under construction</option>
              <option value="poor_condition">Poor road condition</option>
              <option value="severe_congestion">Severe congestion</option>
              <option value="road_reopened">Road reopened</option>
            </select>
          </label>
          <label className="block text-[12px] font-semibold text-slate-700">
            Travel Impact
            <select value={impact} onChange={(e) => setImpact(e.target.value)} className="mt-1 h-9 w-full rounded-[8px] border border-[var(--edify-border)] px-2 text-[13px]">
              <option value="impassable">Impassable</option>
              <option value="delay">Major delay</option>
              <option value="advisory">Advisory</option>
            </select>
          </label>
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <label className="block text-[12px] font-semibold text-slate-700">
            Latitude
            <input type="text" value={lat} onChange={(e) => setLat(e.target.value)} className="mt-1 h-9 w-full rounded-[8px] border border-[var(--edify-border)] px-3 text-[13px]" />
          </label>
          <label className="block text-[12px] font-semibold text-slate-700">
            Longitude
            <input type="text" value={lng} onChange={(e) => setLng(e.target.value)} className="mt-1 h-9 w-full rounded-[8px] border border-[var(--edify-border)] px-3 text-[13px]" />
          </label>
        </div>
        <label className="block text-[12px] font-semibold text-slate-700">
          Field Notes
          <textarea
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Describe detour or safety guidance…"
            className="mt-1 w-full rounded-[8px] border border-[var(--edify-border)] p-2.5 text-[13px]"
          />
        </label>
        {err ? <p className="text-[12px] font-semibold text-red-700">{err}</p> : null}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="h-9 rounded-[8px] border border-[var(--edify-border)] px-4 text-[13px] font-semibold text-slate-700">
            Cancel
          </button>
          <button type="submit" disabled={submitting} className="h-9 rounded-[8px] bg-[var(--brand-primary)] px-4 text-[13px] font-semibold text-white">
            {submitting ? 'Submitting…' : 'Submit Report'}
          </button>
        </div>
      </form>
    </div>
  );
}
