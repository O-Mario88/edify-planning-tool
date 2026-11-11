/**
 * Sharing the school loan application: each link the gateway lets this
 * person share, with WhatsApp, SMS, email, copy, other apps and its QR code.
 * Every option opens the person's own app with the approved message filled
 * in; nothing is sent from Edify. Each tap is counted (channel only).
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Image, Linking, Platform, Pressable, ScrollView, Share, StyleSheet, Switch, Text, View } from 'react-native';
import { Copy, Download, Mail, MessageCircle, MessageSquare, Printer, QrCode, Share2 } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetShareKitResponse, ShareLink, ShareMessage } from '../../gen/edify/loans/v1/sharing_pb';
import { LoanShareService } from '../../gen/edify/loans/v1/sharing_pb';
import { fonts, radius, useTheme } from '../../theme';
import { shareLink } from './loanParts';
import { isShareableUrl, shareHref, smsNote, type ShareChannel } from './shareRoutes';

function messageFor(link: ShareLink, channel: 'whatsapp' | 'sms' | 'email'): ShareMessage | undefined {
  return link.messages.find((message) => message.channel === channel);
}

interface ShareButtonProps {
  readonly label: string;
  readonly icon: typeof Mail;
  readonly onPress: () => void;
}

function ShareButton({ label, icon: Icon, onPress }: ShareButtonProps) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => [styles.button, { borderColor: colors.border, backgroundColor: colors.surface, opacity: pressed ? 0.8 : 1 }]}
    >
      <Icon size={18} color={colors.link} />
      <Text style={[styles.buttonText, { color: colors.text }]}>{label}</Text>
    </Pressable>
  );
}

interface ShareLinkCardProps {
  readonly link: ShareLink;
  readonly onPolicy?: (lock: boolean) => void;
  readonly onReplace?: () => void;
}

/** One link and every way to send it. */
export function ShareLinkCard({ link, onPolicy, onReplace }: ShareLinkCardProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [showQr, setShowQr] = useState(false);
  const [note, setNote] = useState('');
  const safe = isShareableUrl(link.url);

  const record = useCallback(
    (channel: ShareChannel) => {
      // Counting is best effort: a failed count never blocks the share.
      api.call(LoanShareService.method.recordShare, { linkKind: link.kind, linkId: link.id, channel }).catch(() => undefined);
    },
    [api, link.id, link.kind],
  );

  const open = (channel: 'whatsapp' | 'sms' | 'email') => {
    const message = messageFor(link, channel);
    if (!message || !safe) {
      return;
    }
    record(channel);
    Linking.openURL(shareHref(channel, message, Platform.OS)).catch(() =>
      setNote(channel === 'whatsapp' ? 'WhatsApp did not open. Copy the link instead.' : 'That app did not open. Copy the link instead.'),
    );
  };
  const copy = () => {
    record('copy');
    shareLink(link.url, link.title)
      .then((answer) => setNote(answer))
      .catch((cause: unknown) => setNote(describe(cause)));
  };
  const others = () => {
    const message = messageFor(link, 'whatsapp');
    record('native');
    Share.share({ message: message?.body ?? link.url, title: link.title }).catch(() => undefined);
  };
  const sms = messageFor(link, 'sms');

  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <Text style={[styles.cardTitle, { color: colors.text }]} accessibilityRole="header">
        {link.title}
      </Text>
      {link.description ? <Text style={[styles.copy, { color: colors.textMuted }]}>{link.description}</Text> : null}
      <View style={[styles.url, { backgroundColor: colors.surface, borderColor: colors.fieldBorder }]}>
        <Text style={[styles.urlText, { color: colors.text }]} selectable numberOfLines={2}>
          {link.url}
        </Text>
      </View>
      {link.expiresOn ? <Text style={[styles.meta, { color: colors.textSubtle }]}>Works until {link.expiresOn}.</Text> : null}
      {safe ? (
        <View style={styles.buttons}>
          <ShareButton label="WhatsApp" icon={MessageCircle} onPress={() => open('whatsapp')} />
          <ShareButton label="SMS" icon={MessageSquare} onPress={() => open('sms')} />
          <ShareButton label="Email" icon={Mail} onPress={() => open('email')} />
          <ShareButton label={Platform.OS === 'web' ? 'Copy link' : 'Copy'} icon={Copy} onPress={copy} />
          <ShareButton label="Other apps" icon={Share2} onPress={others} />
          {link.qrUrl ? (
            <ShareButton
              label={showQr ? 'Hide QR code' : 'QR code'}
              icon={QrCode}
              onPress={() => {
                if (!showQr) {
                  record('qr');
                }
                setShowQr(!showQr);
              }}
            />
          ) : null}
        </View>
      ) : (
        <Text style={[styles.copy, { color: colors.danger }]}>This server has no HTTPS address set, so this link cannot be shared.</Text>
      )}
      {sms && smsNote(sms.smsParts) ? <Text style={[styles.meta, { color: colors.textSubtle }]}>SMS: {smsNote(sms.smsParts)}</Text> : null}
      {note ? (
        <Text style={[styles.meta, { color: colors.textMuted }]} accessibilityLiveRegion="polite">
          {note}
        </Text>
      ) : null}
      {showQr && link.qrUrl ? (
        <View style={styles.qr}>
          <Image source={{ uri: link.qrUrl }} style={styles.qrImage} accessibilityLabel="QR code for this application link" />
          <Text style={[styles.qrCall, { color: colors.text }]}>Scan to Apply for a School Loan</Text>
          <View style={styles.buttons}>
            <ShareButton label="Download QR" icon={Download} onPress={() => Linking.openURL(`${link.qrUrl}?download=1`)} />
            <ShareButton label="Print poster" icon={Printer} onPress={() => Linking.openURL(link.posterUrl)} />
          </View>
        </View>
      ) : null}
      {onPolicy ? (
        <View style={[styles.policy, { borderTopColor: colors.border }]}>
          <View style={styles.policyText}>
            <Text style={[styles.policyLabel, { color: colors.text }]}>Schools apply to {link.lenderName} only</Text>
            <Text style={[styles.meta, { color: colors.textMuted }]}>
              {link.lockPartner ? 'The school cannot choose another lender.' : 'The school may choose another lender.'}
            </Text>
          </View>
          <Switch value={link.lockPartner} onValueChange={onPolicy} accessibilityLabel={`Schools apply to ${link.lenderName} only`} />
        </View>
      ) : null}
      {onReplace ? (
        <Pressable onPress={onReplace} accessibilityRole="button" style={styles.replace}>
          <Text style={[styles.replaceText, { color: colors.link }]}>Replace this link (the old one stops working)</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/** The share page: every link this person may share. */
interface ShareApplicationScreenProps {
  readonly eyebrow?: string;
  readonly onBack?: () => void;
}

export function ShareApplicationScreen({ eyebrow, onBack }: ShareApplicationScreenProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [kit, setKit] = useState<GetShareKitResponse | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    setError('');
    api
      .call(LoanShareService.method.getShareKit, {})
      .then(setKit)
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api]);
  useEffect(load, [load]);

  const replaceWith = (index: number, link: ShareLink | undefined) =>
    link && setKit((current) => current && { ...current, links: current.links.map((old, at) => (at === index ? link : old)) });

  return (
    <ScrollView contentContainerStyle={styles.page}>
      {onBack ? (
        <Pressable onPress={onBack} accessibilityRole="button" style={styles.replace}>
          <Text style={[styles.replaceText, { color: colors.link }]}>‹ Back</Text>
        </Pressable>
      ) : null}
      {eyebrow ? <Text style={[styles.eyebrow, { color: colors.eyebrow }]}>{eyebrow.toUpperCase()}</Text> : null}
      <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
        Share the loan application
      </Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>
        Schools open the link and apply without an account. Choose how to send it; your own app opens with the message ready.
      </Text>
      {error ? (
        <Text style={[styles.copy, { color: colors.danger }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
      {kit === null && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
      {kit?.links.map((link, index) => (
        <ShareLinkCard
          key={`${link.kind}-${link.id}`}
          link={link}
          onPolicy={
            link.canSetPolicy
              ? (lock) =>
                  api
                    .call(LoanShareService.method.setPartnerLinkPolicy, { lockPartner: lock })
                    .then((answer) => replaceWith(index, answer.link))
                    .catch((cause: unknown) => setError(describe(cause)))
              : undefined
          }
          onReplace={
            link.canReplace
              ? () =>
                  api
                    .call(LoanShareService.method.replaceShareLink, { linkId: link.id, reason: 'Replaced from the app' })
                    .then((answer) => replaceWith(index, answer.link))
                    .catch((cause: unknown) => setError(describe(cause)))
              : undefined
          }
        />
      ))}
      {kit?.clusters.length ? (
        <Text style={[styles.copy, { color: colors.textMuted }]}>
          To invite a particular school, open Schools and choose “Invite to apply” on it. You can invite the member schools of{' '}
          {kit.clusters.map((cluster) => cluster.name).join(', ')}.
        </Text>
      ) : null}
      {kit?.note ? <Text style={[styles.meta, { color: colors.textSubtle }]}>{kit.note}</Text> : null}
    </ScrollView>
  );
}

interface InviteSchoolPanelProps {
  readonly schoolId: string;
  readonly schoolName: string;
}

/** Makes a school's invitation and shows how to send it. */
export function InviteSchoolPanel({ schoolId, schoolName }: InviteSchoolPanelProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [link, setLink] = useState<ShareLink | null>(null);
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);

  const invite = () => {
    setIsBusy(true);
    setError('');
    api
      .call(LoanShareService.method.inviteSchool, { schoolId })
      .then((answer) => setLink(answer.link ?? null))
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  if (link) {
    return <ShareLinkCard link={link} />;
  }
  return (
    <View style={styles.invite}>
      <Pressable
        onPress={invite}
        disabled={isBusy}
        accessibilityRole="button"
        accessibilityLabel={`Invite ${schoolName} to apply for a school loan`}
        style={[styles.inviteButton, { backgroundColor: colors.primary, opacity: isBusy ? 0.7 : 1 }]}
      >
        {isBusy ? <ActivityIndicator color={colors.primaryInk} /> : <Text style={[styles.inviteText, { color: colors.primaryInk }]}>Make an invitation link</Text>}
      </Pressable>
      <Text style={[styles.meta, { color: colors.textMuted }]}>
        It opens the public form with the school’s name filled in, and replaces any earlier invitation for it. You will not see whether the school applies.
      </Text>
      {error ? (
        <Text style={[styles.meta, { color: colors.danger }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { padding: 12, gap: 12, paddingBottom: 32 },
  eyebrow: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 1.2 },
  title: { fontFamily: fonts.bold, fontSize: 22, letterSpacing: -0.2 },
  copy: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  meta: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 17 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 10 },
  cardTitle: { fontFamily: fonts.bold, fontSize: 16 },
  url: { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10 },
  urlText: { fontFamily: fonts.medium, fontSize: 13 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  button: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 14, minHeight: 44 },
  buttonText: { fontFamily: fonts.semibold, fontSize: 14 },
  qr: { alignItems: 'center', gap: 10, paddingTop: 4 },
  qrImage: { width: 240, height: 240, backgroundColor: '#ffffff', borderRadius: radius.sm },
  qrCall: { fontFamily: fonts.bold, fontSize: 16 },
  policy: { flexDirection: 'row', alignItems: 'center', gap: 12, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 10 },
  policyText: { flex: 1, gap: 2 },
  policyLabel: { fontFamily: fonts.semibold, fontSize: 14 },
  replace: { minHeight: 44, justifyContent: 'center' },
  replaceText: { fontFamily: fonts.semibold, fontSize: 13 },
  invite: { gap: 8 },
  inviteButton: { alignSelf: 'flex-start', borderRadius: radius.pill, paddingHorizontal: 18, minHeight: 44, justifyContent: 'center' },
  inviteText: { fontFamily: fonts.bold, fontSize: 14 },
});
