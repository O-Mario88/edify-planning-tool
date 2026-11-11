/**
 * One Cluster Action — "Action Details & Progress" (owner brief, 2026-11-11):
 * what was asked, for which schools, who holds each school's request and how
 * far its support has got (the linked official activity's own status), the
 * meetings' reviews, escalations and the full history. The leader and staff
 * see the same record; the controls are what the gateway says each may do.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { AlertTriangle, CalendarCheck, Check, ChevronDown, ChevronRight, Link2, MessageSquare, School, XCircle } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ActionSchool, ClusterActionView, LinkedActivity } from '../../gen/edify/clusters/v1/actions_pb';
import { ClusterActionService } from '../../gen/edify/clusters/v1/actions_pb';
import { fonts, radius, useTheme } from '../../theme';
import { Select } from '../../ui/Select';
import { LoanHero, LoanSheet, PrimaryButton, StatusChip } from '../loans/loanUi';
import { longDate } from './clusterRoutes';
import { ChoiceRow, Field, FieldLabel, Notice } from './opsParts';

const METHOD = ClusterActionService.method;

const RETURN_REASONS = [
  { value: 'already_scheduled', label: 'School already scheduled for this support' },
  { value: 'needs_clarification', label: 'Request needs clarification' },
  { value: 'not_eligible', label: 'School not eligible for this activity' },
  { value: 'unavailable', label: 'Requested support unavailable' },
  { value: 'wrong_staff', label: 'Incorrect responsible staff' },
  { value: 'duplicate', label: 'Duplicate of an existing request' },
  { value: 'other', label: 'Other' },
];

type Panel = '' | 'reply' | 'review' | 'escalate' | 'close' | 'cancel';

interface ActionDetailProps {
  readonly actionId: string;
  readonly onBack: () => void;
  readonly onEdit?: (view: ClusterActionView) => void;
  /** What the screen that opened it has to say (such as "Draft saved."). */
  readonly notice?: string;
}

