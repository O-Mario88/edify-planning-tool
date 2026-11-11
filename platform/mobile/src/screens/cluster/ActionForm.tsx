/**
 * "+ New Action" (owner brief, 2026-11-11, part 12): a Cluster Leader records
 * a need their schools have and asks staff for support. It is a support
 * request, not a scheduled activity: sending it routes each school to the
 * CCEO who holds it, and only their own planning makes it official work.
 * Required: schools, support needed, a description and a target date.
 * Success is shown only after the gateway confirms; a retry sends the same
 * submission key, so a lost answer never makes a second action.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Save, Send } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { Choice, ClusterActionView } from '../../gen/edify/clusters/v1/actions_pb';
import { ClusterActionService } from '../../gen/edify/clusters/v1/actions_pb';
import { fonts, radius, useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { Select } from '../../ui/Select';
import { fromDate, toIso } from '../../ui/calendar';
import { LoanHero, LoanSheet, PrimaryButton } from '../loans/loanUi';
import { PRIORITIES, newSubmissionKey } from './clusterData';
import { SchoolTick } from './MeetingForm';
import { ChoiceRow, Field, FieldLabel, Notice } from './opsParts';

const METHOD = ClusterActionService.method;

interface ActionFormProps {
  readonly clusterId: string;
  readonly clusterName: string;
  /** A draft being edited; absent for a new action. */
  readonly draft?: ClusterActionView;
  /** A meeting the action is raised from ("activity:<id>" or "plan:<id>"). */
  readonly fromMeeting?: string;
  readonly onDone: (actionId: string, isSent: boolean) => void;
  readonly onBack: () => void;
}

