/**
 * Onboard a new Cluster Leader for a cluster (owner, 2026-11-11: "add cluster
 * leader user category so the staff can onboard them"). The account holds the
 * Cluster Leader role alone and starts with an invitation; the leader then
 * leads this cluster. When email cannot reach the leader the gateway hands
 * back the set-password link for the person onboarding them to pass on.
 */
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { UserPlus } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import { ClusterLeadershipService } from '../../gen/edify/clusters/v1/leadership_pb';
import { fonts, radius, useTheme } from '../../theme';
import { PrimaryButton } from '../loans/loanUi';
import { Field } from './opsParts';
import { SendLinkOptions } from './SendLinkOptions';

interface OnboardLeaderFormProps {
  readonly clusterId: string;
  readonly clusterName: string;
  readonly onDone: (message: string) => void;
  readonly onError: (message: string) => void;
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function OnboardLeaderForm({ clusterId, clusterName, onDone, onError }: OnboardLeaderFormProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [reason, setReason] = useState('');
  const [link, setLink] = useState('');
  // Who the link is for, kept once the form clears so it can be addressed to them.
  const [invitee, setInvitee] = useState({ name: '', email: '', phone: '' });
  const [isBusy, setIsBusy] = useState(false);

  if (!isOpen) {
    return <PrimaryButton label="Onboard a new Cluster Leader" icon={UserPlus} isOutline onPress={() => setIsOpen(true)} />;
  }
  const problem = !name.trim() ? 'Enter the leader’s name.' : !EMAIL.test(email.trim()) ? 'Enter a valid email: the invitation goes there.' : '';

  const submit = () => {
    setIsBusy(true);
    api
      .call(ClusterLeadershipService.method.onboardLeader, {
        clusterId,
        name: name.trim(),
        email: email.trim(),
        phone: phone.trim(),
        reason: reason.trim(),
      })
      .then((answer) => {
        const who = answer.assignment?.leaderName || name.trim();
        if (answer.alreadyLeading) {
          onDone(`${who} already leads ${clusterName}.`);
        } else if (answer.existingAccount) {
          onDone(`${who} already had a Cluster Leader account and now leads ${clusterName}.`);
        } else if (answer.inviteLink) {
          onDone(`${who} now leads ${clusterName}. Send them the link below to set their password.`);
        } else {
          onDone(`${who} now leads ${clusterName}. An invitation to set a password was emailed to ${email.trim()}.`);
        }
        setInvitee({ name: who, email: email.trim(), phone: phone.trim() });
        setLink(answer.inviteLink);
        setName('');
        setEmail('');
        setPhone('');
        setReason('');
        if (!answer.inviteLink) {
          setIsOpen(false);
        }
      })
      .catch((cause: unknown) => onError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <Text style={[styles.title, { color: colors.text }]}>Onboard a new Cluster Leader</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>
        The account can only use the Cluster Leader app for this cluster. The leader sets their own password from the invitation.
      </Text>
      {link ? (
        <View style={[styles.link, { backgroundColor: colors.primarySoft }]}>
          <Text style={[styles.copy, { color: colors.text }]}>
            Email cannot reach the leader from this server. Send them this link to set their password, using any app on your phone:
          </Text>
          <Text style={[styles.mono, { color: colors.text }]} selectable>
            {link}
          </Text>
          <SendLinkOptions link={link} name={invitee.name} clusterName={clusterName} email={invitee.email} phone={invitee.phone} />
          <PrimaryButton
            label="Done"
            isOutline
            onPress={() => {
              setLink('');
              setIsOpen(false);
            }}
          />
        </View>
      ) : (
        <>
          <Field label="Full name *" value={name} onChange={setName} placeholder="Grace Nakato" />
          <Field label="Email *" value={email} onChange={setEmail} placeholder="name@school.org" isEmail />
          <Field label="Phone" value={phone} onChange={setPhone} placeholder="0772 000 000" isNumeric />
          <Field label="Why (optional)" value={reason} onChange={setReason} placeholder="Elected at the Term 1 meeting" />
          {problem ? <Text style={[styles.copy, { color: colors.textMuted }]}>{problem}</Text> : null}
          <PrimaryButton label={isBusy ? 'Onboarding…' : 'Onboard and give the cluster'} icon={UserPlus} onPress={submit} isDisabled={Boolean(problem) || isBusy} />
          <PrimaryButton label="Cancel" isOutline onPress={() => setIsOpen(false)} />
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 10 },
  title: { fontFamily: fonts.bold, fontSize: 16 },
  copy: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  link: { borderRadius: radius.md, padding: 12, gap: 8 },
  mono: { fontFamily: fonts.medium, fontSize: 12 },
});
