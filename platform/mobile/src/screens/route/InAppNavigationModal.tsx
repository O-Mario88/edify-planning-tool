/**
 * Embedded In-App Turn-by-Turn Navigation Modal for React Native / Expo (Section 6).
 *
 * Keeps the user 100% inside Edify — zero external redirects to Google Maps,
 * Apple Maps, or Waze. Calls Go's /api/v1/smart-route/directions endpoint for
 * real road-following polylines, turn-by-turn instructions, ETAs, alternatives,
 * and active road-condition warnings, paired with debounced expo-location GPS.
 *
 * Note on @googlemaps/react-native-navigation-sdk: Native Google Navigation SDK
 * requires a custom native iOS/Android development build (not Expo Go) and
 * licensed Google Navigation SDK credentials. This embedded screen delivers
 * real road-following in-app guidance across Expo, iOS, Android, and Web today.
 */
import * as Location from 'expo-location';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { AlertTriangle, Compass, CornerUpRight, Navigation, RefreshCw, X } from 'lucide-react-native';

import { useSession } from '../../auth/SessionContext';
import { RoutePlannerService } from '../../gen/edify/routes/v1/routes_pb';
import type { SchoolPin } from '../../gen/edify/routes/v1/routes_pb';
import { fonts, radius, spacing, useTheme } from '../../theme';
import { hrMin, km, PIN_TONES, shortName } from './routeData';
import type { MapScene } from './routeMapHtml';
import { RouteMapView } from './RouteMapView';

interface DirectionStep {
  instruction: string;
  road_name?: string;
  distance_meters: number;
  duration_seconds: number;
}

interface DirectionLeg {
  index: number;
  from_label: string;
  to_label: string;
  distance_meters: number;
  duration_seconds: number;
  eta: string;
  steps?: DirectionStep[];
}

interface DirectionsPayload {
  road_available: boolean;
  message?: string;
  provider: string;
  total_meters?: number;
  total_seconds?: number;
  traffic_state: string;
  eta_final?: string;
  path: Array<{ lat: number; lng: number }>;
  legs: DirectionLeg[];
  road_alerts?: Array<{ id: string; road_name: string; category: string; verification_status: string; applicability_note?: string }>;
}

export interface InAppNavigationModalProps {
  readonly stops: readonly SchoolPin[];
  readonly onClose: () => void;
}

