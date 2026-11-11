/**
 * The Loan Partners of the Partner Directory and how each receives school
 * loan referrals (brief §4, §7). The public form offers a lender only when
 * it is active, under a data-sharing agreement, switched on, and has a
 * receiving address it confirmed itself. The Country Director manages the
 * addresses and the switch; other staff see why a lender is not offered.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, Switch, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { LenderChannel, ListLenderChannelsResponse } from '../../gen/edify/loans/v1/loans_pb';
import { LoanReferralService } from '../../gen/edify/loans/v1/loans_pb';
import { useTheme } from '../../theme';
import { DrawerButton } from '../../ui/drawerParts';
import { Field, Muted, Notice, OpsCard, OpsTitle, opsStyles } from '../cluster/opsParts';
import { StatusPill } from './loanParts';

const METHOD = LoanReferralService.method;

export function LenderChannelsScreen() {
  const { api } = useSession();
  const { colors } = useTheme();
  const [answer, setAnswer] = useState<ListLenderChannelsResponse | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    api
      .call(METHOD.listLenderChannels, {})
      .then(setAnswer)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api]);
  useEffect(load, [load]);
  return (
    <ScrollView contentContainerStyle={opsStyles.page} keyboardShouldPersistTaps="handled">
      <OpsTitle
        eyebrow="School loans"
        title="Lending partners"
        copy="Loan Partners from the Partner Directory, and whether schools can choose them on the application form."
      />
      <Notice text={error} isError />
      {!answer && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
      {answer && answer.channels.length === 0 ? (
        <Muted>No Loan Partner is in the Partner Directory yet. Save a partner as a Loan Partner there first.</Muted>
      ) : null}
      {answer?.channels.map((channel) => (
        <ChannelCard key={channel.partnerId} channel={channel} canManage={answer.canManage} onSaved={load} />
      ))}
    </ScrollView>
  );
}

function ChannelCard({ channel, canManage, onSaved }: { readonly channel: LenderChannel; readonly canManage: boolean; readonly onSaved: () => void }) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [isEditing, setIsEditing] = useState(false);
  const [email, setEmail] = useState(channel.deliveryEmail);
  const [description, setDescription] = useState(channel.description);
  const [isEnabled, setIsEnabled] = useState(channel.referralsEnabled);
  const [isBusy, setIsBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const run = (work: Promise<{ message: string }>) => {
    setIsBusy(true);
    setError('');
    work
      .then((answer) => {
        setNotice(answer.message);
        setIsEditing(false);
        onSaved();
      })
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  return (
    <OpsCard>
      <View style={opsStyles.spread}>
        <Text style={[opsStyles.name, { color: colors.text, flex: 1 }]}>{channel.lenderName}</Text>
        <StatusPill status={channel.eligible ? 'approved' : 'information_requested'} label={channel.eligible ? 'Offered to schools' : 'Not offered'} />
      </View>
      <Text style={[opsStyles.meta, { color: colors.textMuted }]}>
        {channel.deliveryEmail ? `Receives at ${channel.deliveryEmail}` : 'No receiving address'}
        {channel.addressConfirmed ? ' (confirmed)' : channel.deliveryEmail ? ' (not confirmed yet)' : ''}
        {channel.portalUsers > 0 ? ` · ${channel.portalUsers} staff sign in to Edify` : ''}
      </Text>
      {channel.description ? <Muted>{channel.description}</Muted> : null}
      {channel.problems.map((problem) => (
        <Text key={problem} style={[opsStyles.meta, { color: colors.warning }]}>
          • {problem}
        </Text>
      ))}
      <Notice text={notice} />
      <Notice text={error} isError />
      {canManage && !isEditing ? (
        <View style={opsStyles.actions}>
          <DrawerButton label="Edit" onPress={() => setIsEditing(true)} />
          {channel.deliveryEmail && !channel.addressConfirmed ? (
            <DrawerButton
              label="Send confirmation again"
              isBusy={isBusy}
              onPress={() => run(api.call(METHOD.sendChannelConfirmation, { partnerId: channel.partnerId }))}
            />
          ) : null}
        </View>
      ) : null}
      {canManage && isEditing ? (
        <>
          <Field label="Receiving address" value={email} onChange={setEmail} placeholder="loans@lender.org" />
          <Muted>A new address is emailed a confirmation link; referrals go there only after the lender confirms it.</Muted>
          <Field label="Description schools see (optional)" value={description} onChange={setDescription} isMultiline />
          <View style={opsStyles.spread}>
            <Text style={[opsStyles.meta, { color: colors.text, fontSize: 14 }]}>Receive referrals</Text>
            <Switch value={isEnabled} onValueChange={setIsEnabled} accessibilityLabel="Receive referrals" />
          </View>
          <View style={opsStyles.actions}>
            <DrawerButton
              label="Save"
              isPrimary
              isBusy={isBusy}
              onPress={() =>
                run(
                  api
                    .call(METHOD.saveLenderChannel, {
                      partnerId: channel.partnerId, referralsEnabled: isEnabled, deliveryEmail: email, description,
                    })
                    .then((answer) => ({ message: answer.message })),
                )
              }
            />
            <DrawerButton label="Cancel" onPress={() => setIsEditing(false)} />
          </View>
        </>
      ) : null}
    </OpsCard>
  );
}
