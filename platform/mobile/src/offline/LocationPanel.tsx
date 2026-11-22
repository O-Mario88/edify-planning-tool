/**
 * A school's location on its profile, online or offline (offline capture
 * brief, 2026-11-14, part 2). No coordinates: "GPS Location Not Captured"
 * and Capture School Location. Coordinates: the current location, its
 * latitude and longitude, how sure it is, when it was last verified, the
 * pin, Verify / Replace Location and Get Directions. A capture saved on the
 * phone and not yet accepted shows as its own pin, labelled as such, until
 * the server's answer comes back.
 */
import { create } from '@bufbuild/protobuf';
import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Crosshair, DoorOpen, MapPin, MapPinOff, Navigation } from 'lucide-react-native';

import { SchoolPinSchema } from '../gen/edify/routes/v1/routes_pb';
import { fonts, radius, spacing, useTheme } from '../theme';
import { InAppNavigationModal } from '../screens/route/InAppNavigationModal';
import { PIN_TONES, shortName } from '../screens/route/routeData';
import { RouteMapView } from '../screens/route/RouteMapView';
import type { MapScene } from '../screens/route/routeMapHtml';
import { useOffline } from './OfflineContext';
import { STATUS_TEXT } from './queueLogic';
import type { CachedSchool, CaptureTarget, QueuedCapture } from './store';

const BLUE = PIN_TONES.planned;
const PENDING_TONE = '#f59e0b';

const STATUS: Record<string, string> = {
  verified: 'Verified location',
  recorded: 'From the School Directory (not yet verified)',
  missing: 'No location recorded',
  invalid: 'The recorded location looks wrong',
};

const DAY = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
export const dayOf = (iso: string) => (iso ? DAY.format(new Date(iso)) : '');

/** The queued captures still worth showing on the profile. */
const SHOWN = new Set(['saved_offline', 'pending_sync', 'syncing', 'awaiting_review', 'conflict', 'failed']);

export interface LocationPanelProps {
  readonly school: CachedSchool;
  /** Who verified it last, when known (online). */
  readonly verifiedByName?: string;
  /** Online parts below the panel: nearby schools, review, history. */
  readonly footer?: ReactNode;
  /** Called after a capture is saved, so the screen can read again. */
  readonly onCaptured?: () => void;
  /** The server's word on capturing (online); otherwise the offline pack's. */
  readonly canCapture?: boolean;
}

