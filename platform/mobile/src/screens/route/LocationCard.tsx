/**
 * A school's Location & Directions card on its profile (Smart Route brief,
 * part 11; offline GPS capture brief, 2026-11-14). The server's answer when
 * there is a connection, the phone's own copy when there is not; either way
 * the same panel: the pin, how sure it is, Capture / Verify / Replace
 * Location, Get Directions. Online it adds the nearby schools, a report
 * waiting for review (with Approve / Reject for a reviewer), Report location
 * for those who do not capture by GPS, and the location's history.
 */
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { History, Hourglass, Route, TriangleAlert } from 'lucide-react-native';

import { useSession } from '../../auth/SessionContext';
import { RoutePlannerService } from '../../gen/edify/routes/v1/routes_pb';
import type { GetSchoolLocationResponse, LocationReport } from '../../gen/edify/routes/v1/routes_pb';
import { LocationHistory } from '../../offline/LocationHistory';
import { LocationPanel } from '../../offline/LocationPanel';
import { useOffline } from '../../offline/OfflineContext';
import type { CachedSchool } from '../../offline/store';
import { useCachedSchool } from '../../offline/useCachedSchool';
import { fonts, radius, spacing, useTheme } from '../../theme';
import { ReportDetails, ReportForm, ReviewControls } from './LocationReportParts';
import { LOCATION_REPORTS_URL, PIN_TONES, ROUTE_URL } from './routeData';

export interface LocationCardProps {
  readonly schoolId: string;
  /** Opens the route planner; absent where the profile cannot. */
  readonly onOpenRoute?: (url: string) => void;
}

/** The server's answer as the panel reads a school. */
function schoolOf(answer: GetSchoolLocationResponse): CachedSchool | null {
  const s = answer.school;
  if (!s) return null;
  return {
    schoolId: s.schoolId,
    code: s.code,
    name: s.name,
    district: s.district,
    cluster: s.cluster,
    category: s.category,
    locationStatus: s.locationStatus,
    lat: s.point?.lat ?? null,
    lng: s.point?.lng ?? null,
    version: answer.version || s.locationVersion,
    entranceLat: answer.entrance?.lat ?? null,
    entranceLng: answer.entrance?.lng ?? null,
    verifiedAt: answer.verifiedAt,
    accessNote: answer.accessNote,
    hasPending: Boolean(answer.pendingReport),
    lastConfirmedAt: answer.lastConfirmedAt,
  };
}

