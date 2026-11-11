/**
 * The Acting Leadership drawers (the web's appoint, reschedule and cancel
 * drawers, apps.acting): appoint in two steps — choose the person and the
 * month, then read what the appointment gives and confirm — move one that
 * has not begun, or cancel one. The gateway checks every part again on save.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ActingAppointment, GetAppointOptionsResponse, PreviewAppointmentResponse } from '../../gen/edify/identity/v1/acting_pb';
import { ActingLeadershipService } from '../../gen/edify/identity/v1/acting_pb';
import { fonts, useTheme } from '../../theme';
import { DrawerInput, DrawerNote, DrawerText, FieldShell } from '../../ui/drawerParts';
import { Select } from '../../ui/Select';
import { SubmitDrawer, useSubmit } from '../../ui/SubmitDrawer';
import { cancelConsequence } from './actingData';

interface Base {
  readonly onClose: () => void;
  readonly onSaved: (message: string) => void;
}

/** Who may be appointed and the twelve months, read when a drawer opens. */
function useOptions(): { options: GetAppointOptionsResponse | null; error: string } {
  const { api } = useSession();
  const [options, setOptions] = useState<GetAppointOptionsResponse | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let isLive = true;
    api
      .call(ActingLeadershipService.method.getAppointOptions, {})
      .then((answer) => isLive && setOptions(answer))
      .catch((cause: unknown) => isLive && setError(describe(cause)));
    return () => {
      isLive = false;
    };
  }, [api]);
  return { options, error };
}

function Line({ term, value }: { readonly term: string; readonly value: string }) {
  const { colors } = useTheme();
  return (
    <View style={styles.line}>
      <Text style={[styles.term, { color: colors.textMuted }]}>{term}</Text>
      <Text style={[styles.value, { color: colors.text }]}>{value}</Text>
    </View>
  );
}

/** Appoint Acting PL / Appoint Acting CD. */
export function AppointDrawer({ shortLabel, onClose, onSaved }: Base & { readonly shortLabel: string }) {
  const { api } = useSession();
  const { options, error: loadError } = useOptions();
  const [person, setPerson] = useState('');
  const [month, setMonth] = useState('');
  const [preview, setPreview] = useState<PreviewAppointmentResponse | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const submit = useSubmit(onSaved);
  const chosenMonth = options?.months.find((m) => m.value === month) ?? options?.months[0];
  const isTeam = options?.appointeeRole === 'CCEO';
  const scope = isTeam ? 'My PL Team' : 'Country';

  if (preview) {
    return (
      <SubmitDrawer
        title={`Appoint ${shortLabel}`}
        label="Confirm Appointment"
        cancelLabel="Back"
        onSecondary={() => setPreview(null)}
        {...submit}
        onClose={onClose}
        onSubmit={() =>
          void submit.run(async () => {
            const made = await api.call(ActingLeadershipService.method.appoint, {
              appointeeStaffId: person, month: chosenMonth?.value ?? '',
            });
            const a = made.appointment;
            return `${a?.appointeeName ?? preview.appointeeName} is ${a?.label ?? preview.label} for ${a?.monthLabel ?? preview.monthLabel}.`;
          })
        }
      >
        <View style={styles.summary}>
          <Line term={options?.appointeeRole ?? ''} value={preview.appointeeName} />
          <Line term="Acting role" value={preview.label} />
          <Line term="Acting month" value={preview.monthLabel} />
          <Line term="Scope" value={scope} />
          <Line term="Effective" value={preview.effectiveLabel} />
        </View>
        <DrawerNote tone="info" text={preview.statement} />
        <DrawerText text="Money and leave approvals, performance reviews, targets, accounts and further acting appointments are not part of an appointment. They stay with you." />
      </SubmitDrawer>
    );
  }

  // The review step, validated as the appointment itself will be.
  async function review() {
    setIsChecking(true);
    submit.setError('');
    try {
      setPreview(
        await api.call(ActingLeadershipService.method.previewAppointment, {
          appointeeStaffId: person, month: chosenMonth?.value ?? '',
        }),
      );
    } catch (cause) {
      submit.setError(describe(cause));
    } finally {
      setIsChecking(false);
    }
  }

  const candidates = options?.candidates ?? [];
  return (
    <SubmitDrawer
      title={`Appoint ${shortLabel}`}
      subtitle="Appoint an acting leader"
      label={`Appoint ${shortLabel}`}
      isDisabled={!options || candidates.length === 0}
      {...submit}
      isBusy={isChecking}
      error={submit.error || loadError}
      onClose={onClose}
      onSubmit={() => void review()}
    >
      {!options ? (
        loadError ? null : <ActivityIndicator />
      ) : candidates.length === 0 ? (
        <DrawerNote
          tone="warning"
          text={isTeam ? 'No CCEO is recorded under you yet, so there is nobody to appoint.' : 'No Program Lead is recorded in your country yet, so there is nobody to appoint.'}
        />
      ) : (
        <>
          <FieldShell
            label={options.appointeeRole}
            isRequired
            help={isTeam ? 'The CCEOs who report to you.' : 'The Program Leads of your country.'}
          >
            <Select
              label={options.appointeeRole}
              value={person}
              placeholder={`Choose a ${options.appointeeRole}`}
              choices={candidates.map((c) => ({ value: c.staffProfileId, label: c.name }))}
              onChange={setPerson}
            />
          </FieldShell>
          <FieldShell label="Acting Month" isRequired>
            <Select
              label="Acting Month"
              value={chosenMonth?.value ?? ''}
              placeholder="Choose a month"
              hasEmptyChoice={false}
              choices={options.months.map((m) => ({ value: m.value, label: m.label }))}
              onChange={setMonth}
            />
          </FieldShell>
          <View style={styles.summary}>
            <Line term="Scope" value={scope} />
            <Line term="Effective" value={chosenMonth?.effectiveLabel ?? ''} />
          </View>
        </>
      )}
    </SubmitDrawer>
  );
}

