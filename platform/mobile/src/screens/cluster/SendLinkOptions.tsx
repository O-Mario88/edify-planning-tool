/**
 * The ways to send a new Cluster Leader their set-password link (owner,
 * 2026-11-11: "Send the link should open medium of sending like whatsapp,
 * email … that already exist on the phone"). Each tile opens the person's
 * own app with the message filled in and, where the number or address is
 * known, the leader already chosen; "More apps" opens the phone's share sheet
 * with every other app on it. Nothing is sent from Edify.
 */
import { useState } from 'react';
import { Linking, Platform, Share, StyleSheet, Text, View } from 'react-native';
import { Copy, Mail, MessageCircle, MessageSquare, Share2 } from 'lucide-react-native';

import { fonts, useTheme } from '../../theme';
import { ShareTile } from '../loans/ShareSheet';
import { shareLink } from '../loans/loanParts';
import { inviteText, shareHref } from '../loans/shareRoutes';

interface SendLinkOptionsProps {
  readonly link: string;
  readonly name: string;
  readonly clusterName: string;
  readonly email: string;
  readonly phone: string;
}

export function SendLinkOptions({ link, name, clusterName, email, phone }: SendLinkOptionsProps) {
  const { colors } = useTheme();
  const [note, setNote] = useState('');
  const text = inviteText(name, clusterName, link);
  const isWeb = Platform.OS === 'web';

  const open = (channel: 'whatsapp' | 'sms' | 'email', to: string, app: string) => {
    setNote('');
    Linking.openURL(shareHref(channel, text, Platform.OS, to)).catch(() =>
      setNote(`${app} did not open on this device. Try another way below.`),
    );
  };
  const more = () => {
    setNote('');
    Share.share({ message: text.body, title: text.subject }).catch(() => setNote('The share sheet did not open. Copy the link instead.'));
  };
  const copy = () => {
    shareLink(link, text.subject ?? '')
      .then((answer) => setNote(answer))
      .catch(() => setNote('The link could not be copied. Select it above and copy it.'));
  };

  return (
    <View style={styles.stack}>
      <View style={styles.tiles}>
        <ShareTile title="WhatsApp" caption={phone ? `Chat with ${phone}` : 'Choose the chat'} icon={MessageCircle} onPress={() => open('whatsapp', phone, 'WhatsApp')} />
        {!isWeb ? <ShareTile title="SMS" caption={phone ? `Text ${phone}` : 'Send by text'} icon={MessageSquare} onPress={() => open('sms', phone, 'Messages')} /> : null}
        <ShareTile title="Email" caption={email ? `Email ${email}` : 'Send by email'} icon={Mail} onPress={() => open('email', email, 'Your mail app')} />
        {isWeb ? (
          <ShareTile title="Copy Link" caption="Paste anywhere" icon={Copy} onPress={copy} />
        ) : (
          <ShareTile title="More apps" caption="Telegram, Signal, copy…" icon={Share2} onPress={more} />
        )}
      </View>
      {note ? (
        <Text style={[styles.note, { color: colors.textMuted }]} accessibilityLiveRegion="polite">
          {note}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 8 },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  note: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
});
