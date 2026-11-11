/**
 * One school loan's progress for Edify staff and lenders: the stages from
 * submission to collateral release (only recorded facts mark a stage done),
 * the follow-ups and notifications, and the two one-tap actions — Send
 * Notification (approved texts, the shared cooldown) and Record Follow-up
 * (a payment the school reports waits for the lender's verification).
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { CalendarCheck, Check, Circle, Clock, MessageSquare } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetLoanProgressResponse, PrepareNotificationResponse, ProgressStage } from '../../gen/edify/loans/v1/follow_up_pb';
import { LoanFollowUpService } from '../../gen/edify/loans/v1/follow_up_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { Select } from '../../ui/Select';
import { parseUGX } from './loanRoutes';
import { LoanHero, LoanSheet, PrimaryButton, StatusChip } from './loanUi';
import type { ProgressPanel } from './StaffLoansScreen';

interface LoanProgressScreenProps {
  readonly applicationId: string;
  readonly initialPanel: ProgressPanel;
  readonly onBack: () => void;
}

function today(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function LoanProgressScreen({ applicationId, initialPanel, onBack }: LoanProgressScreenProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [progress, setProgress] = useState<GetLoanProgressResponse | null>(null);
  const [panel, setPanel] = useState<ProgressPanel>(initialPanel);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(() => {
    api
      .call(LoanFollowUpService.method.getLoanProgress, { applicationId })
      .then(setProgress)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, applicationId]);
  useEffect(load, [load]);

  const done = (message: string) => {
    setPanel('');
    setNotice(message);
    load();
  };
  const row = progress?.row;

  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <LoanHero eyebrow={row?.reference} title={row?.schoolName ?? 'Loan progress'} subtitle={row?.lenderName} onBack={onBack} />
      <LoanSheet>
        {error ? (
          <Text style={[styles.note, { color: colors.danger }]} accessibilityRole="alert">
            {error}
          </Text>
        ) : null}
        {notice ? (
          <Text style={[styles.note, { color: colors.success }]} accessibilityLiveRegion="polite">
            {notice}
          </Text>
        ) : null}
        {!progress && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
        {row ? (
          <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
            <View style={styles.chips}>
              <StatusChip label={row.statusLabel} tone={row.statusTone} />
              <StatusChip label={row.disbursementLabel} tone="plain" />
              {row.followUpLabel && row.followUpLabel !== '—' ? <StatusChip label={row.followUpLabel} tone={row.followUpTone} /> : null}
            </View>
            {progress?.facts.map((fact) => (
              <Fact key={fact.label} label={fact.label} value={fact.value} />
            ))}
            <Fact label="Next payment" value={row.nextPaymentOn} />
            <Fact label="Responsible staff" value={row.responsibleStaff} />
            <Fact label="Loan officer" value={progress?.assignedOfficer ?? ''} />
            <Fact label="Lender contact" value={progress?.lenderContact ?? ''} />
            <Fact label="Next follow-up" value={row.nextFollowUpOn} />
          </View>
        ) : null}
        {row ? (
          <View style={styles.actions}>
            <View style={styles.action}>
              <PrimaryButton label="Send Notification" icon={MessageSquare} onPress={() => setPanel(panel === 'notify' ? '' : 'notify')} isDisabled={!row.canNotify} />
            </View>
            <View style={styles.action}>
              <PrimaryButton label="Record Follow-up" icon={CalendarCheck} isOutline onPress={() => setPanel(panel === 'follow_up' ? '' : 'follow_up')} isDisabled={!row.canFollowUp} />
            </View>
          </View>
        ) : null}
        {row?.notifyNote ? <Text style={[styles.note, { color: colors.textMuted }]}>{row.notifyNote}</Text> : null}
        {panel === 'notify' ? <NotifyPanel applicationId={applicationId} onSent={done} onCancel={() => setPanel('')} /> : null}
        {panel === 'follow_up' ? <FollowUpPanel applicationId={applicationId} onSaved={done} onCancel={() => setPanel('')} /> : null}

        {progress ? (
          <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
            <Text style={[styles.heading, { color: colors.text }]} accessibilityRole="header">
              Application progress
            </Text>
            {progress.stages.map((stage, index) => (
              <StageRow key={stage.key} stage={stage} isLast={index === progress.stages.length - 1} />
            ))}
          </View>
        ) : null}

        {progress?.followUps.length ? (
          <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
            <Text style={[styles.heading, { color: colors.text }]} accessibilityRole="header">
              Follow-ups
            </Text>
            {progress.followUps.map((entry) => (
              <View key={entry.id} style={[styles.entry, { borderTopColor: colors.border }]}>
                <Text style={[styles.entryTitle, { color: colors.text }]}>
                  {[entry.followedUpOn, entry.reason, entry.method].filter((part) => part && part !== '—').join(' · ')}
                </Text>
                <Text style={[styles.note, { color: colors.textMuted }]}>{entry.summary}</Text>
                {entry.paymentNote ? <StatusChip label={entry.paymentNote} tone="caution" /> : null}
                <Text style={[styles.note, { color: colors.textSubtle }]}>
                  {entry.staffName}
                  {entry.nextFollowUpOn ? ` · next ${entry.nextFollowUpOn}` : ''}
                </Text>
              </View>
            ))}
          </View>
        ) : null}

        {progress?.notifications.length ? (
          <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
            <Text style={[styles.heading, { color: colors.text }]} accessibilityRole="header">
              Notifications to the school
            </Text>
            {progress.notifications.map((entry) => (
              <View key={entry.id} style={[styles.entry, { borderTopColor: colors.border }]}>
                <View style={styles.entryHead}>
                  <Text style={[styles.entryTitle, { color: colors.text }]}>{entry.typeLabel}</Text>
                  <StatusChip label={entry.statusLabel} tone={entry.statusTone} />
                </View>
                <Text style={[styles.note, { color: colors.textSubtle }]}>
                  {entry.createdAt} · {entry.sentBy} ({entry.sendingOrganisation}) · {entry.recipient}
                </Text>
                {entry.failure ? <Text style={[styles.note, { color: colors.danger }]}>{entry.failure}</Text> : null}
              </View>
            ))}
          </View>
        ) : null}
      </LoanSheet>
    </ScrollView>
  );
}

function Fact({ label, value }: { readonly label: string; readonly value: string }) {
  const { colors } = useTheme();
  if (!value) {
    return null;
  }
  return (
    <View style={[styles.fact, { borderTopColor: colors.border }]}>
      <Text style={[styles.factLabel, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.factValue, { color: colors.text }]} selectable>
        {value}
      </Text>
    </View>
  );
}

const STAGE_LOOK = {
  done: { tone: 'good', icon: Check },
  current: { tone: 'brand', icon: Circle },
  waiting: { tone: 'caution', icon: Clock },
  not_reached: { tone: 'plain', icon: Circle },
} as const;

function StageRow({ stage, isLast }: { readonly stage: ProgressStage; readonly isLast: boolean }) {
  const { colors } = useTheme();
  const look = STAGE_LOOK[stage.state as keyof typeof STAGE_LOOK] ?? STAGE_LOOK.not_reached;
  const tone = toneColors(colors, look.tone);
  const Icon = look.icon;
  const detail = [stage.updatedOn, stage.note, stage.nextAction].filter(Boolean).join(' · ');
  return (
    <View style={styles.stage} accessible accessibilityLabel={`${stage.label}: ${stage.state.replace('_', ' ')}. ${detail}`}>
      <View style={styles.rail}>
        <View style={[styles.dot, { backgroundColor: tone.soft, borderColor: tone.fg }]}>
          <Icon size={12} color={tone.fg} />
        </View>
        {isLast ? null : <View style={[styles.line, { backgroundColor: colors.border }]} />}
      </View>
      <View style={styles.stageBody}>
        <Text style={[styles.entryTitle, { color: stage.state === 'not_reached' ? colors.textSubtle : colors.text }]}>{stage.label}</Text>
        {detail ? <Text style={[styles.note, { color: colors.textMuted }]}>{detail}</Text> : null}
        <Text style={[styles.note, { color: colors.textSubtle }]}>{stage.responsible}</Text>
      </View>
    </View>
  );
}

interface NotifyPanelProps {
  readonly applicationId: string;
  readonly onSent: (message: string) => void;
  readonly onCancel: () => void;
}

/** The Send Notification dialog, drawn in the page (no modal). */
function NotifyPanel({ applicationId, onSent, onCancel }: NotifyPanelProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [prepared, setPrepared] = useState<PrepareNotificationResponse | null>(null);
  const [type, setType] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    api
      .call(LoanFollowUpService.method.prepareNotification, { applicationId })
      .then((answer) => {
        setPrepared(answer);
        setType(answer.options.find((option) => !option.inCooldown)?.type ?? answer.options[0]?.type ?? '');
      })
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, applicationId]);

  const chosen = prepared?.options.find((option) => option.type === type);
  const send = () => {
    setIsBusy(true);
    setError('');
    api
      .call(LoanFollowUpService.method.sendNotification, { applicationId, type, exceptionReason: chosen?.inCooldown ? reason : '' })
      .then((answer) => onSent(answer.message))
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };
  const blocked = !chosen || (chosen.inCooldown && (!chosen.canOverride || !reason.trim()));

  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.primary }]}>
      <Text style={[styles.heading, { color: colors.text }]} accessibilityRole="header">
        Send Notification
      </Text>
      {!prepared && !error ? <ActivityIndicator color={colors.primary} /> : null}
      {prepared ? (
        <>
          <Fact label="School" value={prepared.schoolName} />
          <Fact label="Recipient" value={`${prepared.recipientName} · ${prepared.recipientPhone}${prepared.recipientVerified ? '' : ' (not yet confirmed by code)'}`} />
          <Fact label="Loan reference" value={prepared.reference} />
          <Fact label="Last notification" value={prepared.lastNotification} />
          {prepared.options.length === 0 ? (
            <Text style={[styles.note, { color: colors.textMuted }]}>No notification fits this loan's present state for your role.</Text>
          ) : (
            <Select
              label="Notification type"
              value={type}
              placeholder="Choose a notification"
              hasEmptyChoice={false}
              choices={prepared.options.map((option) => ({ value: option.type, label: option.inCooldown ? `${option.label} (sent recently)` : option.label }))}
              onChange={setType}
            />
          )}
          {chosen ? (
            <View style={[styles.preview, { backgroundColor: colors.surface, borderColor: colors.fieldBorder }]}>
              <Text style={[styles.note, { color: colors.text }]}>{chosen.preview}</Text>
              <Text style={[styles.note, { color: colors.textSubtle }]}>
                {chosen.smsParts > 1 ? `Sent as ${chosen.smsParts} text messages.` : 'One text message.'}
              </Text>
            </View>
          ) : null}
          {chosen?.inCooldown ? (
            <View style={styles.gap}>
              <Text style={[styles.note, { color: colors.warning }]}>{chosen.cooldownNote}</Text>
              {chosen.canOverride ? (
                <TextInput
                  value={reason}
                  onChangeText={setReason}
                  placeholder="Why it must go now (for the record)"
                  placeholderTextColor={colors.textSubtle}
                  accessibilityLabel="Reason to send inside the cooldown"
                  multiline
                  style={[styles.input, { color: colors.text, borderColor: colors.fieldBorder, backgroundColor: colors.surface }]}
                />
              ) : null}
            </View>
          ) : null}
          <Text style={[styles.note, { color: colors.textSubtle }]}>{prepared.note}</Text>
        </>
      ) : null}
      {error ? (
        <Text style={[styles.note, { color: colors.danger }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
      <View style={styles.actions}>
        <View style={styles.action}>
          <PrimaryButton label={isBusy ? 'Sending…' : 'Send Notification'} icon={MessageSquare} onPress={send} isDisabled={blocked || isBusy} />
        </View>
        <View style={styles.action}>
          <PrimaryButton label="Cancel" isOutline onPress={onCancel} />
        </View>
      </View>
    </View>
  );
}

const METHODS = [
  { value: 'phone', label: 'Phone call' },
  { value: 'visit', label: 'School visit' },
  { value: 'sms', label: 'SMS' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'email', label: 'Email' },
  { value: 'meeting', label: 'Meeting' },
  { value: 'other', label: 'Other' },
];

const REASONS = [
  { value: 'not_acknowledged', label: 'Application not acknowledged' },
  { value: 'assessment_delayed', label: 'Assessment delayed' },
  { value: 'documents_required', label: 'Additional documents required' },
  { value: 'decision_pending', label: 'Loan decision pending' },
  { value: 'disbursement_delayed', label: 'Disbursement delayed' },
  { value: 'installment_approaching', label: 'Installment approaching' },
  { value: 'repayment_overdue', label: 'Repayment overdue' },
  { value: 'payment_discrepancy', label: 'Payment discrepancy' },
  { value: 'collateral_delayed', label: 'Collateral release delayed' },
  { value: 'other', label: 'Other' },
];

interface FollowUpPanelProps {
  readonly applicationId: string;
  readonly onSaved: (message: string) => void;
  readonly onCancel: () => void;
}

/** Record Follow-up: what was done, said and agreed, and what comes next. */
function FollowUpPanel({ applicationId, onSaved, onCancel }: FollowUpPanelProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [form, setForm] = useState({ on: today(), method: 'phone', reason: '', person: '', summary: '', feedback: '', next: '', nextOn: '' });
  const [isPaid, setIsPaid] = useState(false);
  const [amount, setAmount] = useState('');
  const [paidOn, setPaidOn] = useState('');
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const set = (key: keyof typeof form) => (value: string) => setForm((current) => ({ ...current, [key]: value }));

  const save = () => {
    const parsed = isPaid && amount.trim() ? parseUGX(amount) : 0n;
    if (parsed === null) {
      setError('Write the amount like 1,500,000.');
      return;
    }
    setIsBusy(true);
    setError('');
    api
      .call(LoanFollowUpService.method.recordStaffFollowUp, {
        applicationId, followedUpOn: form.on, method: form.method, reason: form.reason, contactedPerson: form.person,
        summary: form.summary, schoolFeedback: form.feedback, nextAction: form.next, nextFollowUpOn: form.nextOn,
        paymentReported: isPaid, reportedAmountUgx: parsed ?? 0n, reportedPaidOn: isPaid ? paidOn : '',
      })
      .then(() => onSaved(isPaid ? 'Follow-up saved. The reported payment awaits the lender’s verification; the balance is unchanged.' : 'Follow-up saved.'))
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  const field = (label: string, key: keyof typeof form, isMultiline = false) => (
    <TextInput
      value={form[key]}
      onChangeText={set(key)}
      placeholder={label}
      placeholderTextColor={colors.textSubtle}
      accessibilityLabel={label}
      multiline={isMultiline}
      style={[styles.input, isMultiline && styles.multiline, { color: colors.text, borderColor: colors.fieldBorder, backgroundColor: colors.surface }]}
    />
  );

  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.primary }]}>
      <Text style={[styles.heading, { color: colors.text }]} accessibilityRole="header">
        Record Follow-up
      </Text>
      <DateField label="Follow-up date" value={form.on} onChange={set('on')} max={today()} isRequired />
      <Select label="Method" value={form.method} placeholder="How" hasEmptyChoice={false} choices={METHODS} onChange={set('method')} />
      <Select label="Reason" value={form.reason} placeholder="Choose a reason" choices={REASONS} onChange={set('reason')} />
      {field('Person contacted', 'person')}
      {field('Discussion summary', 'summary', true)}
      {field('School feedback', 'feedback', true)}
      {field('Next action', 'next')}
      <DateField label="Next follow-up" value={form.nextOn} onChange={set('nextOn')} min={today()} />
      <View style={styles.switchRow}>
        <View style={styles.flex}>
          <Text style={[styles.entryTitle, { color: colors.text }]}>The school says it has paid</Text>
          <Text style={[styles.note, { color: colors.textMuted }]}>Recorded for the lender to verify. The balance does not change.</Text>
        </View>
        <Switch value={isPaid} onValueChange={setIsPaid} accessibilityLabel="The school says it has paid" />
      </View>
      {isPaid ? (
        <>
          <TextInput
            value={amount}
            onChangeText={setAmount}
            placeholder="Amount the school reports (UGX)"
            placeholderTextColor={colors.textSubtle}
            accessibilityLabel="Amount the school reports"
            keyboardType="number-pad"
            style={[styles.input, { color: colors.text, borderColor: colors.fieldBorder, backgroundColor: colors.surface }]}
          />
          <DateField label="Paid on (as reported)" value={paidOn} onChange={setPaidOn} max={today()} />
        </>
      ) : null}
      {error ? (
        <Text style={[styles.note, { color: colors.danger }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
      <View style={styles.actions}>
        <View style={styles.action}>
          <PrimaryButton label={isBusy ? 'Saving…' : 'Save Follow-up'} icon={CalendarCheck} onPress={save} isDisabled={isBusy || !form.reason || !form.summary.trim()} />
        </View>
        <View style={styles.action}>
          <PrimaryButton label="Cancel" isOutline onPress={onCancel} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 8 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  heading: { fontFamily: fonts.bold, fontSize: 16 },
  note: { fontFamily: fonts.medium, fontSize: 12.5, lineHeight: 18 },
  fact: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, paddingTop: 8, borderTopWidth: StyleSheet.hairlineWidth },
  factLabel: { fontFamily: fonts.medium, fontSize: 13, maxWidth: '42%' },
  factValue: { fontFamily: fonts.semibold, fontSize: 13, flex: 1, textAlign: 'right' },
  actions: { flexDirection: 'row', gap: 10, flexWrap: 'wrap' },
  action: { flexGrow: 1, flexBasis: '45%' },
  stage: { flexDirection: 'row', gap: 10 },
  rail: { alignItems: 'center', width: 24 },
  dot: { width: 24, height: 24, borderRadius: 12, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  line: { width: 2, flex: 1, minHeight: 14, marginVertical: 2 },
  stageBody: { flex: 1, gap: 2, paddingBottom: 10 },
  entry: { gap: 3, paddingTop: 8, borderTopWidth: StyleSheet.hairlineWidth },
  entryHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  entryTitle: { fontFamily: fonts.semibold, fontSize: 14, flexShrink: 1 },
  preview: { borderWidth: 1, borderRadius: radius.sm, padding: 10, gap: 4 },
  gap: { gap: 6 },
  input: { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10, fontFamily: fonts.medium, fontSize: 15, minHeight: 44 },
  multiline: { minHeight: 80, textAlignVertical: 'top' },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  flex: { flex: 1, gap: 2 },
});