export function LocationPanel({ school, verifiedByName = '', footer, onCaptured, canCapture: allowed }: LocationPanelProps) {
  const { colors } = useTheme();
  const { store, account, revision, canCapture: packAllows, openCapture } = useOffline();
  const canCapture = (allowed ?? packAllows) && account !== null;
  const [local, setLocal] = useState<QueuedCapture[]>([]);

  useEffect(() => {
    if (!store || !account) return;
    let isCurrent = true;
    void store.captures(account.userId).then((all) => {
      if (isCurrent) setLocal(all.filter((c) => c.schoolId === school.schoolId && SHOWN.has(c.status) && c.kind !== 'confirm'));
    });
    return () => {
      isCurrent = false;
    };
  }, [store, account, revision, school.schoolId]);

  const hasPoint = school.lat !== null && school.lng !== null;
  const waiting = local.find((c) => c.target === 'school' && c.lat !== null && c.status !== 'failed');
  const scene = useMemo<MapScene>(() => {
    const pins: MapScene['pins'] = [];
    if (hasPoint) pins.push({ id: school.schoolId, order: '', name: shortName(school.name), detail: '', lat: school.lat!, lng: school.lng!, tone: BLUE });
    if (school.entranceLat !== null && school.entranceLng !== null) {
      pins.push({ id: `${school.schoolId}:entrance`, order: 'E', name: 'Entrance', detail: '', lat: school.entranceLat, lng: school.entranceLng, tone: PIN_TONES.completed });
    }
    if (waiting) {
      pins.push({ id: `${school.schoolId}:waiting`, order: '', name: 'Not yet accepted', detail: `(${STATUS_TEXT[waiting.status]})`, lat: waiting.lat!, lng: waiting.lng!, tone: PENDING_TONE });
    }
    const legend: MapScene['legend'] = waiting ? [{ label: 'On record', tone: BLUE }, { label: 'Captured, not yet accepted', tone: PENDING_TONE }] : [];
    return { pins, path: [], legend, join: false, primaryId: hasPoint ? school.schoolId : waiting ? `${school.schoolId}:waiting` : undefined };
  }, [school, hasPoint, waiting]);

  const setCapturing = (target: CaptureTarget) => openCapture({ school, target, onDone: (saved) => saved && onCaptured?.() });

  const [navStops, setNavStops] = useState<readonly ReturnType<typeof create<typeof SchoolPinSchema>>[]>([]);

  // In-app directions inside Edify (Section 6 — never opens external maps).
  const directions = () => {
    const at = school.entranceLat !== null ? { lat: school.entranceLat, lng: school.entranceLng! } : { lat: school.lat!, lng: school.lng! };
    setNavStops([create(SchoolPinSchema, { schoolId: school.schoolId, name: school.name, code: school.code, point: at, locationStatus: 'verified' })]);
  };

  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]} accessibilityLabel="School location and directions">
      <View style={styles.titleRow}>
        <View style={styles.title}>
          <MapPin size={20} color={BLUE} />
          <Text style={[styles.titleText, { color: colors.text }]} accessibilityRole="header">
            School Location
          </Text>
        </View>
        {waiting ? (
          <View style={[styles.badge, styles.badgePending]}>
            <Text style={styles.badgePendingText}>Pending Sync</Text>
          </View>
        ) : hasPoint ? (
          <View style={[styles.badge, styles.badgeRecorded]}>
            <Text style={styles.badgeRecordedText}>GPS Recorded</Text>
          </View>
        ) : (
          <View style={[styles.badge, styles.badgeMissing]}>
            <Text style={styles.badgeMissingText}>GPS Missing</Text>
          </View>
        )}
      </View>
      {scene.pins.length ? (
        <View style={[styles.map, { borderColor: colors.border }]}>
          <RouteMapView scene={scene} onSelect={() => undefined} />
        </View>
      ) : null}
      {hasPoint ? (
        <>
          <Fact label="Latitude / Longitude" value={`${school.lat!.toFixed(6)}, ${school.lng!.toFixed(6)}`} />
          <Fact label="Location status" value={`${STATUS[school.locationStatus] ?? school.locationStatus}${school.version > 0 ? ` · version ${school.version}` : ''}`} />
          <Fact
            label="Verification date"
            value={school.verifiedAt ? `${dayOf(school.verifiedAt)}${verifiedByName ? ` by ${verifiedByName}` : ''}` : 'Not yet verified in the field'}
          />
          <Fact label="Source" value={school.locationStatus === 'verified' ? 'Device location services' : 'School Directory'} />
          {school.lastConfirmedAt ? <Fact label="Last checked on a visit" value={dayOf(school.lastConfirmedAt)} /> : null}
          {school.entranceLat !== null ? <Fact label="Entrance" value={`${school.entranceLat.toFixed(6)}, ${school.entranceLng!.toFixed(6)}`} /> : null}
          {school.accessNote ? <Fact label="Directions" value={school.accessNote} /> : null}
          <View style={styles.buttons}>
            {canCapture ? (
              <Pressable onPress={() => setCapturing('school')} style={styles.primary} accessibilityRole="button">
                <Crosshair size={18} color="#fff" />
                <Text style={styles.primaryText}>Update GPS Coordinates</Text>
              </Pressable>
            ) : null}
            <Pressable onPress={directions} style={styles.outline} accessibilityRole="button">
              <Navigation size={18} color={BLUE} />
              <Text style={styles.outlineText}>Get Directions</Text>
            </Pressable>
            {canCapture ? (
              <Pressable onPress={() => setCapturing('entrance')} style={styles.link} accessibilityRole="button">
                <DoorOpen size={16} color={BLUE} />
                <Text style={styles.linkText}>{school.entranceLat !== null ? 'Replace entrance point' : 'Add entrance / road access point'}</Text>
              </Pressable>
            ) : null}
          </View>
        </>
      ) : (
        <View style={styles.none}>
          <View style={styles.noneHeader}>
            <MapPinOff size={22} color="#92400e" />
            <Text style={styles.noneTitle}>No verified GPS location has been recorded for this school.</Text>
          </View>
          <Text style={styles.noneText}>Capture the school&apos;s location while physically at the premises.</Text>
          {canCapture ? (
            <Pressable onPress={() => setCapturing('school')} style={[styles.primary, styles.wide]} accessibilityRole="button">
              <Crosshair size={20} color="#fff" />
              <Text style={styles.primaryText}>Tap to Add GPS Coordinates</Text>
            </Pressable>
          ) : null}
        </View>
      )}
      {local.length ? (
        <View style={styles.queue}>
          {local.map((c) => (
            <Text key={c.id} style={[styles.queueText, { color: c.status === 'failed' ? colors.danger : colors.text }]}>
              {c.target === 'entrance' ? 'Entrance: ' : ''}
              {STATUS_TEXT[c.status]}
              {c.note && c.status !== 'saved_offline' ? ` · ${c.note}` : ''}
            </Text>
          ))}
        </View>
      ) : null}
      {footer}
      {navStops.length > 0 ? <InAppNavigationModal stops={navStops} onClose={() => setNavStops([])} /> : null}
    </View>
  );
}

