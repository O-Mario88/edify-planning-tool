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
import { Crosshair, DoorOpen, MapPin, Navigation } from 'lucide-react-native';

import { SchoolPinSchema } from '../gen/edify/routes/v1/routes_pb';
import { fonts, radius, spacing, useTheme } from '../theme';
import { chooseDirections } from '../screens/route/directions';
import { PIN_TONES, shortName } from '../screens/route/routeData';
import { RouteMapView } from '../screens/route/RouteMapView';
import type { MapScene } from '../screens/route/routeMapHtml';
import { CaptureFlow } from './CaptureFlow';
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
  const { store, account, revision, canCapture: packAllows } = useOffline();
  const canCapture = (allowed ?? packAllows) && account !== null;
  const [local, setLocal] = useState<QueuedCapture[]>([]);
  const [capturing, setCapturing] = useState<CaptureTarget | null>(null);

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

  // Directions go to the entrance when there is one.
  const directions = () => {
    const at = school.entranceLat !== null ? { lat: school.entranceLat, lng: school.entranceLng! } : { lat: school.lat!, lng: school.lng! };
    chooseDirections([create(SchoolPinSchema, { schoolId: school.schoolId, name: school.name, code: school.code, point: at, locationStatus: 'verified' })]);
  };

  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]} accessibilityLabel="Location and directions">
      <View style={styles.title}>
        <MapPin size={20} color={BLUE} />
        <Text style={[styles.titleText, { color: colors.text }]} accessibilityRole="header">
          Location &amp; Directions
        </Text>
      </View>
      {scene.pins.length ? (
        <View style={[styles.map, { borderColor: colors.border }]}>
          <RouteMapView scene={scene} onSelect={() => undefined} />
        </View>
      ) : null}
      {hasPoint ? (
        <>
          <Fact label="Current location" value={`${school.lat!.toFixed(6)}, ${school.lng!.toFixed(6)}`} />
          <Fact label="Location status" value={`${STATUS[school.locationStatus] ?? school.locationStatus}${school.version > 0 ? ` · version ${school.version}` : ''}`} />
          <Fact
            label="Date last verified"
            value={school.verifiedAt ? `${dayOf(school.verifiedAt)}${verifiedByName ? ` by ${verifiedByName}` : ''}` : 'Not yet verified in the field'}
          />
          {school.lastConfirmedAt ? <Fact label="Last checked on a visit" value={dayOf(school.lastConfirmedAt)} /> : null}
          {school.entranceLat !== null ? <Fact label="Entrance" value={`${school.entranceLat.toFixed(6)}, ${school.entranceLng!.toFixed(6)}`} /> : null}
          {school.accessNote ? <Fact label="Directions" value={school.accessNote} /> : null}
          <View style={styles.buttons}>
            {canCapture ? (
              <Pressable onPress={() => setCapturing('school')} style={styles.primary} accessibilityRole="button">
                <Crosshair size={18} color="#fff" />
                <Text style={styles.primaryText}>Verify / Replace Location</Text>
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
          <Text style={styles.noneTitle}>GPS Location Not Captured</Text>
          <Text style={styles.noneText}>The school still appears in every list and plan. Directions and route planning need a location.</Text>
          {canCapture ? (
            <Pressable onPress={() => setCapturing('school')} style={[styles.primary, styles.wide]} accessibilityRole="button">
              <Crosshair size={20} color="#fff" />
              <Text style={styles.primaryText}>Capture School Location</Text>
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
      {capturing ? (
        <CaptureFlow
          school={school}
          target={capturing}
          onClose={(saved) => {
            setCapturing(null);
            if (saved) onCaptured?.();
          }}
        />
      ) : null}
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
  title: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: spacing.sm },
  titleText: { fontFamily: fonts.semibold, fontSize: 16 },
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
  noneTitle: { fontFamily: fonts.semibold, fontSize: 16, color: '#92400e' },
  noneText: { fontFamily: fonts.regular, fontSize: 14, color: '#92400e' },
  queue: { backgroundColor: '#fff7ed', borderRadius: radius.sm, padding: spacing.sm, gap: 4, marginTop: spacing.sm },
  queueText: { fontFamily: fonts.medium, fontSize: 14 },
});
