/**
 * A planned meeting or training (owner's mockup, 2026-11-11, "Meeting
 * Details"): its status in words, when and where, the agenda, the schools
 * invited, and Edit or Cancel while it is still planned. Once staff schedule
 * it, it opens the official activity for attendance and minutes.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { CalendarDays, ChevronDown, ChevronRight, FileText, MapPin, Pencil, Trash2, Users } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetPlanResponse } from '../../gen/edify/clusters/v1/mobilization_pb';
import { ClusterMobilizationService } from '../../gen/edify/clusters/v1/mobilization_pb';
import { fonts, radius, useTheme } from '../../theme';
import { LoanHero, LoanSheet, PrimaryButton, StatusChip } from '../loans/loanUi';
import { channelLabel, planStatus } from './clusterData';
import { longDate } from './clusterRoutes';
import { MeetingForm } from './MeetingForm';
import { Field, Notice } from './opsParts';

const METHOD = ClusterMobilizationService.method;

interface MeetingDetailProps {
  readonly planId: string;
  readonly clusterId: string;
  readonly clusterName: string;
  readonly onOpenActivity: (activityId: string) => void;
  readonly onBack: () => void;
}

export function MeetingDetailScreen({ planId, clusterId, clusterName, onOpenActivity, onBack }: MeetingDetailProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [answer, setAnswer] = useState<GetPlanResponse | null>(null);
  const [error, setError] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [isListOpen, setIsListOpen] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [reason, setReason] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const load = useCallback(() => {
    setError('');
    api
      .call(METHOD.getPlan, { id: planId })
      .then(setAnswer)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, planId]);
  useEffect(load, [load]);

  const plan = answer?.plan;
  if (plan && isEditing) {
    return (
      <MeetingForm
        kind={plan.category === 'training' ? 'training' : 'meeting'}
        clusterId={clusterId}
        clusterName={clusterName}
        plan={plan}
        invitedIds={answer.invited.map((school) => school.schoolId)}
        onDone={() => {
          setIsEditing(false);
          setNotice('Saved and sent to your CCEO for review.');
          load();
        }}
        onBack={() => setIsEditing(false)}
      />
    );
  }

  const cancel = () => {
    setIsBusy(true);
    api
      .call(METHOD.cancelPlan, { id: planId, reason: reason.trim() })
      .then(() => {
        setIsCancelling(false);
        setNotice(`${noun} cancelled.`);
        load();
      })
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  const status = planStatus(plan?.status ?? '');
  const noun = plan?.category === 'training' ? 'Training' : 'Meeting';
  const card = [styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }];
  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <LoanHero eyebrow={clusterName} title={plan?.category === 'training' ? 'Cluster Training' : 'Cluster Meeting'} onBack={onBack} />
      <LoanSheet>
        {error ? <Notice text={error} isError /> : null}
        {notice ? <Notice text={notice} /> : null}
        {!plan && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
        {plan ? (
          <>
            <View style={card}>
              <View style={styles.head}>
                <CalendarDays size={28} color={colors.primary} />
                <View style={styles.flex}>
                  <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
                    {plan.title}
                  </Text>
                  <View style={styles.chipRow}>
                    <StatusChip label={status.label} tone={status.tone} />
                  </View>
                  {status.meaning ? <Text style={[styles.muted, { color: colors.textMuted }]}>{status.meaning}</Text> : null}
                </View>
              </View>
              <Line icon={CalendarDays} text={`${longDate(plan.plannedOn)}${plan.startsAt ? ` · ${plan.startsAt}` : ''}`} />
              {plan.venue ? <Line icon={MapPin} text={plan.venue} /> : null}
              {plan.trainingCourse ? <Line icon={FileText} text={plan.trainingCourse} /> : null}
              {plan.agenda ? <Line icon={FileText} text={plan.agenda} /> : null}
              {plan.reviewNote ? <Line icon={FileText} text={`Staff note: ${plan.reviewNote}`} /> : null}
            </View>

            <Pressable
              onPress={() => setIsListOpen(!isListOpen)}
              accessibilityRole="button"
              accessibilityState={{ expanded: isListOpen }}
              style={[card, styles.rowCard]}
            >
              <Users size={22} color={colors.primary} />
              <Text style={[styles.rowLabel, { color: colors.text }]}>Invited Schools ({answer?.invited.length ?? 0})</Text>
              {isListOpen ? <ChevronDown size={20} color={colors.textMuted} /> : <ChevronRight size={20} color={colors.textMuted} />}
            </Pressable>
            {isListOpen ? (
              <View style={card}>
                {answer?.invited.length === 0 ? <Text style={[styles.muted, { color: colors.textMuted }]}>No school invited yet.</Text> : null}
                {answer?.invited.map((school) => (
                  <View key={school.schoolId} style={[styles.invitee, { borderTopColor: colors.border }]}>
                    <Text style={[styles.rowLabel, { color: colors.text }]}>{school.name}</Text>
                    <Text style={[styles.muted, { color: colors.textMuted }]}>
                      {[school.edifySchoolId, channelLabel(school.channel), longDate(school.invitedOn)].filter(Boolean).join(' · ')}
                    </Text>
                  </View>
                ))}
              </View>
            ) : null}

            {plan.activityId ? (
              <PrimaryButton label="Open the scheduled meeting" icon={CalendarDays} onPress={() => onOpenActivity(plan.activityId)} />
            ) : null}
            {plan.canEdit ? <PrimaryButton label={`Edit ${noun}`} icon={Pencil} isOutline onPress={() => setIsEditing(true)} /> : null}
            {plan.canCancel && !isCancelling ? (
              <Pressable onPress={() => setIsCancelling(true)} accessibilityRole="button" style={[styles.danger, { borderColor: colors.danger }]}>
                <Trash2 size={18} color={colors.danger} />
                <Text style={[styles.dangerText, { color: colors.danger }]}>Cancel {noun}</Text>
              </Pressable>
            ) : null}
            {isCancelling ? (
              <View style={card}>
                <Field label="Why is it cancelled? (optional)" value={reason} onChange={setReason} isMultiline />
                <PrimaryButton label={isBusy ? 'Cancelling…' : 'Confirm cancellation'} icon={Trash2} onPress={cancel} isDisabled={isBusy} />
                <PrimaryButton label={`Keep the ${noun.toLowerCase()}`} isOutline onPress={() => setIsCancelling(false)} />
              </View>
            ) : null}
          </>
        ) : null}
      </LoanSheet>
    </ScrollView>
  );
}

function Line({ icon: Icon, text }: { readonly icon: typeof CalendarDays; readonly text: string }) {
  const { colors } = useTheme();
  return (
    <View style={styles.line}>
      <Icon size={18} color={colors.textMuted} />
      <Text style={[styles.lineText, { color: colors.text }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 10 },
  head: { flexDirection: 'row', gap: 12 },
  flex: { flex: 1, gap: 6 },
  title: { fontFamily: fonts.bold, fontSize: 19 },
  chipRow: { flexDirection: 'row' },
  muted: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
  line: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  lineText: { flex: 1, fontFamily: fonts.medium, fontSize: 15, lineHeight: 21 },
  rowCard: { flexDirection: 'row', alignItems: 'center', minHeight: 56 },
  rowLabel: { flex: 1, fontFamily: fonts.semibold, fontSize: 15 },
  invitee: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 8, gap: 2 },
  danger: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, borderWidth: 1.5, borderRadius: radius.md, minHeight: 48 },
  dangerText: { fontFamily: fonts.bold, fontSize: 16 },
});
