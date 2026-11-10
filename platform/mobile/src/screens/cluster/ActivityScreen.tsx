/**
 * One cluster activity, as its leader works it (brief A5-A6): the member
 * schools and where each stands — not invited, invited, its answer, then
 * attended or absent from an attendance record (never from the answer) — and
 * the minutes. Inviting stops once the activity is held; attendance opens on
 * its day. The app records each invitation; no message is sent from here, and
 * the delivery says "recorded", never "delivered".
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';
import { Check, ChevronLeft } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetMobilizationResponse, SchoolMobilization } from '../../gen/edify/clusters/v1/mobilization_pb';
import { ClusterMobilizationService } from '../../gen/edify/clusters/v1/mobilization_pb';
import { useTheme } from '../../theme';
import { DrawerButton } from '../../ui/drawerParts';
import { longDate } from './clusterRoutes';
import { ChoiceRow, Field, Muted, Notice, OpsCard, OpsTitle, SectionLabel, StateBadge, opsStyles, stateLabel } from './opsParts';

const METHOD = ClusterMobilizationService.method;
const CHANNELS = [
  { value: 'in_person', label: 'In person' },
  { value: 'phone', label: 'Phone' },
  { value: 'sms', label: 'SMS' },
  { value: 'email', label: 'Email' },
  { value: 'whatsapp', label: 'WhatsApp' },
];
const ANSWERS = ['acknowledged', 'confirmed', 'declined'] as const;
const SUMMARY_ORDER = ['not_invited', 'invited', 'acknowledged', 'confirmed', 'declined', 'no_response', 'attended', 'absent'];

export function ActivityScreen({ activityId, onBack }: { readonly activityId: string; readonly onBack: () => void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [board, setBoard] = useState<GetMobilizationResponse | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [picked, setPicked] = useState<readonly string[]>([]);
  const [channel, setChannel] = useState('phone');
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(() => {
    api
      .call(METHOD.getMobilization, { activityId })
      .then((answer) => {
        setBoard(answer);
        setError('');
      })
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, activityId]);
  useEffect(load, [load]);

  const run = (work: Promise<unknown>, message: string) => {
    setIsBusy(true);
    setNotice('');
    work
      .then(() => {
        setNotice(message);
        load();
      })
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  if (!board) {
    return (
      <ScrollView contentContainerStyle={opsStyles.page}>
        <Back onBack={onBack} />
        {error ? <Notice text={error} isError /> : <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />}
      </ScrollView>
    );
  }
  const activity = board.activity;
  const uninvited = board.schools.filter((s) => s.state === 'not_invited');
  const summary = SUMMARY_ORDER.filter((key) => board.counts[key]).map((key) => `${board.counts[key]} ${stateLabel(key).toLowerCase()}`);

  return (
    <ScrollView contentContainerStyle={opsStyles.page} keyboardShouldPersistTaps="handled">
      <Back onBack={onBack} />
      <OpsTitle
        eyebrow={activity?.type}
        title={activity?.name ?? ''}
        copy={`${longDate(activity?.date ?? '')} · ${activity?.location || 'Venue to be set'}`}
      />
      <Muted>{summary.join(' · ') || 'No member school yet.'}</Muted>
      <Notice text={notice} />
      <Notice text={error} isError />

      {board.canInvite && uninvited.length > 0 ? (
        <OpsCard>
          <SectionLabel>Invite schools</SectionLabel>
          <ChoiceRow label="How you invited them" value={channel} choices={CHANNELS} onChange={setChannel} />
          {uninvited.map((school) => {
            const isOn = picked.includes(school.schoolId);
            return (
              <Pressable
                key={school.schoolId}
                onPress={() => setPicked(isOn ? picked.filter((id) => id !== school.schoolId) : [...picked, school.schoolId])}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: isOn }}
                accessibilityLabel={`Invite ${school.name}`}
                style={opsStyles.row}
              >
                <View
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 6,
                    borderWidth: 1.5,
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderColor: isOn ? colors.primary : colors.borderStrong,
                    backgroundColor: isOn ? colors.primary : colors.raised,
                  }}
                >
                  {isOn ? <Check size={14} color={colors.primaryInk} /> : null}
                </View>
                <View style={opsStyles.grow}>
                  <Text style={[opsStyles.name, { color: colors.text }]}>{school.name}</Text>
                  <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
                    {school.edifySchoolId} · {school.district}
                  </Text>
                </View>
              </Pressable>
            );
          })}
          <Pressable onPress={() => setPicked(uninvited.map((s) => s.schoolId))} accessibilityRole="button" hitSlop={8}>
            <Text style={[opsStyles.smallText, { color: colors.link }]}>Select all {uninvited.length}</Text>
          </Pressable>
          <DrawerButton
            label={picked.length ? `Record ${picked.length} invitation${picked.length === 1 ? '' : 's'}` : 'Choose schools'}
            isPrimary
            isBusy={isBusy}
            isDisabled={picked.length === 0}
            onPress={() => {
              run(api.call(METHOD.inviteSchools, { activityId, schoolIds: [...picked], channel }), 'Invitations recorded.');
              setPicked([]);
            }}
          />
          <Muted>The app records the invitation; it sends no message. Delivery shows as “recorded”.</Muted>
        </OpsCard>
      ) : null}

      <SectionLabel>Schools</SectionLabel>
      {board.schools.map((school) => (
        <SchoolCard
          key={school.schoolId}
          school={school}
          canAnswer={board.canInvite}
          isBusy={isBusy}
          onAnswer={(status) => run(api.call(METHOD.recordResponse, { invitationId: school.invitationId, status }), `${school.name}: ${stateLabel(status)}.`)}
          onFollowUp={() => run(api.call(METHOD.followUp, { invitationId: school.invitationId }), `Follow-up recorded for ${school.name}.`)}
        />
      ))}

      {board.canRecordAttendance ? (
        <Attendance board={board} isBusy={isBusy} onSave={(entries) => run(api.call(METHOD.recordAttendance, { activityId, entries }), 'Attendance recorded.')} />
      ) : null}

      <MinutesCard
        board={board}
        isBusy={isBusy}
        onSave={(discussion, decisions, submit) =>
          run(api.call(METHOD.saveMinutes, { activityId, discussion, decisions, submit }), submit ? 'Minutes submitted.' : 'Minutes saved.')
        }
      />
    </ScrollView>
  );
}

function Back({ onBack }: { readonly onBack: () => void }) {
  const { colors } = useTheme();
  return (
    <Pressable onPress={onBack} accessibilityRole="button" hitSlop={10} style={opsStyles.row}>
      <ChevronLeft size={16} color={colors.link} />
      <Text style={[opsStyles.smallText, { color: colors.link }]}>Activities</Text>
    </Pressable>
  );
}

interface SchoolCardProps {
  readonly school: SchoolMobilization;
  readonly canAnswer: boolean;
  readonly isBusy: boolean;
  readonly onAnswer: (status: string) => void;
  readonly onFollowUp: () => void;
}

function SchoolCard({ school, canAnswer, isBusy, onAnswer, onFollowUp }: SchoolCardProps) {
  const { colors } = useTheme();
  const isInvited = school.invitationId !== '';
  return (
    <OpsCard>
      <View style={opsStyles.spread}>
        <View style={opsStyles.grow}>
          <Text style={[opsStyles.name, { color: colors.text }]}>{school.name}</Text>
          <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
            {school.edifySchoolId} · {school.district}
          </Text>
        </View>
        <StateBadge state={school.state} />
      </View>
      {isInvited ? (
        <Text style={[opsStyles.meta, { color: colors.textSubtle }]}>
          {school.channel.replace('_', ' ')} · {school.deliveryStatus} · {school.followUps} follow-up{school.followUps === 1 ? '' : 's'}
          {school.attendanceSource === 'leader' ? ' · attendance: your record' : ''}
          {school.attendanceSource === 'official' ? ' · attendance: staff record' : ''}
        </Text>
      ) : null}
      {isInvited && canAnswer ? (
        <View style={opsStyles.actions}>
          {ANSWERS.map((status) => (
            <Pressable
              key={status}
              disabled={isBusy}
              onPress={() => onAnswer(status)}
              accessibilityRole="button"
              accessibilityState={{ selected: school.state === status }}
              style={[opsStyles.small, { borderColor: school.state === status ? colors.primary : colors.border, backgroundColor: school.state === status ? colors.primarySoft : colors.raised }]}
            >
              <Text style={[opsStyles.smallText, { color: colors.link }]}>{stateLabel(status)}</Text>
            </Pressable>
          ))}
          <Pressable disabled={isBusy} onPress={onFollowUp} accessibilityRole="button" style={[opsStyles.small, { borderColor: colors.border }]}>
            <Text style={[opsStyles.smallText, { color: colors.text }]}>Followed up</Text>
          </Pressable>
        </View>
      ) : null}
    </OpsCard>
  );
}

interface AttendanceProps {
  readonly board: GetMobilizationResponse;
  readonly isBusy: boolean;
  readonly onSave: (entries: { schoolId: string; attended: boolean; participants: number }[]) => void;
}

function Attendance({ board, isBusy, onSave }: AttendanceProps) {
  const { colors } = useTheme();
  const [marks, setMarks] = useState<Readonly<Record<string, { attended: boolean; participants: string }>>>(() =>
    Object.fromEntries(
      board.schools.map((s) => [s.schoolId, { attended: s.state === 'attended', participants: s.participants ? String(s.participants) : '' }]),
    ),
  );
  return (
    <OpsCard>
      <SectionLabel>Attendance</SectionLabel>
      <Muted>Your record of who came. Staff complete the activity in Edify; their record then counts.</Muted>
      {board.schools.map((school) => {
        const mark = marks[school.schoolId] ?? { attended: false, participants: '' };
        return (
          <View key={school.schoolId} style={opsStyles.spread}>
            <Pressable
              onPress={() => setMarks({ ...marks, [school.schoolId]: { ...mark, attended: !mark.attended } })}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: mark.attended }}
              accessibilityLabel={`${school.name} attended`}
              style={[opsStyles.row, opsStyles.grow]}
            >
              <View
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 6,
                  borderWidth: 1.5,
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderColor: mark.attended ? colors.success : colors.borderStrong,
                  backgroundColor: mark.attended ? colors.success : colors.raised,
                }}
              >
                {mark.attended ? <Check size={14} color="#ffffff" /> : null}
              </View>
              <Text style={[opsStyles.name, { color: colors.text, flex: 1 }]}>{school.name}</Text>
            </Pressable>
            <View style={{ width: 96 }}>
              <Field
                label="People"
                value={mark.participants}
                isNumeric
                onChange={(value) => setMarks({ ...marks, [school.schoolId]: { ...mark, participants: value.replace(/\D/g, '') } })}
              />
            </View>
          </View>
        );
      })}
      <DrawerButton
        label="Save attendance"
        isPrimary
        isBusy={isBusy}
        onPress={() =>
          onSave(
            Object.entries(marks).map(([schoolId, mark]) => ({
              schoolId,
              attended: mark.attended,
              participants: Number(mark.participants || '0'),
            })),
          )
        }
      />
    </OpsCard>
  );
}

interface MinutesCardProps {
  readonly board: GetMobilizationResponse;
  readonly isBusy: boolean;
  readonly onSave: (discussion: string, decisions: string, submit: boolean) => void;
}

function MinutesCard({ board, isBusy, onSave }: MinutesCardProps) {
  const minutes = board.minutes;
  const isSubmitted = minutes?.status === 'submitted';
  const [discussion, setDiscussion] = useState(minutes?.discussion ?? '');
  const [decisions, setDecisions] = useState(minutes?.decisions ?? '');
  return (
    <OpsCard>
      <SectionLabel>Minutes</SectionLabel>
      {isSubmitted ? <Muted>Submitted {minutes?.submittedAt.slice(0, 10)}. Kept as they are.</Muted> : null}
      <Field label="Discussion" value={discussion} onChange={setDiscussion} isMultiline isReadOnly={isSubmitted} />
      <Field label="Decisions" value={decisions} onChange={setDecisions} isMultiline isReadOnly={isSubmitted} />
      {isSubmitted ? null : (
        <View style={{ gap: 8 }}>
          <DrawerButton label="Save draft" isBusy={isBusy} onPress={() => onSave(discussion, decisions, false)} />
          <DrawerButton label="Submit minutes" isPrimary isBusy={isBusy} isDisabled={!discussion.trim()} onPress={() => onSave(discussion, decisions, true)} />
        </View>
      )}
    </OpsCard>
  );
}
