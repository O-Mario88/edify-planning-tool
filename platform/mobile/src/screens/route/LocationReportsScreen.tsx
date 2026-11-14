/**
 * Location Reports in the app (Verify Location): the reports on school
 * locations a reviewer may decide. Pending is oldest first; Approved and
 * Rejected are newest first. An approved point becomes the school's
 * verified location for route planning; the School Directory's own
 * coordinates are never changed.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import { RoutePlannerService } from '../../gen/edify/routes/v1/routes_pb';
import type { LocationReport } from '../../gen/edify/routes/v1/routes_pb';
import { fonts, radius, spacing, useTheme } from '../../theme';
import { LoanHero, LoanSheet, SegmentTabs } from '../loans/loanUi';
import { ReportDetails, ReviewControls } from './LocationReportParts';
import { PIN_TONES } from './routeData';

type Status = 'pending' | 'approved' | 'rejected';

export interface LocationReportsScreenProps {
  readonly onOpenSchool: (schoolId: string) => void;
}

export function LocationReportsScreen({ onOpenSchool }: LocationReportsScreenProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [status, setStatus] = useState<Status>('pending');
  const [reports, setReports] = useState<readonly LocationReport[] | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(() => {
    let isCurrent = true;
    setReports(null);
    setError('');
    api
      .call(RoutePlannerService.method.listLocationReports, { status })
      .then((answer) => isCurrent && setReports(answer.reports))
      .catch((cause: unknown) => isCurrent && setError(describe(cause)));
    return () => {
      isCurrent = false;
    };
  }, [api, status]);
  useEffect(load, [load]);

  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <LoanHero eyebrow="Field routes" title="Location Reports" subtitle="Corrections to school locations sent from the field. An approved point becomes the verified location." />
      <LoanSheet>
        <SegmentTabs<Status>
          tabs={[
            { key: 'pending', label: 'Pending' },
            { key: 'approved', label: 'Approved' },
            { key: 'rejected', label: 'Rejected' },
          ]}
          value={status}
          onChange={(next) => {
            setNotice('');
            setStatus(next);
          }}
        />
        {notice ? (
          <Text style={styles.notice} accessibilityLiveRegion="polite">
            {notice}
          </Text>
        ) : null}
        {error ? <Text style={[styles.error, { color: colors.danger, backgroundColor: colors.dangerSoft }]}>{error}</Text> : null}
        {reports === null && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading reports" /> : null}
        {reports?.length === 0 ? (
          <Text style={[styles.muted, { color: colors.textMuted }]}>
            {status === 'pending' ? 'No location reports are waiting for review.' : `No ${status} location reports.`}
          </Text>
        ) : null}
        {reports?.map((report) => (
          <View key={report.id} style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.border }]}>
            <Pressable onPress={() => report.school && onOpenSchool(report.school.schoolId)} accessibilityRole="link" style={styles.head}>
              <Text style={styles.school}>{report.school?.name}</Text>
              <Text style={[styles.muted, { color: colors.textMuted }]}>
                School ID {report.school?.code || '—'} · {report.school?.district || 'No district'}
              </Text>
            </Pressable>
            <ReportDetails report={report} />
            {report.status === 'pending' ? (
              <ReviewControls
                report={report}
                onDecided={(decided) => {
                  setReports((list) => (list ?? []).filter((r) => r.id !== decided.id));
                  setNotice(
                    decided.status === 'approved'
                      ? `${decided.school?.name}: approved. This is now its verified location.`
                      : `${decided.school?.name}: rejected. Its location stays as it was.`,
                  );
                }}
              />
            ) : null}
          </View>
        ))}
      </LoanSheet>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: spacing.xl },
  card: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: spacing.sm },
  head: { gap: 2, minHeight: 44 },
  school: { fontFamily: fonts.semibold, fontSize: 16, color: PIN_TONES.planned },
  muted: { fontFamily: fonts.regular, fontSize: 13 },
  notice: { fontFamily: fonts.medium, fontSize: 14, color: '#0b4a9e', backgroundColor: '#e8f1fd', borderRadius: radius.sm, padding: spacing.sm },
  error: { fontFamily: fonts.medium, fontSize: 14, borderRadius: radius.sm, padding: spacing.sm },
});