function Fact({ label, value }: { readonly label: string; readonly value: string }) {
  const { colors } = useTheme();
  return (
    <View>
      <Text style={[styles.label, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.value, { color: colors.text }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: 6, marginTop: spacing.md },
  titleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: spacing.sm },
  title: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  titleText: { fontFamily: fonts.semibold, fontSize: 16 },
  badge: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 3 },
  badgeRecorded: { backgroundColor: '#dcfce7' },
  badgeRecordedText: { fontFamily: fonts.semibold, fontSize: 12, color: '#166534' },
  badgeMissing: { backgroundColor: '#fef3c7' },
  badgeMissingText: { fontFamily: fonts.semibold, fontSize: 12, color: '#92400e' },
  badgePending: { backgroundColor: '#ffedd5' },
  badgePendingText: { fontFamily: fonts.semibold, fontSize: 12, color: '#9a3412' },
  map: { height: 220, borderRadius: radius.sm, borderWidth: 1, overflow: 'hidden', marginBottom: spacing.sm },
  label: { fontFamily: fonts.regular, fontSize: 13, marginTop: spacing.xs },
  value: { fontFamily: fonts.medium, fontSize: 14 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md, alignItems: 'center' },
  primary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: BLUE, borderRadius: radius.sm, paddingHorizontal: 16, minHeight: 48 },
  primaryText: { fontFamily: fonts.semibold, fontSize: 16, color: '#fff' },
  wide: { alignSelf: 'stretch', minHeight: 54, marginTop: spacing.sm },
  outline: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1.5, borderColor: BLUE, borderRadius: radius.sm, paddingHorizontal: 14, minHeight: 48 },
  outlineText: { fontFamily: fonts.semibold, fontSize: 15, color: BLUE },
  link: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44 },
  linkText: { fontFamily: fonts.semibold, fontSize: 15, color: BLUE },
  none: { backgroundColor: '#fffbeb', borderRadius: radius.sm, padding: spacing.md, gap: 6 },
  noneHeader: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  noneTitle: { flex: 1, fontFamily: fonts.semibold, fontSize: 15, color: '#92400e' },
  noneText: { fontFamily: fonts.regular, fontSize: 14, color: '#92400e' },
  queue: { backgroundColor: '#fff7ed', borderRadius: radius.sm, padding: spacing.sm, gap: 4, marginTop: spacing.sm },
  queueText: { fontFamily: fonts.medium, fontSize: 14 },
});