export function LocationCard({ schoolId, onOpenRoute }: LocationCardProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const { markChanged } = useOffline();
  const cached = useCachedSchool(schoolId);
  const [answer, setAnswer] = useState<GetSchoolLocationResponse | null>(null);
  const [isOffline, setIsOffline] = useState(false);
  const [pending, setPending] = useState<LocationReport | undefined>(undefined);
  const [isReporting, setIsReporting] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [notice, setNotice] = useState('');
  // Bumped after a capture or a review, so the card reads the school again.
  const [reads, setReads] = useState(0);

  useEffect(() => {
    let isCurrent = true;
    api
      .call(RoutePlannerService.method.getSchoolLocation, { schoolId })
      .then((next) => {
        if (!isCurrent) return;
        setAnswer(next);
        setPending(next.pendingReport);
        setIsOffline(false);
      })
      // Without a connection the phone's own copy is shown.
      .catch(() => isCurrent && setIsOffline(true));
    return () => {
      isCurrent = false;
    };
  }, [api, schoolId, reads]);

  const online = answer ? schoolOf(answer) : null;
  const school = isOffline ? cached : online;
  if (!school) return null;
  const reread = () => {
    setReads((n) => n + 1);
    markChanged();
  };

  const footer =
    answer && !isOffline ? (
      <>
        {school.lat !== null ? (
          <Text style={[styles.value, { color: colors.text }]}>
            <Text style={{ color: colors.textMuted }}>Nearby: </Text>
            {answer.nearbySchools} of your schools within {answer.nearbyRadiusKm} km (straight line)
          </Text>
        ) : null}
        {answer.canPlan && onOpenRoute && school.lat !== null ? (
          <Pressable onPress={() => onOpenRoute(`${ROUTE_URL}?near=${encodeURIComponent(school.schoolId)}`)} style={styles.link} accessibilityRole="button">
            <Route size={16} color={PIN_TONES.planned} />
            <Text style={styles.linkText}>Find Nearby Schools</Text>
          </Pressable>
        ) : null}
        {notice ? (
          <Text style={styles.notice} accessibilityLiveRegion="polite">
            {notice}
          </Text>
        ) : null}
        {pending ? (
          <View style={styles.pending}>
            <View style={styles.row}>
              <Hourglass size={16} color="#0b4a9e" />
              <Text style={styles.pendingTitle}>Location report waiting for review</Text>
            </View>
            <ReportDetails report={pending} />
            {answer.canReview && onOpenRoute ? (
              <Pressable onPress={() => onOpenRoute(LOCATION_REPORTS_URL)} accessibilityRole="link" style={styles.link}>
                <Text style={styles.linkText}>All location reports</Text>
              </Pressable>
            ) : null}
            {answer.canReview ? (
              <ReviewControls
                report={pending}
                onDecided={(decided) => {
                  setPending(undefined);
                  setNotice(decided.status === 'approved' ? 'Approved. This is now the verified location.' : 'Rejected. The location stays as it was.');
                  reread();
                }}
              />
            ) : null}
          </View>
        ) : null}
        {!pending && answer.canReport && !answer.canCapture && !isReporting && answer.school ? (
          <Pressable onPress={() => setIsReporting(true)} style={styles.link} accessibilityRole="button">
            <TriangleAlert size={16} color={PIN_TONES.planned} />
            <Text style={styles.linkText}>Report location</Text>
          </Pressable>
        ) : null}
        {isReporting && answer.school ? (
          <ReportForm
            school={answer.school}
            onCancel={() => setIsReporting(false)}
            onFiled={(report) => {
              setIsReporting(false);
              setPending(report);
              setNotice('Sent for review. The location changes only once someone else approves it.');
            }}
          />
        ) : null}
        <Pressable onPress={() => setIsHistoryOpen(true)} style={styles.link} accessibilityRole="button">
          <History size={16} color={PIN_TONES.planned} />
          <Text style={styles.linkText}>Location history</Text>
        </Pressable>
        {isHistoryOpen ? <LocationHistory schoolId={school.schoolId} onClose={() => setIsHistoryOpen(false)} /> : null}
      </>
    ) : isOffline ? (
      <Text style={[styles.offline, { color: colors.textMuted }]}>Offline: showing the location saved on this phone.</Text>
    ) : null;

  return (
    <LocationPanel
      school={school}
      verifiedByName={answer?.verifiedByName}
      footer={footer}
      onCaptured={reread}
      canCapture={isOffline ? undefined : answer?.canCapture}
    />
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  value: { fontFamily: fonts.medium, fontSize: 14, marginTop: spacing.sm },
  link: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44, alignSelf: 'flex-start' },
  linkText: { fontFamily: fonts.semibold, fontSize: 15, color: PIN_TONES.planned },
  notice: { fontFamily: fonts.medium, fontSize: 14, color: '#0b4a9e', backgroundColor: '#e8f1fd', borderRadius: radius.sm, padding: spacing.sm, marginTop: spacing.sm },
  pending: { borderWidth: 1, borderColor: '#a9c8f3', backgroundColor: '#f4f8fe', borderRadius: radius.sm, padding: spacing.sm, marginTop: spacing.sm, gap: 6 },
  pendingTitle: { fontFamily: fonts.semibold, fontSize: 14, color: '#0b4a9e', flexShrink: 1 },
  offline: { fontFamily: fonts.medium, fontSize: 13, marginTop: spacing.sm },
});
