/**
 * The Smart Route Planner in the app (owner design, 2026-11-14): the
 * planner (map, recommended route, Optimise Route) and the Route Details
 * (itinerary, nearby schools, directions, the field day). Re-ordering and
 * optimising change this route only; Add to Plan opens the existing Schedule
 * visit drawer, which is the only way a school joins the official plan.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Alert, Linking, Platform, StyleSheet, Text, View } from 'react-native';

import { ApiError } from '../../api/connect';
import { useSession } from '../../auth/SessionContext';
import { RoutePlannerService } from '../../gen/edify/routes/v1/routes_pb';
import type { GetFieldDayResponse, Itinerary, SchoolPin } from '../../gen/edify/routes/v1/routes_pb';
import { fonts, spacing, useTheme } from '../../theme';
import { PlanningDrawer } from '../../ui/planning/PlanningDrawer';
import { PIN_TONES, ROUTE_DETAILS_URL, dateOf, directionsUrl, legText, placedStops, shortName } from './routeData';
import type { MapsApp } from './routeData';
import type { MapScene } from './routeMapHtml';
import { RouteDetailsScreen, RoutePlannerScreen } from './RouteScreens';

export interface RouteFlowProps {
  readonly url: string;
  readonly onOpen: (url: string, label: string) => void;
  readonly onOpenSchool: (schoolId: string) => void;
}

function today(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

/** The map's pins for an itinerary, as the mobile design draws them. */
export function sceneOf(itinerary: Itinerary | undefined): MapScene {
  const stops = itinerary?.stops ?? [];
  const pins = stops
    .filter((s) => s.school?.point)
    .map((s) => {
      const tone = s.school?.status === 'completed' ? PIN_TONES.completed : s.kind === 'recommended' ? PIN_TONES.suggested : PIN_TONES.planned;
      const leg = legText(s.leg);
      return {
        id: s.school!.schoolId,
        order: String(s.order),
        name: shortName(s.school!.name),
        detail: leg ? `(${leg.replace(' (straight line)', ', straight line')})` : '',
        lat: s.school!.point!.lat,
        lng: s.school!.point!.lng,
        tone,
      };
    });
  const path = (stops[0]?.leg?.path ?? []).map((p) => [p.lng, p.lat] as [number, number]);
  // A legend only explains pins that are there.
  const legend: MapScene['legend'] = pins.length ? [{ label: 'Planned School', tone: PIN_TONES.planned }] : [];
  if (stops.some((s) => s.kind === 'recommended')) legend.push({ label: 'Recommended', tone: PIN_TONES.suggested });
  if (stops.some((s) => s.school?.status === 'completed')) legend.push({ label: 'Completed', tone: PIN_TONES.completed });
  return { pins, path, legend };
}