/** Change acting month: only the appointing leader, before it begins. */
export function ChangeMonthDrawer({ appointment, onClose, onSaved }: Base & { readonly appointment: ActingAppointment }) {
  const { api } = useSession();
  const { options, error: loadError } = useOptions();
  const [month, setMonth] = useState(appointment.month);
  const submit = useSubmit(onSaved);
  const chosen = options?.months.find((m) => m.value === month);
  return (
    <SubmitDrawer
      title="Change acting month"
      subtitle={`${appointment.appointeeName} · ${appointment.shortLabel}`}
      label="Save month"
      isDisabled={!options}
      {...submit}
      error={submit.error || loadError}
      onClose={onClose}
      onSubmit={() =>
        void submit.run(async () => {
          const moved = await api.call(ActingLeadershipService.method.changeMonth, { appointmentId: appointment.id, month });
          return `${appointment.appointeeName} is now ${appointment.shortLabel} for ${moved.appointment?.monthLabel ?? month}.`;
        })
      }
    >
      {!options ? (
        loadError ? null : <ActivityIndicator />
      ) : (
        <FieldShell label="Acting Month" isRequired help={chosen ? `Effective ${chosen.effectiveLabel}.` : undefined}>
          <Select
            label="Acting Month"
            value={month}
            placeholder="Choose a month"
            hasEmptyChoice={false}
            choices={options.months.map((m) => ({ value: m.value, label: m.label }))}
            onChange={setMonth}
          />
        </FieldShell>
      )}
      <DrawerText text="The month this appointment was first made for stays on its record." />
    </SubmitDrawer>
  );
}

/** Cancel acting appointment: access ends at once; the record is kept. */
export function CancelAppointmentDrawer({ appointment, onClose, onSaved }: Base & { readonly appointment: ActingAppointment }) {
  const { api } = useSession();
  const [reason, setReason] = useState('');
  const submit = useSubmit(onSaved);
  return (
    <SubmitDrawer
      title="Cancel acting appointment"
      subtitle={`${appointment.appointeeName} · ${appointment.shortLabel} · ${appointment.monthLabel}`}
      label="Cancel appointment"
      cancelLabel="Keep appointment"
      {...submit}
      onClose={onClose}
      onSubmit={() =>
        void submit.run(async () => {
          await api.call(ActingLeadershipService.method.cancelAppointment, { appointmentId: appointment.id, reason });
          return `${appointment.appointeeName}'s ${appointment.shortLabel} appointment for ${appointment.monthLabel} was cancelled.`;
        })
      }
    >
      <FieldShell label="Reason" isOptional help="Kept on the record with your name and the time.">
        <DrawerInput value={reason} onChangeText={setReason} accessibilityLabel="Reason" multiline maxLength={500} />
      </FieldShell>
      <DrawerNote tone="warning" text={cancelConsequence(appointment)} />
    </SubmitDrawer>
  );
}

const styles = StyleSheet.create({
  summary: { gap: 6 },
  line: { flexDirection: 'row', gap: 12 },
  term: { fontFamily: fonts.medium, fontSize: 13, width: 112 },
  value: { fontFamily: fonts.semibold, fontSize: 13, flex: 1 },
});
