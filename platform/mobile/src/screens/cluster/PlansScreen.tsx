/**
 * The leader's meeting plans (brief A4): Draft → Submitted → Approved or
 * Returned → Scheduled. A training names one of the governed courses a
 * cluster may receive; a meeting shows no training field. The CCEO reviews,
 * and schedules the official activity in Edify; the plan then shows it.
 */
import { useCallback, useEffect, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { CourseChoice, MeetingPlan } from '../../gen/edify/clusters/v1/mobilization_pb';
import { ClusterMobilizationService } from '../../gen/edify/clusters/v1/mobilization_pb';
import { useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { DrawerButton } from '../../ui/drawerParts';
import { Select } from '../../ui/Select';
import { toIso, fromDate } from '../../ui/calendar';
import { longDate } from './clusterRoutes';
import { ChoiceRow, Field, Muted, Notice, OpsCard, OpsTitle, SectionLabel, StateBadge, opsStyles } from './opsParts';

const METHOD = ClusterMobilizationService.method;
const CATEGORIES = [
  { value: 'only_meeting', label: 'Meeting' },
  { value: 'cluster_leaders', label: 'Cluster leaders meeting' },
  { value: 'training', label: 'Cluster training' },
];

interface Draft {
  id: string;
  category: string;
  title: string;
  trainingCourseId: string;
  plannedOn: string;
  startsAt: string;
  venue: string;
  objectives: string;
  agenda: string;
  expectedParticipants: string;
  facilitator: string;
  notes: string;
}

const EMPTY: Draft = {
  id: '', category: 'only_meeting', title: '', trainingCourseId: '', plannedOn: '', startsAt: '', venue: '',
  objectives: '', agenda: '', expectedParticipants: '', facilitator: '', notes: '',
};

function draftOf(plan: MeetingPlan): Draft {
  return {
    id: plan.id, category: plan.category, title: plan.title, trainingCourseId: plan.trainingCourseId,
    plannedOn: plan.plannedOn, startsAt: plan.startsAt, venue: plan.venue, objectives: plan.objectives,
    agenda: plan.agenda, expectedParticipants: plan.expectedParticipants ? String(plan.expectedParticipants) : '',
    facilitator: plan.facilitator, notes: plan.notes,
  };
}

export function PlansScreen({ clusterId, clusterName }: { readonly clusterId: string; readonly clusterName: string }) {
  const { api } = useSession();
  const [plans, setPlans] = useState<readonly MeetingPlan[]>([]);
  const [courses, setCourses] = useState<readonly CourseChoice[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(() => {
    api
      .call(METHOD.listPlans, { clusterId })
      .then((answer) => setPlans(answer.plans))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, clusterId]);
  useEffect(load, [load]);
  useEffect(() => {
    api
      .call(METHOD.getPlanOptions, {})
      .then((answer) => setCourses(answer.courses))
      .catch(() => undefined);
  }, [api]);

  const save = (submit: boolean) => {
    if (!draft) {
      return;
    }
    setIsBusy(true);
    setError('');
    api
      .call(METHOD.savePlan, {
        ...draft,
        clusterId,
        trainingCourseId: draft.category === 'training' ? draft.trainingCourseId : '',
        expectedParticipants: Number(draft.expectedParticipants || '0'),
        submit,
      })
      .then(() => {
        setNotice(submit ? 'Sent to your CCEO for review.' : 'Draft saved.');
        setDraft(null);
        load();
      })
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  return (
    <ScrollView contentContainerStyle={opsStyles.page} keyboardShouldPersistTaps="handled">
      <OpsTitle eyebrow={clusterName} title="Meeting plans" copy="Propose a meeting or a cluster training. Your CCEO reviews it and schedules it in Edify." />
      <Notice text={notice} />
      <Notice text={error} isError />
      {draft ? (
        <PlanForm draft={draft} courses={courses} onChange={setDraft} onSave={save} onCancel={() => setDraft(null)} isBusy={isBusy} />
      ) : (
        <DrawerButton label="Plan a meeting" isPrimary onPress={() => setDraft({ ...EMPTY })} />
      )}
      <SectionLabel>Your plans</SectionLabel>
      {plans.length === 0 ? <Muted>No plan yet.</Muted> : null}
      {plans.map((plan) => (
        <PlanCard key={plan.id} plan={plan} onEdit={() => setDraft(draftOf(plan))} />
      ))}
    </ScrollView>
  );
}

function PlanCard({ plan, onEdit }: { readonly plan: MeetingPlan; readonly onEdit: () => void }) {
  const { colors } = useTheme();
  return (
    <OpsCard>
      <View style={opsStyles.spread}>
        <View style={opsStyles.grow}>
          <Text style={[opsStyles.name, { color: colors.text }]}>{plan.title}</Text>
          <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
            {CATEGORIES.find((c) => c.value === plan.category)?.label} · {longDate(plan.plannedOn)}
            {plan.trainingCourse ? ` · ${plan.trainingCourse}` : ''}
          </Text>
        </View>
        <StateBadge state={plan.status} />
      </View>
      {plan.status === 'returned' && plan.reviewNote ? (
        <Text style={[opsStyles.meta, { color: colors.warning }]}>Your CCEO: “{plan.reviewNote}”</Text>
      ) : null}
      {plan.history.map((event, index) => (
        <Text key={index} style={[opsStyles.meta, { color: colors.textSubtle }]}>
          {event.event} by {event.actor || 'someone'} · {event.at.slice(0, 10)}
        </Text>
      ))}
      {plan.canEdit ? <DrawerButton label={plan.status === 'returned' ? 'Revise' : 'Edit'} onPress={onEdit} /> : null}
    </OpsCard>
  );
}

interface PlanFormProps {
  readonly draft: Draft;
  readonly courses: readonly CourseChoice[];
  readonly onChange: (draft: Draft) => void;
  readonly onSave: (submit: boolean) => void;
  readonly onCancel: () => void;
  readonly isBusy: boolean;
}

function PlanForm({ draft, courses, onChange, onSave, onCancel, isBusy }: PlanFormProps) {
  const set = (key: keyof Draft) => (value: string) => onChange({ ...draft, [key]: value });
  const isTraining = draft.category === 'training';
  const isReady = draft.title.trim() !== '' && draft.plannedOn !== '' && (!isTraining || draft.trainingCourseId !== '');
  return (
    <OpsCard>
      <SectionLabel>{draft.id ? 'Edit plan' : 'New plan'}</SectionLabel>
      <ChoiceRow label="What it is" value={draft.category} choices={CATEGORIES} onChange={set('category')} />
      <Field label="Title" value={draft.title} onChange={set('title')} placeholder="Term 1 planning meeting" />
      {isTraining ? (
        <Select
          label="Training course"
          value={draft.trainingCourseId}
          choices={courses.map((c) => ({ value: c.id, label: c.intervention ? `${c.name} (${c.intervention})` : c.name }))}
          placeholder="Choose the course"
          onChange={set('trainingCourseId')}
          variant="form"
        />
      ) : null}
      <DateField label="Date" value={draft.plannedOn} onChange={set('plannedOn')} min={toIso(fromDate(new Date()))} isRequired />
      <Field label="Time" value={draft.startsAt} onChange={set('startsAt')} placeholder="9:00 am" />
      <Field label="Venue or online link" value={draft.venue} onChange={set('venue')} />
      <Field label="Objectives" value={draft.objectives} onChange={set('objectives')} isMultiline />
      <Field label="Agenda" value={draft.agenda} onChange={set('agenda')} isMultiline />
      <Field label="Expected participants" value={draft.expectedParticipants} onChange={(v) => set('expectedParticipants')(v.replace(/\D/g, ''))} isNumeric />
      <Field label="Facilitator" value={draft.facilitator} onChange={set('facilitator')} />
      <Field label="Notes" value={draft.notes} onChange={set('notes')} isMultiline />
      <View style={{ gap: 8 }}>
        <DrawerButton label="Submit for review" isPrimary isBusy={isBusy} isDisabled={!isReady} onPress={() => onSave(true)} />
        <DrawerButton label="Save draft" isBusy={isBusy} isDisabled={!isReady} onPress={() => onSave(false)} />
        <DrawerButton label="Cancel" onPress={onCancel} />
      </View>
    </OpsCard>
  );
}
