/**
 * A school's Location & Directions card on its profile (Smart Route brief,
 * part 11): the school on the map, how sure its location is, directions in
 * the person's own maps app, and its nearby schools in the planner. A school
 * with no usable location says so and stays in every list and plan.
 * Report location sends a correction for someone else to review; an open
 * report shows here, with Approve / Reject for a reviewer.
 */
import { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Hourglass, MapPin, Navigation, Route, TriangleAlert } from 'lucide-react-native';

import { useSession } from '../../auth/SessionContext';
import { RoutePlannerService } from '../../gen/edify/routes/v1/routes_pb';
import type { GetSchoolLocationResponse, LocationReport } from '../../gen/edify/routes/v1/routes_pb';
import { fonts, radius, spacing, useTheme } from '../../theme';
import { chooseDirections } from './directions';
import { ReportDetails, ReportForm, ReviewControls } from './LocationReportParts';
import { LOCATION_REPORTS_URL, PIN_TONES, ROUTE_URL, shortName } from './routeData';
import { RouteMapView } from './RouteMapView';

const STATUS: Record<string, string> = {
  verified: 'Verified location',
  recorded: 'From the School Directory (not yet verified)',
  missing: 'No location recorded',
  invalid: 'The recorded location looks wrong',
};

export interface LocationCardProps {
  readonly schoolId: string;
  /** Opens the route planner; absent where the profile cannot. */
  readonly onOpenRoute?: (url: string) => void;
}

