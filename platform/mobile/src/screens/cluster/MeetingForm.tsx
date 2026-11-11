/**
 * "Plan Cluster Meeting" and "Mobilize Schools (Training)" (owner's mockup,
 * 2026-11-11), and editing either while it is still planned. Saving sends the
 * plan to the cluster's CCEO for review and records the leader's invitations
 * at once; they carry over to the official activity when staff schedule it.
 * Success is shown only after the gateway confirms both.
 */
import { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { CalendarDays, Check, GraduationCap, Send } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { CourseChoice, MeetingPlan } from '../../gen/edify/clusters/v1/mobilization_pb';
import { ClusterMobilizationService } from '../../gen/edify/clusters/v1/mobilization_pb';
import { fonts, radius, useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { Select } from '../../ui/Select';
import { fromDate, toIso } from '../../ui/calendar';
import { LoanHero, LoanSheet, PrimaryButton } from '../loans/loanUi';
import { INVITE_CHANNELS, isTimeText, useAllMembers } from './clusterData';
import { ChoiceRow, Field, FieldLabel, Notice } from './opsParts';

const METHOD = ClusterMobilizationService.method;

export type MeetingKind = 'meeting' | 'training';

interface MeetingFormProps {
  readonly kind: MeetingKind;
  readonly clusterId: string;
  readonly clusterName: string;
  /** The plan being edited; absent to create one. */
  readonly plan?: MeetingPlan;
  /** Schools already invited to the plan being edited. */
  readonly invitedIds?: readonly string[];
  readonly onDone: (planId: string) => void;
  readonly onBack: () => void;
}

export function MeetingForm({ kind, clusterId, clusterName, plan, invitedIds = [], onDone, onBack }: MeetingFormProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const members = useAllMembers(clusterId);
  const [courses, setCourses] = useState<readonly CourseChoice[]>([]);
  const [title, setTitle] = useState(plan?.title ?? '');
  const [courseId, setCourseId] = useState(plan?.trainingCourseId ?? '');
  const [plannedOn, setPlannedOn] = useState(plan?.plannedOn ?? '');
  const [startsAt, setStartsAt] = useState(plan?.startsAt ?? '');
  const [venue, setVenue] = useState(plan?.venue ?? '');
  const [agenda, setAgenda] = useState(plan?.agenda ?? '');
  const [channel, setChannel] = useState('');
  const [picked, setPicked] = useState<ReadonlySet<string> | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const isTraining = kind === 'training';

  useEffect(() => {
    if (!isTraining) {
      return;
    }
    api
      .call(METHOD.getPlanOptions, {})
      .then((answer) => setCourses(answer.courses))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, isTraining]);

  // Every member school starts ticked; on an edit, the invited ones stay ticked.
  const all = members.schools ?? [];
  const chosen = picked ?? new Set(all.map((school) => school.id));
  const toInvite = isTraining ? all.filter((school) => chosen.has(school.id)) : all;
  const newInvites = toInvite.filter((school) => !invitedIds.includes(school.id));
  const course = courses.find((choice) => choice.id === courseId);
  const today = useMemo(() => toIso(fromDate(new Date())), []);

  const problem = (() => {
    if (isTraining ? !courseId : !title.trim()) {
      return isTraining ? 'Choose the training topic.' : 'Give the meeting a title.';
    }
    if (!plannedOn) {
      return 'Choose the date.';
    }
    if (!isTraining && !startsAt.trim()) {
      return 'Give the time, such as 10:00 AM.';
    }
    if (!isTimeText(startsAt)) {
      return 'Write the time like 10:00 AM.';
    }
    if (!venue.trim()) {
      return 'Name the venue.';
    }
    if (newInvites.length > 0 && !channel) {
      return 'Say how you are inviting the schools.';
    }
    if (isTraining && toInvite.length === 0) {
      return 'Choose at least one school.';
    }
    return '';
  })();

  const save = async () => {
    setIsBusy(true);
    setError('');
    let planId = plan?.id ?? '';
    try {
      const saved = await api.call(METHOD.savePlan, {
        id: planId,
        clusterId,
        category: isTraining ? 'training' : 'only_meeting',
        title: isTraining ? `${course?.name ?? 'Cluster'} training` : title.trim(),
        trainingCourseId: isTraining ? courseId : '',
        plannedOn,
        startsAt: startsAt.trim(),
        venue: venue.trim(),
        agenda: agenda.trim(),
        submit: true,
      });
      planId = saved.plan?.id ?? planId;
      if (newInvites.length > 0) {
        await api.call(METHOD.invitePlanSchools, { planId, schoolIds: newInvites.map((school) => school.id), channel });
      }
      onDone(planId);
    } catch (cause: unknown) {
      // A saved plan whose invitations failed is still saved: open it to retry.
      setError(planId && planId !== plan?.id ? `Saved, but the invitations were not recorded: ${describe(cause)}` : describe(cause));
      setIsBusy(false);
    }
  };

  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setPicked(next);
  };
  const isAll = all.length > 0 && chosen.size === all.length;
  const heading = isTraining ? 'Mobilize Schools (Training)' : 'Plan Cluster Meeting';
  const label = plan
    ? 'Save Changes'
    : isTraining
      ? `Send Invitations (${toInvite.length})`
      : 'Save & Invite Schools';

  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <LoanHero eyebrow={clusterName} title={plan ? 'Edit Meeting' : heading} onBack={onBack} />
      <LoanSheet>
        <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
          <View style={styles.cardHead}>
            {isTraining ? <GraduationCap size={26} color={colors.primary} /> : <CalendarDays size={26} color={colors.primary} />}
            <View style={styles.flex}>
              <Text style={[styles.cardTitle, { color: colors.text }]}>{isTraining ? 'New Training Mobilization' : 'New Cluster Meeting'}</Text>
              <Text style={[styles.muted, { color: colors.textMuted }]}>
                {isTraining ? 'Invite schools for an upcoming training.' : 'Plan and invite schools in your cluster.'}
              </Text>
            </View>
          </View>

          {isTraining ? (
            <View style={styles.field}>
              <FieldLabel>Training Topic *</FieldLabel>
              <Select
                label="Training Topic"
                value={courseId}
                placeholder="Choose a topic"
                choices={courses.map((choice) => ({ value: choice.id, label: choice.name }))}
                onChange={setCourseId}
                variant="form"
              />
            </View>
          ) : (
            <Field label="Meeting Title *" value={title} onChange={setTitle} placeholder="Term 1 Cluster Meeting" />
          )}
          <View style={styles.field}>
            <FieldLabel>{isTraining ? 'Training Date *' : 'Date *'}</FieldLabel>
            <DateField label={isTraining ? 'Training Date' : 'Date'} value={plannedOn} onChange={setPlannedOn} min={today} isRequired />
          </View>
          <Field label={isTraining ? 'Time' : 'Time *'} value={startsAt} onChange={setStartsAt} placeholder="10:00 AM" />
          <Field label={isTraining ? 'Training Venue *' : 'Venue *'} value={venue} onChange={setVenue} placeholder="Green Valley School" />
          {!isTraining ? (
            <Field label="Main Agenda (optional)" value={agenda} onChange={setAgenda} placeholder="Review SSA results, plan training…" isMultiline />
          ) : null}
        </View>

        {members.error ? <Notice text={members.error} isError /> : null}
        {members.schools === null && !members.error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading schools" /> : null}

        {isTraining && members.schools ? (
          <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
            <Text style={[styles.cardTitle, { color: colors.text }]}>
              Select Schools to Invite * <Text style={[styles.muted, { color: colors.textMuted }]}>({all.length} schools)</Text>
            </Text>
            <SchoolTick
              label="Select All"
              isOn={isAll}
              onPress={() => setPicked(isAll ? new Set() : new Set(all.map((school) => school.id)))}
            />
            {all.map((school) => (
              <SchoolTick key={school.id} label={school.name} detail={school.schoolId} isOn={chosen.has(school.id)} onPress={() => toggle(school.id)} />
            ))}
          </View>
        ) : null}

        {!isTraining && members.schools ? (
          <Text style={[styles.muted, { color: colors.textMuted }]}>
            {newInvites.length > 0
              ? `All ${all.length} member schools are invited.`
              : `All ${all.length} member schools are already invited.`}
          </Text>
        ) : null}

        {newInvites.length > 0 ? <ChoiceRow label="How are you inviting them? *" value={channel} choices={INVITE_CHANNELS} onChange={setChannel} /> : null}

        {error ? <Notice text={error} isError /> : null}
        {problem && !isBusy ? <Text style={[styles.muted, { color: colors.textMuted }]}>{problem}</Text> : null}
        <PrimaryButton label={isBusy ? 'Saving…' : label} icon={isTraining ? Send : CalendarDays} onPress={() => void save()} isDisabled={Boolean(problem) || isBusy} />
        <Text style={[styles.muted, { color: colors.textSubtle }]}>
          Your CCEO reviews it and schedules it in Edify. Invitations you record now carry over to that meeting.
        </Text>
      </LoanSheet>
    </ScrollView>
  );
}

interface SchoolTickProps {
  readonly label: string;
  readonly detail?: string;
  readonly isOn: boolean;
  readonly onPress: () => void;
}

export function SchoolTick({ label, detail, isOn, onPress }: SchoolTickProps) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="checkbox"
      accessibilityState={{ checked: isOn }}
      accessibilityLabel={label}
      style={[styles.tick, { borderTopColor: colors.border }]}
    >
      <View style={[styles.box, { borderColor: isOn ? colors.primary : colors.fieldBorder, backgroundColor: isOn ? colors.primary : 'transparent' }]}>
        {isOn ? <Check size={16} color={colors.primaryInk} /> : null}
      </View>
      <Text style={[styles.tickLabel, { color: colors.text }]} numberOfLines={2}>
        {label}
      </Text>
      {detail ? <Text style={[styles.muted, { color: colors.textSubtle }]}>{detail}</Text> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 12 },
  field: { gap: 6 },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  flex: { flex: 1, gap: 2 },
  cardTitle: { fontFamily: fonts.bold, fontSize: 16 },
  muted: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
  tick: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 48, borderTopWidth: StyleSheet.hairlineWidth },
  box: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  tickLabel: { flex: 1, fontFamily: fonts.semibold, fontSize: 15 },
});