export function ActionDetailScreen({ actionId, onBack, onEdit, notice: opening = '' }: ActionDetailProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [view, setView] = useState<ClusterActionView | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(opening);
  const [meetings, setMeetings] = useState<readonly { readonly value: string; readonly label: string }[]>([]);
  const [panel, setPanel] = useState<Panel>('');
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(() => {
    setError('');
    api
      .call(METHOD.getAction, { id: actionId })
      .then((answer) => setView(answer.action ?? null))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, actionId]);
  useEffect(load, [load]);

  // The cluster's meetings, for saying which one reviewed the action.
  const clusterId = view?.clusterId ?? '';
  const isReviewing = panel === 'review';
  useEffect(() => {
    if (!isReviewing || !clusterId) {
      return;
    }
    api
      .call(METHOD.getActionOptions, { clusterId })
      .then((answer) => setMeetings(answer.meetings))
      .catch(() => setMeetings([]));
  }, [api, clusterId, isReviewing]);

  // Every change answers with the action as it now stands; success is shown
  // only once the gateway has confirmed it.
  const run = (work: Promise<{ action?: ClusterActionView }>, done: string) => {
    setIsBusy(true);
    setError('');
    work
      .then((answer) => {
        if (answer.action) {
          setView(answer.action);
        }
        setNotice(done);
        setPanel('');
      })
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  const card = view?.card;
  const box = [styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }];
  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <LoanHero eyebrow={card ? `${card.ref} · ${card.clusterName}` : 'Cluster action'} title={card?.title ?? ' '} onBack={onBack} />
      <LoanSheet>
        {error ? <Notice text={error} isError /> : null}
        {notice ? <Notice text={notice} /> : null}
        {!view && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
        {view && card ? (
          <>
            <View style={box}>
              <View style={styles.row}>
                <StatusChip label={card.statusLabel} tone={card.statusTone} />
                {card.isOverdue ? <StatusChip label="Overdue" tone="alert" /> : null}
                {card.priority !== 'normal' ? <StatusChip label={card.priority === 'urgent' ? 'Urgent' : 'High priority'} tone="caution" /> : null}
              </View>
              {card.progressSummary ? <Text style={[styles.strong, { color: colors.text }]}>{card.progressSummary}</Text> : null}
              <Fact label="Support needed" value={view.trainingCourse ? `${view.supportKindLabel}: ${view.trainingCourse}` : view.supportKindLabel} />
              <Fact label="Need" value={view.description} />
              <Fact label="Expected outcome" value={view.expectedOutcome} />
              <Fact label="Target date" value={longDate(view.targetOn)} />
              <Fact label="Raised at" value={view.sourceMeeting ? `${view.sourceMeeting} (meeting)` : view.sourceLabel} />
              <Fact label="Raised by" value={`${view.createdBy} · ${longDate(view.createdAt)} · FY ${view.fiscalYear}`} />
              {view.resolutionDays > 0 ? <Fact label="Resolution time" value={`${view.resolutionDays} days from request to verified support`} /> : null}
              {view.closeSummary ? <Fact label="Outcome" value={view.closeSummary} /> : null}
            </View>

            <Text style={[styles.section, { color: colors.textMuted }]}>SCHOOLS</Text>
            {view.schools.length === 0 ? (
              <Text style={[styles.muted, { color: colors.textMuted }]}>{view.schoolIds.length} schools chosen. Each goes to its CCEO when you send the action.</Text>
            ) : null}
            {view.schools.map((school) => (
              <SchoolCard key={school.schoolId} actionId={actionId} school={school} isBusy={isBusy} onRun={run} />
            ))}

            {view.canEdit || view.canReply || view.canReview || view.canEscalate || view.canClose || view.canCancel ? (
              <Text style={[styles.section, { color: colors.textMuted }]}>YOUR NEXT STEP</Text>
            ) : null}
            {view.canSubmit ? (
              <PrimaryButton
                label={isBusy ? 'Sending…' : 'Send for Support'}
                icon={Check}
                isDisabled={isBusy}
                onPress={() =>
                  run(
                    api.call(METHOD.saveAction, {
                      id: view.card?.id ?? '',
                      clusterId: view.clusterId,
                      schoolIds: [...view.schoolIds],
                      supportKind: view.supportKind,
                      trainingCourseId: view.trainingCourseId,
                      title: view.title,
                      description: view.description,
                      expectedOutcome: view.expectedOutcome,
                      priority: view.priority,
                      targetOn: view.targetOn,
                      source: view.source,
                      sourceActivityId: view.sourceActivityId,
                      sourcePlanId: view.sourcePlanId,
                      version: view.version,
                      submit: true,
                    }),
                    'Sent. Each school went to the CCEO who holds it.',
                  )
                }
              />
            ) : null}
            {view.canEdit && onEdit ? <PrimaryButton label="Edit draft" isOutline onPress={() => onEdit(view)} /> : null}
            {view.canReply ? <PanelButton label="Reply to your CCEO" icon={MessageSquare} panel="reply" current={panel} onToggle={setPanel} /> : null}
            {panel === 'reply' ? (
              <NoteForm label="Your reply *" action="Send reply" isBusy={isBusy} onSubmit={(note) => run(api.call(METHOD.replyToAction, { id: actionId, note }), 'Reply sent. The request is back with your CCEO.')} />
            ) : null}
            {view.canReview ? <PanelButton label="Review at a meeting" icon={CalendarCheck} panel="review" current={panel} onToggle={setPanel} /> : null}
            {panel === 'review' ? <ReviewForm meetings={meetings} isBusy={isBusy} onSubmit={(review) => run(api.call(METHOD.reviewAction, { id: actionId, ...review }), 'Review recorded.')} /> : null}
            {view.canClose ? <PanelButton label="Close the action" icon={Check} panel="close" current={panel} onToggle={setPanel} /> : null}
            {panel === 'close' ? (
              <NoteForm label="What was achieved? *" action="Close" isBusy={isBusy} onSubmit={(summary) => run(api.call(METHOD.closeAction, { id: actionId, summary }), 'Action closed.')} />
            ) : null}
            {view.canEscalate ? <PanelButton label="Escalate to the Program Lead" icon={AlertTriangle} panel="escalate" current={panel} onToggle={setPanel} /> : null}
            {panel === 'escalate' ? (
              <NoteForm label="Why does it need the Program Lead? *" action="Escalate" isBusy={isBusy} onSubmit={(reason) => run(api.call(METHOD.escalateAction, { id: actionId, reason }), 'Escalated to the supervising Program Lead.')} />
            ) : null}
            {view.canCancel ? <PanelButton label="Cancel the action" icon={XCircle} panel="cancel" current={panel} onToggle={setPanel} isDanger /> : null}
            {panel === 'cancel' ? (
              <NoteForm label="Why is it cancelled? *" action="Cancel action" isBusy={isBusy} onSubmit={(reason) => run(api.call(METHOD.cancelAction, { id: actionId, reason }), 'Action cancelled.')} />
            ) : null}

            {view.reviews.length > 0 ? <Text style={[styles.section, { color: colors.textMuted }]}>MEETING REVIEWS</Text> : null}
            {view.reviews.map((review) => (
              <View key={review.id} style={box}>
                <Text style={[styles.strong, { color: colors.text }]}>{review.meeting || 'Review'} · {longDate(review.at)}</Text>
                <Fact label="Progress" value={review.progress} />
                <Fact label="Challenges" value={review.challenges} />
                <Fact label="Next step" value={review.nextStep} />
                <Fact label="Agreed" value={{ continue: 'Continue follow-up', escalate: 'Escalate', propose_closure: 'Propose closure' }[review.outcome] ?? review.outcome} />
              </View>
            ))}

            {view.escalations.length > 0 ? <Text style={[styles.section, { color: colors.textMuted }]}>ESCALATIONS</Text> : null}
            {view.escalations.map((x) => (
              <View key={x.id} style={box}>
                <View style={styles.row}>
                  <StatusChip label={x.status === 'open' ? 'Open' : 'Resolved'} tone={x.status === 'open' ? 'caution' : 'good'} />
                  <Text style={[styles.muted, { color: colors.textMuted }]}>{longDate(x.at)} · to {x.toStaff || 'the Program Lead'}</Text>
                </View>
                <Text style={[styles.body, { color: colors.text }]}>{x.reason}</Text>
                {x.resolution ? <Fact label="Resolution" value={x.resolution} /> : null}
                {x.canResolve ? (
                  <NoteForm label="How was it resolved? *" action="Resolve" isBusy={isBusy} onSubmit={(resolution) => run(api.call(METHOD.resolveEscalation, { escalationId: x.id, resolution }), 'Escalation resolved.')} />
                ) : null}
              </View>
            ))}

            <Pressable onPress={() => setIsHistoryOpen(!isHistoryOpen)} accessibilityRole="button" accessibilityState={{ expanded: isHistoryOpen }} style={[box, styles.row]}>
              <Text style={[styles.strong, styles.flex, { color: colors.text }]}>History ({view.history.length})</Text>
              {isHistoryOpen ? <ChevronDown size={20} color={colors.textMuted} /> : <ChevronRight size={20} color={colors.textMuted} />}
            </Pressable>
            {isHistoryOpen
              ? view.history.map((event, index) => (
                  <View key={`${event.at}-${index}`} style={[styles.event, { borderLeftColor: colors.border }]}>
                    <Text style={[styles.strong, { color: colors.text }]}>{event.label || event.event}</Text>
                    <Text style={[styles.muted, { color: colors.textMuted }]}>
                      {[event.at, event.actor, event.school].filter(Boolean).join(' · ')}
                    </Text>
                    {event.note ? <Text style={[styles.body, { color: colors.text }]}>{event.note}</Text> : null}
                  </View>
                ))
              : null}
          </>
        ) : null}
      </LoanSheet>
    </ScrollView>
  );
}