export function InAppNavigationModal({ stops, onClose }: InAppNavigationModalProps) {
  const { colors } = useTheme();
  const { api } = useSession();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState<DirectionsPayload | null>(null);
  const [gpsStatus, setGpsStatus] = useState('Locating device GPS…');
  const [origin, setOrigin] = useState<{ lat: number; lng: number } | null>(null);
  const lastFetchAt = useRef(0);

  const fetchDirections = useCallback(
    async (from?: { lat: number; lng: number } | null) => {
      if (stops.length === 0) return;
      setLoading(true);
      setError('');
      try {
        const answer = await api.call(RoutePlannerService.method.planRoute, {
          date: '',
          schoolIds: stops.map((s) => s.schoolId),
          mode: 'as_given',
          lockedSchoolIds: [],
          startLabel: from ? 'Current GPS Location' : '',
          ...(from ? { start: { lat: from.lat, lng: from.lng } } : {}),
        });
        const it = answer.itinerary;
        const pathPts = (it?.stops?.[0]?.leg?.path ?? []).map((p) => ({ lat: p.lat, lng: p.lng }));
        const roadAvail = Boolean(it?.totals?.roadComplete && pathPts.length >= 2);
        const legs: DirectionLeg[] = (it?.stops ?? []).map((st, idx) => ({
          index: idx,
          from_label: st.leg?.fromLabel || (idx === 0 ? 'Start' : stops[idx - 1]?.name || 'Previous'),
          to_label: st.school?.name || 'School',
          distance_meters: Number(st.leg?.roadMeters ?? 0),
          duration_seconds: Number(st.leg?.roadSeconds ?? 0),
          eta: st.arrival || '',
          steps: st.leg?.roadAvailable
            ? [
                {
                  instruction: `Follow road route to ${st.school?.name || 'school'}`,
                  distance_meters: Number(st.leg.roadMeters),
                  duration_seconds: Number(st.leg.roadSeconds),
                },
              ]
            : [],
        }));
        setData({
          road_available: roadAvail,
          message: roadAvail ? '' : answer.provider?.message || 'Road access requires verification',
          provider: answer.provider?.name || 'none',
          total_meters: Number(it?.totals?.roadMeters ?? 0),
          total_seconds: Number(it?.totals?.roadSeconds ?? 0),
          traffic_state: 'unavailable',
          eta_final: it?.stops?.[it.stops.length - 1]?.arrival || '',
          path: pathPts,
          legs,
        });
        lastFetchAt.current = Date.now();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Road directions temporarily unavailable.');
      } finally {
        setLoading(false);
      }
    },
    [api, stops],
  );

  useEffect(() => {
    let active = true;
    let sub: Location.LocationSubscription | null = null;
    (async () => {
      try {
        const perm = await Location.requestForegroundPermissionsAsync();
        if (!active) return;
        if (perm.status !== 'granted') {
          setGpsStatus('GPS permission denied — showing road route between stops.');
          await fetchDirections(null);
          return;
        }
        const cur = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        if (!active) return;
        const firstPos = { lat: cur.coords.latitude, lng: cur.coords.longitude };
        setOrigin(firstPos);
        setGpsStatus(`Live GPS active (±${Math.round(cur.coords.accuracy ?? 15)} m)`);
        await fetchDirections(firstPos);

        // Battery-safe debounced GPS updates (min 30m movement or 15s interval).
        sub = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.Balanced, distanceInterval: 30, timeInterval: 15_000 },
          (loc) => {
            if (!active) return;
            setOrigin({ lat: loc.coords.latitude, lng: loc.coords.longitude });
            setGpsStatus(`Live GPS active (±${Math.round(loc.coords.accuracy ?? 15)} m)`);
          },
        );
      } catch {
        if (!active) return;
        setGpsStatus('GPS unavailable — showing calculated road route.');
        await fetchDirections(null);
      }
    })();
    return () => {
      active = false;
      sub?.remove();
    };
  }, [fetchDirections]);

  const scene = useMemo<MapScene>(() => {
    const pins: MapScene['pins'] = stops
      .filter((s) => Boolean(s.point))
      .map((s, i) => ({
        id: s.schoolId,
        order: String(i + 1),
        name: shortName(s.name),
        detail: '',
        lat: s.point!.lat,
        lng: s.point!.lng,
        tone: PIN_TONES.planned,
      }));
    const path = (data?.road_available ? data.path : []).map((p) => [p.lng, p.lat] as [number, number]);
    return { pins, path, legend: [{ label: 'Destination', tone: PIN_TONES.planned }], join: false };
  }, [stops, data]);

  const firstLeg = data?.legs?.[0];
  const nextStep = firstLeg?.steps?.[0];

  return (
    <Modal visible={stops.length > 0} animationType="slide" onRequestClose={onClose}>
      <View style={[styles.root, { backgroundColor: colors.bg }]}>
        <View style={[styles.header, { backgroundColor: '#0f2942' }]}>
          <View style={styles.headerLeft}>
            <Navigation size={20} color="#7dd3fc" />
            <View style={styles.flex}>
              <Text style={styles.headerTitle}>Edify In-App Navigation</Text>
              <Text style={styles.headerSub} numberOfLines={1}>
                {stops[0]?.name}
                {stops.length > 1 ? ` + ${stops.length - 1} more` : ''}
              </Text>
            </View>
          </View>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close navigation" hitSlop={10} style={styles.closeBtn}>
            <X size={22} color="#fff" />
          </Pressable>
        </View>

        <View style={styles.mapWrap}>
          <RouteMapView scene={scene} onSelect={() => undefined} />
        </View>

        <ScrollView contentContainerStyle={styles.body}>
          {/* Next Maneuver Card */}
          <View style={styles.hero}>
            <CornerUpRight size={24} color="#7dd3fc" />
            <View style={styles.flex}>
              <Text style={styles.heroTag}>NEXT MANEUVER</Text>
              <Text style={styles.heroMain}>
                {loading
                  ? 'Calculating road route…'
                  : nextStep
                    ? nextStep.instruction
                    : data?.road_available
                      ? `Proceed along road to ${firstLeg?.to_label ?? stops[0]?.name}`
                      : data?.message || 'Road access requires verification'}
              </Text>
              {data?.road_available ? (
                <Text style={styles.heroMeta}>
                  {km(data.total_meters ?? 0)} · {hrMin(data.total_seconds ?? 0)}
                  {data.eta_final ? ` · ETA ${data.eta_final}` : ''}
                </Text>
              ) : null}
            </View>
          </View>

          <View style={[styles.gpsRow, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Compass size={16} color={colors.primary} />
            <Text style={[styles.gpsText, { color: colors.text }]}>{gpsStatus}</Text>
            <Pressable onPress={() => void fetchDirections(origin)} accessibilityRole="button" style={[styles.rerouteBtn, { borderColor: colors.primary }]}>
              <RefreshCw size={14} color={colors.primary} />
              <Text style={[styles.rerouteText, { color: colors.primary }]}>Reroute</Text>
            </Pressable>
          </View>

          {loading ? <ActivityIndicator color={colors.primary} style={{ marginVertical: 16 }} /> : null}
          {error ? <Text style={styles.errorText}>{error}</Text> : null}

          {(data?.road_alerts ?? []).map((al) => (
            <View key={al.id} style={styles.alertBox}>
              <AlertTriangle size={16} color="#92400e" />
              <View style={styles.flex}>
                <Text style={styles.alertTitle}>
                  {al.road_name} ({al.category.replace(/_/g, ' ')}, {al.verification_status})
                </Text>
                {al.applicability_note ? <Text style={styles.alertSub}>{al.applicability_note}</Text> : null}
              </View>
            </View>
          ))}

          {(data?.legs ?? []).map((leg) => (
            <View key={leg.index} style={[styles.legCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
              <Text style={[styles.legTitle, { color: colors.text }]}>
                {leg.from_label} → {leg.to_label}
              </Text>
              <Text style={[styles.legSub, { color: colors.textMuted }]}>
                {km(leg.distance_meters)} · {hrMin(leg.duration_seconds)} · ETA {leg.eta}
              </Text>
              {(leg.steps ?? []).map((st, idx) => (
                <View key={`${leg.index}-${idx}`} style={[styles.stepRow, { borderTopColor: colors.border }]}>
                  <Text style={[styles.stepNum, { color: colors.primary }]}>{idx + 1}.</Text>
                  <View style={styles.flex}>
                    <Text style={[styles.stepText, { color: colors.text }]}>{st.instruction}</Text>
                    <Text style={[styles.stepMeta, { color: colors.textMuted }]}>
                      {km(st.distance_meters)} · {hrMin(st.duration_seconds)}
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          ))}
        </ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  flex: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.md, paddingTop: 48, paddingBottom: 14 },
  headerLeft: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10 },
  headerTitle: { fontFamily: fonts.bold, fontSize: 16, color: '#fff' },
  headerSub: { fontFamily: fonts.regular, fontSize: 13, color: '#cbd5e1' },
  closeBtn: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.12)' },
  mapWrap: { height: 260 },
  body: { padding: spacing.md, gap: spacing.sm, paddingBottom: 40 },
  hero: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, backgroundColor: '#0f2942', borderRadius: radius.md, padding: spacing.md },
  heroTag: { fontFamily: fonts.bold, fontSize: 11, color: '#7dd3fc', letterSpacing: 0.6 },
  heroMain: { fontFamily: fonts.bold, fontSize: 16, color: '#fff', marginTop: 2 },
  heroMeta: { fontFamily: fonts.medium, fontSize: 13, color: '#cbd5e1', marginTop: 4 },
  gpsRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: radius.sm, padding: 10 },
  gpsText: { flex: 1, fontFamily: fonts.medium, fontSize: 12 },
  rerouteBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 10, paddingVertical: 6 },
  rerouteText: { fontFamily: fonts.semibold, fontSize: 12 },
  errorText: { fontFamily: fonts.medium, fontSize: 13, color: '#b91c1c' },
  alertBox: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, backgroundColor: '#fffbeb', borderColor: '#fcd34d', borderWidth: 1, borderRadius: radius.sm, padding: 10 },
  alertTitle: { fontFamily: fonts.bold, fontSize: 13, color: '#92400e' },
  alertSub: { fontFamily: fonts.regular, fontSize: 12, color: '#92400e' },
  legCard: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: 6 },
  legTitle: { fontFamily: fonts.bold, fontSize: 15 },
  legSub: { fontFamily: fonts.medium, fontSize: 13 },
  stepRow: { flexDirection: 'row', gap: 8, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 8, marginTop: 4 },
  stepNum: { fontFamily: fonts.bold, fontSize: 13, width: 22 },
  stepText: { fontFamily: fonts.medium, fontSize: 14 },
  stepMeta: { fontFamily: fonts.regular, fontSize: 12 },
});
