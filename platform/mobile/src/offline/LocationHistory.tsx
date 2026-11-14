/**
 * A school's location history (offline capture brief, 2026-11-14, part 8):
 * every capture and report on it, newest first: the point, its accuracy,
 * who sent it, the reason, the decision and the version it made. Only
 * points at this school are kept; nothing about anyone's movements.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { X } from 'lucide-react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { describe, useSession } from '../auth/SessionContext';
import { RoutePlannerService } from '../gen/edify/routes/v1/routes_pb';
import type { LocationReport } from '../gen/edify/routes/v1/routes_pb';
import { fonts, radius, spacing, useTheme } from '../theme';
import { dayOf } from './LocationPanel';

const DECISION: Record<string, string> = {
  accepted: 'Accepted at once (first location, good GPS)',
  approved: 'Approved',
  rejected: 'Rejected',
  pending: 'Waiting for review',
  noted: 'Confirmed correct on a visit',
};

export const FLAG_TEXT: Record<string, string> = {
  entrance: 'Entrance point',
  correction: 'Replaces the point on record',
  version_conflict: 'The location changed after this was captured',
  reporter_role: 'Sent by a role that does not capture locations',
  competing: 'Another report on this school was waiting',
  no_point: 'No point given',
  typed_point: 'Typed, not captured by GPS',
  accuracy_poor: 'Poor GPS accuracy',
  accuracy_fair: 'GPS accuracy needed confirming',
  unstable: 'Readings did not agree',
  stale_capture: 'Captured long before it was sent',
  clock_skew: 'The phone’s clock was ahead',
  large_move: 'Moves the school a long way',
  far_from_district: 'Far from the district’s other schools',
};

export function LocationHistory({ schoolId, onClose }: { readonly schoolId: string; onClose(): void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [entries, setEntries] = useState<readonly LocationReport[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let isCurrent = true;
    api
      .call(RoutePlannerService.method.getLocationHistory, { schoolId })
      .then((answer) => isCurrent && setEntries(answer.entries))
      .catch((cause: unknown) => isCurrent && setError(describe(cause)));
    return () => {
      isCurrent = false;
    };
  }, [api, schoolId]);

  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={[styles.sheet, { backgroundColor: colors.bg, paddingBottom: insets.bottom }]}>
        <View style={styles.header}>
          <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
            Location history
          </Text>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close" hitSlop={10} style={styles.close}>
            <X size={24} color={colors.text} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.body}>
          {error ? <Text style={[styles.text, { color: colors.danger }]}>{error}</Text> : null}
          {entries === null && !error ? <ActivityIndicator color={colors.primary} /> : null}
          {entries?.length === 0 ? <Text style={[styles.text, { color: colors.textMuted }]}>No location has been captured or reported for this school yet.</Text> : null}
          {entries?.map((e) => (
            <View key={e.id} style={[styles.entry, { borderColor: colors.border, backgroundColor: colors.card }]}>
              <Text style={[styles.what, { color: colors.text }]}>
                {e.target === 'entrance' ? 'Entrance · ' : ''}
                {e.captureKind === 'confirm' ? 'Location confirmed' : e.captureKind === 'new' || e.kind === 'missing' ? 'First location' : 'Correction'}
                {e.resultVersion ? ` → version ${e.resultVersion}` : ''}
              </Text>
              <Text style={[styles.text, { color: colors.text }]}>{DECISION[e.status] ?? e.status}</Text>
              {e.proposed ? (
                <Text style={[styles.text, { color: colors.text }]}>
                  {e.proposed.lat.toFixed(6)}, {e.proposed.lng.toFixed(6)}
                  {e.pointSource === 'device' ? ` · GPS ${Math.round(e.accuracyM)} m` : e.pointSource === 'typed' ? ' · typed' : ''}
                  {e.previous && e.movedMeters ? ` · moved ${e.movedMeters < 1000 ? `${e.movedMeters} m` : `${(Number(e.movedMeters) / 1000).toFixed(1)} km`}` : ''}
                </Text>
              ) : null}
              <Text style={[styles.meta, { color: colors.textMuted }]}>
                {e.reportedByName || 'Someone'} · {dayOf(e.capturedAt || e.reportedAt)}
                {e.reviewedByName ? ` · decided by ${e.reviewedByName}${e.reviewedAt ? ` on ${dayOf(e.reviewedAt)}` : ''}` : ''}
              </Text>
              {e.note ? <Text style={[styles.text, { color: colors.text }]}>{e.note}</Text> : null}
              {e.reviewNote ? <Text style={[styles.meta, { color: colors.textMuted }]}>Review: {e.reviewNote}</Text> : null}
              {e.flags.length ? <Text style={[styles.meta, { color: colors.textMuted }]}>{e.flags.map((f) => FLAG_TEXT[f] ?? f).join(' · ')}</Text> : null}
            </View>
          ))}
        </ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  sheet: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: spacing.lg },
  title: { fontFamily: fonts.bold, fontSize: 22 },
  close: { minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  body: { padding: spacing.lg, paddingTop: 0, gap: spacing.sm },
  entry: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: 4 },
  what: { fontFamily: fonts.semibold, fontSize: 15 },
  text: { fontFamily: fonts.medium, fontSize: 14 },
  meta: { fontFamily: fonts.regular, fontSize: 13 },
});