export function ActionForm({ clusterId, clusterName, draft, fromMeeting = '', onDone, onBack }: ActionFormProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [options, setOptions] = useState<{ kinds: readonly Choice[]; courses: readonly Choice[]; meetings: readonly Choice[]; schools: readonly Choice[] } | null>(null);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set(draft?.schoolIds ?? []));
  const [kind, setKind] = useState(draft?.supportKind ?? '');
  const [courseId, setCourseId] = useState(draft?.trainingCourseId ?? '');
  const [description, setDescription] = useState(draft?.description ?? '');
  const [outcome, setOutcome] = useState(draft?.expectedOutcome ?? '');
  const [targetOn, setTargetOn] = useState(draft?.targetOn ?? '');
  const [priority, setPriority] = useState(draft?.priority ?? 'normal');
  const [meeting, setMeeting] = useState(() => {
    if (draft?.sourceActivityId) {
      return `activity:${draft.sourceActivityId}`;
    }
    return draft?.sourcePlanId ? `plan:${draft.sourcePlanId}` : fromMeeting;
  });
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  // One key per form and per kind of save: a retry of the same press replays.
  const keys = useRef({ draft: newSubmissionKey(), send: newSubmissionKey() });
  const today = useMemo(() => toIso(fromDate(new Date())), []);

  useEffect(() => {
    api
      .call(METHOD.getActionOptions, { clusterId })
      .then((answer) => setOptions({ kinds: answer.supportKinds, courses: answer.courses, meetings: answer.meetings, schools: answer.schools }))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId]);

  const schools = options?.schools ?? [];
  const problem = (() => {
    if (picked.size === 0) {
      return 'Choose the schools that need support.';
    }
    if (!kind) {
      return 'Choose the support needed.';
    }
    if (!description.trim()) {
      return 'Describe the need in a sentence or two.';
    }
    if (!targetOn) {
      return 'Choose the target date.';
    }
    return '';
  })();

  const save = (submit: boolean) => {
    setIsBusy(true);
    setError('');
    api
      .call(METHOD.saveAction, {
        id: draft?.card?.id ?? '',
        clusterId,
        schoolIds: [...picked],
        supportKind: kind,
        trainingCourseId: kind === 'training' ? courseId : '',
        description: description.trim(),
        expectedOutcome: outcome.trim(),
        priority,
        targetOn,
        source: meeting ? 'meeting' : 'observation',
        sourceActivityId: meeting.startsWith('activity:') ? meeting.slice(9) : '',
        sourcePlanId: meeting.startsWith('plan:') ? meeting.slice(5) : '',
        submit,
        version: draft?.version ?? 0,
        idempotencyKey: submit ? keys.current.send : keys.current.draft,
      })
      .then((answer) => onDone(answer.action?.card?.id ?? '', submit))
      .catch((cause: unknown) => {
        setError(describe(cause));
        setIsBusy(false);
      });
  };

  const toggle = (id: string) => {
    const next = new Set(picked);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setPicked(next);
  };
  const isAll = schools.length > 0 && picked.size === schools.length;
  const box = [styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }];

  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <LoanHero eyebrow={clusterName} title={draft ? 'Edit Action' : 'New Action'} onBack={onBack} />
      <LoanSheet>
        {!options && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
        {options ? (
          <>
            <View style={box}>
              <View style={styles.field}>
                <FieldLabel>Support needed *</FieldLabel>
                <Select label="Support needed" value={kind} placeholder="Choose the support" choices={[...options.kinds]} onChange={setKind} variant="form" />
              </View>
              {kind === 'training' ? (
                <View style={styles.field}>
                  <FieldLabel>Training topic (optional)</FieldLabel>
                  <Select label="Training topic" value={courseId} placeholder="Choose a topic" choices={[...options.courses]} onChange={setCourseId} variant="form" />
                </View>
              ) : null}
              <Field label="Brief description *" value={description} onChange={setDescription} placeholder="What did you see, and what do the schools need?" isMultiline />
              <View style={styles.field}>
                <FieldLabel>Target date *</FieldLabel>
                <DateField label="Target date" value={targetOn} onChange={setTargetOn} min={today} isRequired />
              </View>
              <ChoiceRow label="Priority" value={priority} choices={PRIORITIES} onChange={setPriority} />
              <Field label="Expected outcome (optional)" value={outcome} onChange={setOutcome} placeholder="What should be different afterwards?" isMultiline />
              {options.meetings.length > 0 ? (
                <View style={styles.field}>
                  <FieldLabel>Raised at a meeting (optional)</FieldLabel>
                  <Select
                    label="Meeting"
                    value={meeting}
                    placeholder="Not raised at a meeting"
                    choices={[{ value: '', label: 'Not raised at a meeting' }, ...options.meetings]}
                    onChange={setMeeting}
                    variant="form"
                  />
                </View>
              ) : null}
            </View>

            <View style={box}>
              <Text style={[styles.cardTitle, { color: colors.text }]}>
                Schools * <Text style={[styles.muted, { color: colors.textMuted }]}>({picked.size} of {schools.length} chosen)</Text>
              </Text>
              <SchoolTick label="Select All" isOn={isAll} onPress={() => setPicked(isAll ? new Set() : new Set(schools.map((school) => school.value)))} />
              {schools.map((school) => (
                <SchoolTick key={school.value} label={school.label} isOn={picked.has(school.value)} onPress={() => toggle(school.value)} />
              ))}
            </View>
          </>
        ) : null}

        {error ? <Notice text={error} isError /> : null}
        {problem && options && !isBusy ? <Text style={[styles.muted, { color: colors.textMuted }]}>{problem}</Text> : null}
        <PrimaryButton label={isBusy ? 'Sending…' : 'Send for Support'} icon={Send} onPress={() => save(true)} isDisabled={Boolean(problem) || isBusy || !options} />
        <PrimaryButton label="Save Draft" icon={Save} isOutline onPress={() => save(false)} isDisabled={Boolean(problem) || isBusy || !options} />
        <Text style={[styles.muted, { color: colors.textSubtle }]}>
          Each school goes to the CCEO who holds it. They accept and plan the support in Edify; you follow its progress here.
        </Text>
      </LoanSheet>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 12 },
  field: { gap: 6 },
  cardTitle: { fontFamily: fonts.bold, fontSize: 16 },
  muted: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
});