export function RouteFlow({ url, onOpen, onOpenSchool }: RouteFlowProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [date, setDateState] = useState(() => dateOf(url) || today());
  // The day rides in the route's URL, so coming back from a school keeps it.
  const setDate = (next: string) => {
    setDateState(next);
    onOpen(`${url.startsWith(ROUTE_DETAILS_URL) ? ROUTE_DETAILS_URL : 'route:planner'}?date=${next}`, 'Smart Route Planner');
  };
  const [district, setDistrict] = useState('');
  const [day, setDay] = useState<GetFieldDayResponse | null>(null);
  const [itinerary, setItinerary] = useState<Itinerary | undefined>(undefined);
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [locked, setLocked] = useState<ReadonlySet<string>>(new Set());
  const [scheduling, setScheduling] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [isFieldDay, setIsFieldDay] = useState(false);
  const isDetails = url.startsWith(ROUTE_DETAILS_URL);
  const dated = (base: string) => `${base}?date=${date}`;

  const load = useCallback(async () => {
    setError('');
    try {
      const answer = await api.call(RoutePlannerService.method.getFieldDay, { date, districtId: district, clusterId: '' });
      setDay(answer);
      setItinerary(answer.recommended);
      setNotice(answer.provider?.message ?? '');
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The route could not be loaded. Please try again.');
    }
  }, [api, date, district]);

  useEffect(() => {
    void load();
  }, [load]);

  const ids = (it: Itinerary | undefined) => (it?.stops ?? []).map((s) => s.school!.schoolId).concat((it?.unplaced ?? []).map((p) => p.schoolId));

  const plan = useCallback(
    async (schoolIds: string[], mode: 'fastest' | 'as_given', locks: ReadonlySet<string>) => {
      if (schoolIds.length === 0) return;
      setIsBusy(true);
      try {
        const answer = await api.call(RoutePlannerService.method.planRoute, { date, schoolIds, mode, lockedSchoolIds: [...locks], startLabel: '' });
        setItinerary(answer.itinerary);
        setNotice(answer.provider?.message ?? '');
      } catch (cause) {
        setNotice(cause instanceof ApiError ? cause.message : 'The route could not be worked out.');
      } finally {
        setIsBusy(false);
      }
    },
    [api, date],
  );

  const scene = useMemo(() => sceneOf(itinerary), [itinerary]);
  const areaLabel = district ? (day?.districts.find((d) => d.value === district)?.label ?? '') : day?.areaLabel ?? '';

  // Directions in the person's own maps app: they choose which.
  const directions = useCallback((stops: readonly SchoolPin[]) => {
    const go = (app: MapsApp) => {
      const target = directionsUrl(stops, app);
      if (target) void Linking.openURL(target);
    };
    if (Platform.OS === 'web') return go('google');
    Alert.alert('Get directions', 'Open the route in your maps app.', [
      { text: 'Google Maps', onPress: () => go('google') },
      ...(Platform.OS === 'ios' ? [{ text: 'Apple Maps', onPress: () => go('apple') }] : []),
      { text: 'Waze', onPress: () => go('waze') },
      { text: 'Cancel', style: 'cancel' as const },
    ]);
  }, []);

  if (error) {
    return (
      <View style={styles.centered}>
        <Text style={[styles.message, { color: colors.text }]}>{error}</Text>
      </View>
    );
  }
  if (!day) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  const common = {
    day,
    itinerary,
    scene,
    date,
    areaLabel,
    notice,
    isBusy,
    onSelectSchool: onOpenSchool,
  };
  const remaining = (itinerary?.stops ?? []).filter((s) => s.school?.status !== 'completed').map((s) => s.school!);

  return (
    <View style={styles.flex}>
      {isDetails ? (
        <RouteDetailsScreen
          {...common}
          locked={locked}
          isFieldDay={isFieldDay}
          onBack={() => onOpen(dated('route:planner'), 'Smart Route Planner')}
          onToggleLock={(id) => {
            const next = new Set(locked);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            setLocked(next);
          }}
          onRecalculate={() => plan(isFieldDay ? remaining.map((s) => s.schoolId) : ids(itinerary), 'fastest', locked)}
          onKeepOrder={() => plan(ids(itinerary), 'as_given', locked)}
          onAddToPlan={(id) => setScheduling(id)}
          onDirections={() => directions(isFieldDay ? remaining : placedStops(itinerary))}
          onStartFieldDay={() => {
            setIsFieldDay(true);
            void load();
          }}
          onRefresh={() => void load()}
        />
      ) : (
        <RoutePlannerScreen
          {...common}
          district={district}
          onDate={setDate}
          onDistrict={setDistrict}
          onOptimise={() => plan(ids(itinerary), 'fastest', locked)}
          onOpenDetails={() => onOpen(dated(ROUTE_DETAILS_URL), 'Route Details')}
        />
      )}
      {scheduling ? (
        <PlanningDrawer
          schoolId={scheduling}
          kind="schedule"
          onClose={() => setScheduling(null)}
          onSaved={(message) => {
            setScheduling(null);
            setNotice(message);
            void load();
          }}
          onOpenWeb={() => setScheduling(null)}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  message: { fontFamily: fonts.medium, fontSize: 15, textAlign: 'center' },
});
