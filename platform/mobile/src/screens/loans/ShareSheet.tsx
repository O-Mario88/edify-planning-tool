/**
 * Sharing the school loan application, laid out after the owner's mockup
 * (2026-11-11) in Edify's blue: the link with a copy button, WhatsApp, SMS,
 * Email and Copy Link tiles, the QR code, how it works for schools, and
 * Share Now. Every option opens the person's own app with the approved
 * message filled in; nothing is sent from Edify. Each tap is counted.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Image, Linking, Platform, Pressable, ScrollView, Share, StyleSheet, Switch, Text, View } from 'react-native';
import { ChevronDown, ChevronRight, Copy, Download, Info, Link2, Mail, MessageCircle, MessageSquare, Printer, QrCode, Share2, type LucideIcon } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetShareKitResponse, ShareLink, ShareMessage } from '../../gen/edify/loans/v1/sharing_pb';
import { LoanShareService } from '../../gen/edify/loans/v1/sharing_pb';
import { fonts, radius, useTheme } from '../../theme';
import { shareLink } from './loanParts';
import { LoanHero, LoanSheet, PrimaryButton } from './loanUi';
import { isShareableUrl, shareHref, smsNote, type ShareChannel } from './shareRoutes';

function messageFor(link: ShareLink, channel: 'whatsapp' | 'sms' | 'email'): ShareMessage | undefined {
  return link.messages.find((message) => message.channel === channel);
}

/** Counts a share; a failed count never blocks the share. */
function useRecord(link: ShareLink) {
  const { api } = useSession();
  return useCallback(
    (channel: ShareChannel) => {
      api.call(LoanShareService.method.recordShare, { linkKind: link.kind, linkId: link.id, channel }).catch(() => undefined);
    },
    [api, link.id, link.kind],
  );
}

/** Opens the native share sheet with the link's WhatsApp text. */
function shareNow(link: ShareLink, record: (channel: ShareChannel) => void) {
  record('native');
  Share.share({ message: messageFor(link, 'whatsapp')?.body ?? link.url, title: link.title }).catch(() => undefined);
}

interface ShareTileProps {
  readonly title: string;
  readonly caption: string;
  readonly icon: LucideIcon;
  readonly onPress: () => void;
}