function SchoolCard({ actionId, school, isBusy, onRun }: {
  readonly actionId: string;
  readonly school: ActionSchool;
  readonly isBusy: boolean;
  readonly onRun: (work: Promise<{ action?: ClusterActionView }>, done: string) => void;
}) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [mode, setMode] = useState<'' | 'clarify' | 'return' | 'link' | 'unlink'>('');
  const [code, setCode] = useState('');
  const [response, setResponse] = useState<'return' | 'decline'>('return');
  const [activities, setActivities] = useState<readonly LinkedActivity[] | null>(null);
  const respond = (kind: string, note = '', reasonCode = '') =>
    onRun(api.call(METHOD.respondToRequest, { actionId, schoolId: school.schoolId, response: kind, note, reasonCode }), {
      acknowledge: 'Acknowledged.',
      accept: 'Accepted. Plan the activity in Edify, then link it here.',
      clarify: 'Clarification requested from the Cluster Leader.',
      return: 'Returned to the Cluster Leader with your reason.',
      decline: 'Declined with your reason.',
    }[kind] ?? 'Saved.');
  const openLinks = () => {
    setMode(mode === 'link' ? '' : 'link');
    api
      .call(METHOD.listLinkableActivities, { actionId, schoolId: school.schoolId })
      .then((answer) => setActivities(answer.activities))
      .catch(() => setActivities([]));
  };
  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <View style={styles.row}>
        <School size={20} color={colors.primary} />
        <Text style={[styles.strong, styles.flex, { color: colors.text }]}>{school.name}</Text>
      </View>
      <Text style={[styles.muted, { color: colors.textMuted }]}>
        {[school.edifySchoolId, school.responsibleStaff || { supervisor: 'With the Program Lead to assign', unassigned: 'Waiting for assignment' }[school.routedTo]].filter(Boolean).join(' · ')}
      </Text>
      <View style={styles.row}>
        <StatusChip label={school.progressLabel} tone={school.progressTone} />
      </View>
      {school.note ? <Text style={[styles.body, { color: colors.text }]}>“{school.note}”</Text> : null}
      {school.activity ? (
        <Text style={[styles.muted, { color: colors.textMuted }]}>
          Linked activity: {school.activity.name} · {longDate(school.activity.date)} · {school.activity.statusLabel}
        </Text>
      ) : null}
      {school.canRespond ? (
        <>
          <View style={styles.buttons}>
            {school.progress === 'awaiting_review' ? <PrimaryButton label="Acknowledge" isOutline isDisabled={isBusy} onPress={() => respond('acknowledge')} /> : null}
            <PrimaryButton label="Accept & Plan" icon={Check} isDisabled={isBusy} onPress={() => respond('accept')} />
          </View>
          <View style={styles.buttons}>
            <PrimaryButton label="Request Clarification" isOutline isDisabled={isBusy} onPress={() => setMode(mode === 'clarify' ? '' : 'clarify')} />
            <PrimaryButton label="Return with Reason" isOutline isDisabled={isBusy} onPress={() => setMode(mode === 'return' ? '' : 'return')} />
          </View>
        </>
      ) : null}
      {mode === 'clarify' ? <NoteForm label="What do you need to know? *" action="Ask the leader" isBusy={isBusy} onSubmit={(note) => respond('clarify', note)} /> : null}
      {mode === 'return' ? (
        <>
          <ChoiceRow label="Return or decline?" value={response} choices={[{ value: 'return', label: 'Return to the leader' }, { value: 'decline', label: 'Decline' }]} onChange={(value) => setResponse(value === 'decline' ? 'decline' : 'return')} />
          <View style={styles.field}>
            <FieldLabel>Reason *</FieldLabel>
            <Select label="Reason" value={code} placeholder="Choose the reason" choices={RETURN_REASONS} onChange={setCode} variant="form" />
          </View>
          <NoteForm label="Explain it to the leader *" action={response === 'decline' ? 'Decline' : 'Return'} isBusy={isBusy || !code} onSubmit={(note) => respond(response, note, code)} />
        </>
      ) : null}
      {school.canLink ? (
        <PrimaryButton label={school.activity ? 'Change linked activity' : 'Link the planned activity'} icon={Link2} isOutline isDisabled={isBusy} onPress={openLinks} />
      ) : null}
      {mode === 'link' ? (
        <View style={styles.links}>
          {activities === null ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading activities" /> : null}
          {activities?.length === 0 ? (
            <Text style={[styles.muted, { color: colors.textMuted }]}>
              No planned activity for this school or its cluster yet. Plan the visit or training in Edify (My Plan or the school's page), then link it here.
            </Text>
          ) : null}
          {activities?.map((activity) => (
            <Pressable
              key={activity.id}
              onPress={() => onRun(api.call(METHOD.linkActivity, { actionId, schoolId: school.schoolId, activityId: activity.id }), 'Linked. Its own status now shows this school’s progress.')}
              accessibilityRole="button"
              style={[styles.linkRow, { borderColor: colors.border }]}
            >
              <Text style={[styles.strong, { color: colors.text }]}>{activity.name}</Text>
              <Text style={[styles.muted, { color: colors.textMuted }]}>{longDate(activity.date)} · {activity.statusLabel}</Text>
            </Pressable>
          ))}
          {school.activity ? (
            <NoteForm label="Why unlink the current activity? *" action="Unlink" isBusy={isBusy} onSubmit={(reason) => onRun(api.call(METHOD.unlinkActivity, { actionId, schoolId: school.schoolId, reason }), 'Unlinked.')} />
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

function ReviewForm({ meetings, isBusy, onSubmit }: {
  readonly meetings: readonly { readonly value: string; readonly label: string }[];
  readonly isBusy: boolean;
  readonly onSubmit: (review: { meetingActivityId: string; meetingPlanId: string; progress: string; challenges: string; nextStep: string; outcome: string }) => void;
}) {
  const [meeting, setMeeting] = useState('');
  const [progress, setProgress] = useState('');
  const [challenges, setChallenges] = useState('');
  const [nextStep, setNextStep] = useState('');
  const [outcome, setOutcome] = useState('continue');
  return (
    <View style={styles.form}>
      {meetings.length > 0 ? (
        <View style={styles.field}>
          <FieldLabel>Meeting (optional)</FieldLabel>
          <Select label="Meeting" value={meeting} placeholder="Choose the meeting" choices={meetings} onChange={setMeeting} variant="form" />
        </View>
      ) : null}
      <Field label="Progress discussed" value={progress} onChange={setProgress} isMultiline />
      <Field label="Challenges" value={challenges} onChange={setChallenges} isMultiline />
      <Field label="Agreed next step" value={nextStep} onChange={setNextStep} isMultiline />
      <ChoiceRow
        label="The meeting agreed to"
        value={outcome}
        choices={[
          { value: 'continue', label: 'Continue follow-up' },
          { value: 'escalate', label: 'Escalate' },
          { value: 'propose_closure', label: 'Propose closure' },
        ]}
        onChange={setOutcome}
      />
      <PrimaryButton
        label="Record review"
        isDisabled={isBusy || (!progress.trim() && !nextStep.trim())}
        onPress={() =>
          onSubmit({
            meetingActivityId: meeting.startsWith('activity:') ? meeting.slice(9) : '',
            meetingPlanId: meeting.startsWith('plan:') ? meeting.slice(5) : '',
            progress: progress.trim(),
            challenges: challenges.trim(),
            nextStep: nextStep.trim(),
            outcome,
          })
        }
      />
    </View>
  );
}

function NoteForm({ label, action, isBusy, onSubmit }: { readonly label: string; readonly action: string; readonly isBusy: boolean; readonly onSubmit: (note: string) => void }) {
  const [note, setNote] = useState('');
  return (
    <View style={styles.form}>
      <Field label={label} value={note} onChange={setNote} isMultiline />
      <PrimaryButton label={action} isDisabled={isBusy || !note.trim()} onPress={() => onSubmit(note.trim())} />
    </View>
  );
}

function PanelButton({ label, icon, panel, current, onToggle, isDanger }: {
  readonly label: string;
  readonly icon: typeof Check;
  readonly panel: Panel;
  readonly current: Panel;
  readonly onToggle: (panel: Panel) => void;
  readonly isDanger?: boolean;
}) {
  const { colors } = useTheme();
  const Icon = icon;
  return (
    <Pressable
      onPress={() => onToggle(current === panel ? '' : panel)}
      accessibilityRole="button"
      accessibilityState={{ expanded: current === panel }}
      style={[styles.panelButton, { borderColor: isDanger ? colors.danger : colors.primary }]}
    >
      <Icon size={18} color={isDanger ? colors.danger : colors.primary} />
      <Text style={[styles.panelLabel, { color: isDanger ? colors.danger : colors.primary }]}>{label}</Text>
    </Pressable>
  );
}

function Fact({ label, value }: { readonly label: string; readonly value: string }) {
  const { colors } = useTheme();
  if (!value) {
    return null;
  }
  return (
    <View style={styles.fact}>
      <Text style={[styles.muted, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.body, { color: colors.text }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  flex: { flex: 1 },
  strong: { fontFamily: fonts.bold, fontSize: 15 },
  body: { fontFamily: fonts.medium, fontSize: 14, lineHeight: 20 },
  muted: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
  section: { fontFamily: fonts.bold, fontSize: 12, letterSpacing: 0.8, marginTop: 6 },
  fact: { gap: 1 },
  buttons: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  form: { gap: 10 },
  field: { gap: 6 },
  links: { gap: 8 },
  linkRow: { borderWidth: 1, borderRadius: radius.md, padding: 12, gap: 2, minHeight: 48 },
  event: { borderLeftWidth: 3, paddingLeft: 10, gap: 2, marginLeft: 4 },
  panelButton: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, borderWidth: 1.5, borderRadius: radius.md, minHeight: 48 },
  panelLabel: { fontFamily: fonts.bold, fontSize: 15 },
});
