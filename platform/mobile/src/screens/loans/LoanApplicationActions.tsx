/**
 * What staff do on one loan application (brief §5, §7, §10, §11): record a
 * follow-up with the lender, leave an oversight note, link the application
 * to its directory school, send it again, record the lender's decision as
 * an evidence-backed correction, and link the loan the lender registered.
 * Each form posts one RPC and reloads the page; the gateway decides who may.
 */
import { useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { Choice, SchoolOption } from '../../gen/edify/loans/v1/loans_pb';
import { LoanReferralService } from '../../gen/edify/loans/v1/loans_pb';
import { useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { DrawerButton } from '../../ui/drawerParts';
import { Select } from '../../ui/Select';
import { ChoiceRow, Field, Muted, Notice, OpsCard, SectionLabel, opsStyles } from '../cluster/opsParts';
import { parseUGX, todayISO } from './loanRoutes';

const METHOD = LoanReferralService.method;

interface ActionProps {
  readonly applicationId: string;
  readonly onDone: (message: string) => void;
}

/** Runs one action, showing its refusal in place. */
function useAction(onDone: (message: string) => void) {
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const run = (work: Promise<unknown>, message: string) => {
    setIsBusy(true);
    setError('');
    work
      .then(() => onDone(message))
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };
  return { isBusy, error, run, setError };
}

const CHANNELS = [
  { value: 'phone', label: 'Phone' },
  { value: 'email', label: 'Email' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'meeting', label: 'Meeting' },
  { value: 'other', label: 'Other' },
];

export function FollowUpForm({ applicationId, onDone }: ActionProps) {
  const { api } = useSession();
  const { isBusy, error, run } = useAction(onDone);
  const [on, setOn] = useState(todayISO());
  const [channel, setChannel] = useState('phone');
  const [notes, setNotes] = useState('');
  const [feedback, setFeedback] = useState('');
  const [nextAction, setNextAction] = useState('');
  const [nextOn, setNextOn] = useState('');
  const [documentReference, setDocumentReference] = useState('');
  return (
    <OpsCard>
      <SectionLabel>Record a follow-up with the lender</SectionLabel>
      <Muted>A follow-up never changes the application's status: only the lender records its decision.</Muted>
      <DateField label="Day of the follow-up" value={on} onChange={setOn} max={todayISO()} />
      <ChoiceRow label="How" value={channel} choices={CHANNELS} onChange={setChannel} />
      <Field label="What was discussed" value={notes} onChange={setNotes} isMultiline />
      <Field label="Lender's feedback" value={feedback} onChange={setFeedback} isMultiline />
      <Field label="Next action" value={nextAction} onChange={setNextAction} />
      <DateField label="Next follow-up" value={nextOn} onChange={setNextOn} min={todayISO()} placeholder="Not set" />
      <Field label="Supporting document reference (optional)" value={documentReference} onChange={setDocumentReference} />
      <Notice text={error} isError />
      <DrawerButton
        label="Save follow-up"
        isPrimary
        isBusy={isBusy}
        isDisabled={!notes.trim()}
        onPress={() =>
          run(
            api.call(METHOD.recordFollowUp, {
              applicationId, followedUpOn: on, channel, notes, lenderFeedback: feedback, nextAction,
              nextFollowUpOn: nextOn, documentReference,
            }),
            'Follow-up recorded.',
          )
        }
      />
    </OpsCard>
  );
}

export function OversightForm({ applicationId, onDone }: ActionProps) {
  const { api } = useSession();
  const { isBusy, error, run } = useAction(onDone);
  const [notes, setNotes] = useState('');
  const [nextOn, setNextOn] = useState('');
  return (
    <OpsCard>
      <SectionLabel>Oversight note</SectionLabel>
      <Field label="Note" value={notes} onChange={setNotes} isMultiline />
      <DateField label="Ask for a follow-up by" value={nextOn} onChange={setNextOn} min={todayISO()} placeholder="Not set" />
      <Notice text={error} isError />
      <DrawerButton
        label="Save note"
        isPrimary
        isBusy={isBusy}
        isDisabled={!notes.trim()}
        onPress={() => run(api.call(METHOD.recordOversightNote, { applicationId, notes, nextFollowUpOn: nextOn }), 'Note recorded.')}
      />
    </OpsCard>
  );
}

interface MatchProps extends ActionProps {
  readonly candidates: readonly SchoolOption[];
  readonly isMatched: boolean;
}

/** Links the application to its directory school; never creates one. */
export function SchoolMatchForm({ applicationId, candidates, isMatched, onDone }: MatchProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const { isBusy, error, run, setError } = useAction(onDone);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<readonly SchoolOption[]>([]);
  const [note, setNote] = useState('');
  const search = () => {
    setError('');
    api
      .call(METHOD.searchSchools, { query })
      .then((answer) => setFound(answer.schools))
      .catch((cause: unknown) => setError(describe(cause)));
  };
  const choose = (school: SchoolOption) =>
    run(api.call(METHOD.resolveSchoolMatch, { applicationId, schoolId: school.id, note }), `Linked to ${school.name}.`);
  const shown = found.length > 0 ? found : candidates;
  return (
    <OpsCard>
      <SectionLabel>{isMatched ? 'Change the directory school' : 'Find the school in the directory'}</SectionLabel>
      <Muted>Choose only a school you are sure of (confirm its School ID with the director). No directory record is ever created here.</Muted>
      <View style={opsStyles.spread}>
        <TextInput
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={search}
          placeholder="School name or School ID"
          placeholderTextColor={colors.textSubtle}
          accessibilityLabel="Search the School Directory"
          style={[opsStyles.grow, { color: colors.text, borderColor: colors.fieldBorder, borderWidth: 1, borderRadius: 10, padding: 10 }]}
        />
        <DrawerButton label="Search" onPress={search} isDisabled={query.trim().length < 2} />
      </View>
      {shown.length === 0 ? <Muted>No similar school found yet.</Muted> : null}
      {shown.map((school) => (
        <Pressable
          key={school.id}
          onPress={() => choose(school)}
          disabled={isBusy}
          accessibilityRole="button"
          accessibilityLabel={`Link to ${school.name}, School ID ${school.edifySchoolId}`}
          style={[opsStyles.spread, { paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.border }]}
        >
          <View style={opsStyles.grow}>
            <Text style={[opsStyles.name, { color: colors.text, fontSize: 14 }]}>{school.name}</Text>
            <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
              School ID {school.edifySchoolId || '—'}
              {school.district ? ` · ${school.district}` : ''}
            </Text>
          </View>
          <Text style={[opsStyles.meta, { color: colors.link }]}>This is the school</Text>
        </Pressable>
      ))}
      <Field label="Note (how you confirmed it)" value={note} onChange={setNote} />
      <Notice text={error} isError />
      {!isMatched ? (
        <DrawerButton
          label="Not in the directory yet"
          isBusy={isBusy}
          onPress={() => run(api.call(METHOD.resolveSchoolMatch, { applicationId, notInDirectory: true, note }), 'Recorded as not in the directory.')}
        />
      ) : null}
    </OpsCard>
  );
}

interface CorrectionProps extends ActionProps {
  readonly actions: readonly Choice[];
}

/** Records what the lender decided, with its evidence; or withdraws or closes. */
export function CorrectionForm({ applicationId, actions, onDone }: CorrectionProps) {
  const { api } = useSession();
  const { isBusy, error, run, setError } = useAction(onDone);
  const [action, setAction] = useState('');
  const [note, setNote] = useState('');
  const [evidence, setEvidence] = useState('');
  const [approved, setApproved] = useState('');
  const [disbursed, setDisbursed] = useState('');
  const [disbursedOn, setDisbursedOn] = useState('');
  const [reference, setReference] = useState('');
  if (actions.length === 0) {
    return null;
  }
  const isPlain = action === 'withdraw' || action === 'close';
  const save = () => {
    const approvedUgx = approved ? parseUGX(approved) : BigInt(0);
    const disbursedUgx = disbursed ? parseUGX(disbursed) : BigInt(0);
    if (approvedUgx === null || disbursedUgx === null) {
      setError('Write amounts in whole shillings, such as 38,500,000.');
      return;
    }
    run(
      api.call(METHOD.recordCorrection, {
        applicationId, action, note, evidence, approvedUgx, disbursedUgx, disbursementDate: disbursedOn,
        disbursementReference: reference,
      }),
      'Recorded.',
    );
  };
  return (
    <OpsCard>
      <SectionLabel>Record for the lender, or withdraw</SectionLabel>
      <Muted>Use this only when the lender cannot record it themselves, and name their evidence. Withdraw only at the school's request.</Muted>
      <Select label="What happened" value={action} choices={actions.map((choice) => ({ value: choice.value, label: choice.label }))} placeholder="Choose" onChange={setAction} variant="form" />
      {action === 'approve' ? <Field label="Approved amount (UGX)" value={approved} onChange={setApproved} isNumeric /> : null}
      {action === 'disburse' ? (
        <>
          <Field label="Amount actually disbursed (UGX)" value={disbursed} onChange={setDisbursed} isNumeric />
          <DateField label="Disbursement date" value={disbursedOn} onChange={setDisbursedOn} max={todayISO()} />
          <Field label="Loan or transaction reference" value={reference} onChange={setReference} />
        </>
      ) : null}
      {action && !isPlain ? <Field label="The lender's evidence" value={evidence} onChange={setEvidence} placeholder="e.g. lender's email of 12 Nov" /> : null}
      {action ? <Field label={isPlain ? 'Why' : 'Why staff are recording it'} value={note} onChange={setNote} isMultiline /> : null}
      <Notice text={error} isError />
      {action ? <DrawerButton label="Record" isPrimary isBusy={isBusy} isDisabled={!note.trim()} onPress={save} /> : null}
    </OpsCard>
  );
}

export function ResendButton({ applicationId, onDone }: ActionProps) {
  const { api } = useSession();
  const { isBusy, error, run } = useAction(onDone);
  return (
    <>
      <DrawerButton
        label="Send to the lender again"
        isBusy={isBusy}
        onPress={() => run(api.call(METHOD.resendToLender, { applicationId, note: '' }), 'Queued to be sent again.')}
      />
      <Notice text={error} isError />
    </>
  );
}

export function LinkLoanForm({ applicationId, onDone }: ActionProps) {
  const { api } = useSession();
  const { isBusy, error, run } = useAction(onDone);
  const [loanId, setLoanId] = useState('');
  return (
    <OpsCard>
      <SectionLabel>Link the loan the lender registered</SectionLabel>
      <Muted>The loan ledger stays the record of the loan; linking keeps it from being counted twice.</Muted>
      <Field label="Registered loan id" value={loanId} onChange={setLoanId} />
      <Notice text={error} isError />
      <DrawerButton
        label="Link"
        isBusy={isBusy}
        isDisabled={!loanId.trim()}
        onPress={() => run(api.call(METHOD.linkRegisteredLoan, { applicationId, mfiLoanId: loanId }), 'Linked.')}
      />
    </OpsCard>
  );
}