function ShareTile({ title, caption, icon: Icon, onPress }: ShareTileProps) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${title}: ${caption}`}
      style={({ pressed }) => [styles.tile, { backgroundColor: colors.raised, borderColor: colors.raisedBorder, opacity: pressed ? 0.85 : 1 }]}
    >
      <View style={[styles.tileIcon, { backgroundColor: colors.primarySoft }]}>
        <Icon size={20} color={colors.primary} />
      </View>
      <View style={styles.tileText}>
        <Text style={[styles.tileTitle, { color: colors.text }]}>{title}</Text>
        <Text style={[styles.tileCaption, { color: colors.textMuted }]} numberOfLines={2}>
          {caption}
        </Text>
      </View>
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
  const { colors } = useTheme();
  const record = useRecord(link);
  const [showQr, setShowQr] = useState(false);
  const [note, setNote] = useState('');
  const safe = isShareableUrl(link.url);

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
  const sms = messageFor(link, 'sms');

  return (
    <View style={styles.cardStack}>
      <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
        <View style={styles.cardHead}>
          <Link2 size={20} color={colors.primary} />
          <Text style={[styles.cardTitle, { color: colors.text }]} accessibilityRole="header">
            {link.title}
          </Text>
        </View>
        <View style={[styles.url, { backgroundColor: colors.surface, borderColor: colors.fieldBorder }]}>
          <Text style={[styles.urlText, { color: colors.text }]} selectable numberOfLines={2}>
            {link.url}
          </Text>
          {safe ? (
            <Pressable onPress={copy} accessibilityRole="button" accessibilityLabel="Copy the link" hitSlop={10} style={styles.urlCopy}>
              <Copy size={18} color={colors.textMuted} />
            </Pressable>
          ) : null}
        </View>
        {link.description ? <Text style={[styles.caption, { color: colors.textMuted }]}>{link.description}</Text> : null}
        {link.expiresOn ? <Text style={[styles.caption, { color: colors.textSubtle }]}>Works until {link.expiresOn}.</Text> : null}
      </View>

      {safe ? (
        <View style={styles.tiles}>
          <ShareTile title="WhatsApp" caption="Share via WhatsApp" icon={MessageCircle} onPress={() => open('whatsapp')} />
          <ShareTile title="SMS" caption="Send by text" icon={MessageSquare} onPress={() => open('sms')} />
          <ShareTile title="Email" caption="Send by email" icon={Mail} onPress={() => open('email')} />
          <ShareTile title="Copy Link" caption="Paste anywhere" icon={Copy} onPress={copy} />
        </View>
      ) : (
        <Text style={[styles.caption, { color: colors.danger }]}>This server has no HTTPS address set, so this link cannot be shared.</Text>
      )}
      {sms && smsNote(sms.smsParts) ? <Text style={[styles.caption, { color: colors.textSubtle }]}>SMS: {smsNote(sms.smsParts)}</Text> : null}
      {note ? (
        <Text style={[styles.caption, { color: colors.textMuted }]} accessibilityLiveRegion="polite">
          {note}
        </Text>
      ) : null}

      {safe && link.qrUrl ? (
        <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
          <Pressable
            onPress={() => {
              if (!showQr) {
                record('qr');
              }
              setShowQr(!showQr);
            }}
            accessibilityRole="button"
            accessibilityState={{ expanded: showQr }}
            accessibilityLabel="QR Code: let schools scan to apply"
            style={styles.qrRow}
          >
            <View style={[styles.tileIcon, { backgroundColor: colors.primarySoft }]}>
              <QrCode size={20} color={colors.primary} />
            </View>
            <View style={styles.tileText}>
              <Text style={[styles.tileTitle, { color: colors.text }]}>QR Code</Text>
              <Text style={[styles.tileCaption, { color: colors.textMuted }]}>Let schools scan to apply</Text>
            </View>
            {showQr ? <ChevronDown size={20} color={colors.textMuted} /> : <ChevronRight size={20} color={colors.textMuted} />}
          </Pressable>
          {showQr ? (
            <View style={styles.qr}>
              <Image source={{ uri: link.qrUrl }} style={styles.qrImage} accessibilityLabel="QR code for this application link" />
              <Text style={[styles.qrCall, { color: colors.text }]}>Scan to Apply for a School Loan</Text>
              <View style={styles.qrButtons}>
                <PrimaryButton label="Download QR" icon={Download} isOutline onPress={() => Linking.openURL(`${link.qrUrl}?download=1`)} />
                <PrimaryButton label="Print poster" icon={Printer} isOutline onPress={() => Linking.openURL(link.posterUrl)} />
              </View>
            </View>
          ) : null}
        </View>
      ) : null}

      {onPolicy ? (
        <View style={[styles.card, styles.policy, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
          <View style={styles.tileText}>
            <Text style={[styles.tileTitle, { color: colors.text }]}>Schools apply to {link.lenderName} only</Text>
            <Text style={[styles.tileCaption, { color: colors.textMuted }]}>
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

const STEPS = ['Open the link (no login or signup).', 'Fill in school and loan details.', 'Choose a lending partner.', 'Submit and receive a reference number.'];

function HowItWorks() {
  const { colors } = useTheme();
  return (
    <View style={[styles.how, { backgroundColor: colors.primarySoft }]}>
      <View style={styles.cardHead}>
        <Info size={18} color={colors.primary} />
        <Text style={[styles.tileTitle, { color: colors.text }]}>How it works for schools</Text>
      </View>
      {STEPS.map((step, index) => (
        <View key={step} style={styles.step}>
          <View style={[styles.stepNumber, { backgroundColor: colors.raised }]}>
            <Text style={[styles.stepNumberText, { color: colors.primary }]}>{index + 1}</Text>
          </View>
          <Text style={[styles.stepText, { color: colors.text }]}>{step}</Text>
        </View>
      ))}
    </View>
  );
}

interface ShareApplicationScreenProps {
  readonly eyebrow?: string;
  readonly onBack?: () => void;
}

/** The share page: every link this person may share. */
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
  const first = kit?.links[0];

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <LoanHero
        eyebrow={eyebrow}
        title="Share Loan Application"
        subtitle="Invite schools to apply for a loan from our participating lending partners."
        onBack={onBack}
      />
      <LoanSheet>
        {error ? (
          <Text style={[styles.caption, { color: colors.danger }]} accessibilityRole="alert">
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
        {kit ? <HowItWorks /> : null}
        {first && isShareableUrl(first.url) ? <ShareNowButton link={first} /> : null}
        {kit?.canInviteSchools ? (
          <Text style={[styles.caption, { color: colors.textMuted }]}>
            To invite one school by name, open it under Schools and choose “Invite to apply for a loan”
            {kit.clusters.length ? ` (member schools of ${kit.clusters.map((cluster) => cluster.name).join(', ')})` : ''}.
          </Text>
        ) : null}
        {kit?.note ? <Text style={[styles.caption, { color: colors.textSubtle }]}>{kit.note}</Text> : null}
      </LoanSheet>
    </ScrollView>
  );
}

function ShareNowButton({ link }: { readonly link: ShareLink }) {
  const record = useRecord(link);
  return <PrimaryButton label="Share Now" icon={Share2} onPress={() => shareNow(link, record)} />;
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
      <PrimaryButton label={isBusy ? 'Making the link…' : 'Make an invitation link'} onPress={invite} isDisabled={isBusy} />
      <Text style={[styles.caption, { color: colors.textMuted }]}>
        It opens the public form with {schoolName}’s name filled in, and replaces any earlier invitation for it. You will not see whether the
        school applies.
      </Text>
      {error ? (
        <Text style={[styles.caption, { color: colors.danger }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  cardStack: { gap: 10 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 8 },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardTitle: { fontFamily: fonts.bold, fontSize: 16, flex: 1 },
  url: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: radius.sm, paddingLeft: 12, paddingRight: 6, minHeight: 46 },
  urlText: { flex: 1, fontFamily: fonts.medium, fontSize: 14, paddingVertical: 8 },
  urlCopy: { minWidth: 40, minHeight: 40, alignItems: 'center', justifyContent: 'center' },
  caption: { fontFamily: fonts.medium, fontSize: 12.5, lineHeight: 18 },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  tile: { flexGrow: 1, flexBasis: '45%', minWidth: 140, flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderRadius: radius.md, padding: 12, minHeight: 64 },
  tileIcon: { width: 38, height: 38, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  tileText: { flex: 1, gap: 1 },
  tileTitle: { fontFamily: fonts.bold, fontSize: 14 },
  tileCaption: { fontFamily: fonts.medium, fontSize: 12 },
  qrRow: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 44 },
  qr: { alignItems: 'center', gap: 10, paddingTop: 4 },
  qrImage: { width: 240, height: 240, backgroundColor: '#ffffff', borderRadius: radius.sm },
  qrCall: { fontFamily: fonts.bold, fontSize: 16 },
  qrButtons: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, justifyContent: 'center' },
  policy: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  replace: { minHeight: 44, justifyContent: 'center' },
  replaceText: { fontFamily: fonts.semibold, fontSize: 13 },
  how: { borderRadius: radius.lg, padding: 14, gap: 8 },
  step: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  stepNumber: { width: 24, height: 24, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  stepNumberText: { fontFamily: fonts.bold, fontSize: 12 },
  stepText: { fontFamily: fonts.medium, fontSize: 14, flex: 1 },
  invite: { gap: 8 },
});