export function LocationCard({ schoolId, onOpenRoute }: LocationCardProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [answer, setAnswer] = useState<GetSchoolLocationResponse | null>(null);
  const [pending, setPending] = useState<LocationReport | undefined>(undefined);
  const [isReporting, setIsReporting] = useState(false);
  const [notice, setNotice] = useState('');
  // Bumped after a review, so the card reads the school's location again.
  const [reads, setReads] = useState(0);

  useEffect(() => {
    let isCurrent = true;
    api
      .call(RoutePlannerService.method.getSchoolLocation, { schoolId })
      .then((next) => {
        if (!isCurrent) return;
        setAnswer(next);
        setPending(next.pendingReport);
      })
      // Without its location the profile is shown as it was.
      .catch(() => undefined);
    return () => {
      isCurrent = false;
    };
  }, [api, schoolId, reads]);

  const school = answer?.school;
  const point = school?.point;
  const scene = useMemo(
    () => ({
      pins: point && school ? [{ id: school.schoolId, order: '', name: shortName(school.name), detail: '', lat: point.lat, lng: point.lng, tone: PIN_TONES.planned }] : [],
      path: [],
      legend: [],
    }),
    [school, point],
  );
  if (!answer || !school) return null;

  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]} accessibilityLabel="Location and directions">
      <View style={styles.title}>
        <MapPin size={20} color={PIN_TONES.planned} />
        <Text style={[styles.titleText, { color: colors.text }]} accessibilityRole="header">
          Location &amp; Directions
        </Text>
      </View>
      {point ? (
        <>
          <View style={[styles.map, { borderColor: colors.border }]}>
            <RouteMapView scene={scene} onSelect={() => undefined} />
          </View>
          <Text style={[styles.label, { color: colors.textMuted }]}>GPS location</Text>
          <Text style={[styles.value, { color: colors.text }]}>
            {point.lat.toFixed(6)}, {point.lng.toFixed(6)}
          </Text>
          <Text style={[styles.label, { color: colors.textMuted }]}>Location status</Text>
          <Text style={[styles.value, { color: colors.text }]}>{STATUS[school.locationStatus] ?? school.locationStatus}</Text>
          <Text style={[styles.label, { color: colors.textMuted }]}>Nearby</Text>
          <Text style={[styles.value, { color: colors.text }]}>
            {answer.nearbySchools} of your schools within {answer.nearbyRadiusKm} km (straight line)
          </Text>
          <View style={styles.buttons}>
            <Pressable onPress={() => chooseDirections([school])} style={styles.primary} accessibilityRole="button">
              <Navigation size={18} color="#fff" />
              <Text style={styles.primaryText}>Get Directions</Text>
            </Pressable>
            {answer.canPlan && onOpenRoute ? (
              <Pressable onPress={() => onOpenRoute(`${ROUTE_URL}?near=${encodeURIComponent(school.schoolId)}`)} style={styles.outline} accessibilityRole="button">
                <Route size={18} color={PIN_TONES.planned} />
                <Text style={styles.outlineText}>Find Nearby Schools</Text>
              </Pressable>
            ) : null}
          </View>
        </>
      ) : (
        <Text style={styles.missing} accessibilityRole="text">
          {STATUS[school.locationStatus]}. Directions and route planning need a location; the school still appears in every list
          and plan.
        </Text>
      )}
      {answer.accessNote ? (
        <Text style={[styles.value, styles.gap, { color: colors.text }]}>
          <Text style={{ color: colors.textMuted }}>Directions: </Text>
          {answer.accessNote}
        </Text>
      ) : null}
      {notice ? (
        <Text style={styles.notice} accessibilityRole="text" accessibilityLiveRegion="polite">
          {notice}
        </Text>
      ) : null}
      {pending ? (
        <View style={styles.pending}>
          <View style={styles.title}>
            <Hourglass size={16} color="#0b4a9e" />
            <Text style={styles.pendingTitle}>Location report waiting for review</Text>
          </View>
          <ReportDetails report={pending} />
          {answer.canReview && onOpenRoute ? (
            <Pressable onPress={() => onOpenRoute(LOCATION_REPORTS_URL)} accessibilityRole="link" style={styles.link}>
              <Text style={styles.outlineText}>All location reports</Text>
            </Pressable>
          ) : null}
          {answer.canReview ? (
            <ReviewControls
              report={pending}
              onDecided={(decided) => {
                setPending(undefined);
                setNotice(decided.status === 'approved' ? 'Approved. This is now the verified location.' : 'Rejected. The location stays as it was.');
                setReads((n) => n + 1);
              }}
            />
          ) : null}
        </View>
      ) : null}
      {!pending && answer.canReport && !isReporting ? (
        <Pressable
          onPress={() => {
            setNotice('');
            setIsReporting(true);
          }}
          style={styles.link}
          accessibilityRole="button"
        >
          <TriangleAlert size={16} color={PIN_TONES.planned} />
          <Text style={styles.outlineText}>Report location</Text>
        </Pressable>
      ) : null}
      {isReporting ? (
        <ReportForm
          school={school}
          onCancel={() => setIsReporting(false)}
          onFiled={(report) => {
            setIsReporting(false);
            setPending(report);
            setNotice('Sent for review. The location changes only once someone else approves it.');
          }}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: 4, marginTop: spacing.md },
  title: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: spacing.sm },
  titleText: { fontFamily: fonts.semibold, fontSize: 16 },
  map: { height: 220, borderRadius: radius.sm, borderWidth: 1, overflow: 'hidden', marginBottom: spacing.sm },
  label: { fontFamily: fonts.regular, fontSize: 13, marginTop: spacing.xs },
  value: { fontFamily: fonts.medium, fontSize: 14 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
  primary: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: PIN_TONES.planned, borderRadius: radius.sm, paddingHorizontal: 14, minHeight: 44 },
  primaryText: { fontFamily: fonts.semibold, fontSize: 15, color: '#fff' },
  outline: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1.5, borderColor: PIN_TONES.planned, borderRadius: radius.sm, paddingHorizontal: 14, minHeight: 44 },
  outlineText: { fontFamily: fonts.semibold, fontSize: 15, color: PIN_TONES.planned },
  gap: { marginTop: spacing.sm },
  notice: { fontFamily: fonts.medium, fontSize: 14, color: '#0b4a9e', backgroundColor: '#e8f1fd', borderRadius: radius.sm, padding: spacing.sm, marginTop: spacing.sm },
  pending: { borderWidth: 1, borderColor: '#a9c8f3', backgroundColor: '#f4f8fe', borderRadius: radius.sm, padding: spacing.sm, marginTop: spacing.sm, gap: 6 },
  pendingTitle: { fontFamily: fonts.semibold, fontSize: 14, color: '#0b4a9e', flexShrink: 1 },
  link: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44, alignSelf: 'flex-start', marginTop: 4 },
  missing: { fontFamily: fonts.regular, fontSize: 14, color: '#92400e', backgroundColor: '#fffbeb', borderRadius: radius.sm, padding: spacing.sm },
});
