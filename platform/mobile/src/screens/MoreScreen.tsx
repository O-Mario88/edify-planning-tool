/**
 * The menu behind "More", and the pages that are still on the web app.
 *
 * The menu is the reader's own sidebar, section by section, as the existing
 * application builds it for their role. A page that has not been rebuilt yet
 * says so plainly and opens the same page of the Edify web app, rather than
 * showing a screen that looks finished and is not.
 */
import { Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ChevronRight, ExternalLink, LogOut } from 'lucide-react-native';

import { useSession } from '../auth/SessionContext';
import type { Session } from '../gen/edify/identity/v1/identity_pb';
import type { NavSection } from '../gen/edify/screens/v1/navigation_pb';
import { fonts, radius, spacing, type, useTheme } from '../theme';
import { SvgIcon } from '../ui/SvgIcon';

interface WebOnlyScreenProps {
  readonly title: string;
  /** Path of the same page on the web app, e.g. "/my-plan". */
  readonly webPath: string;
}

export function WebOnlyScreen({ title, webPath }: WebOnlyScreenProps) {
  const { environment } = useSession();
  const { colors } = useTheme();
  return (
    <ScrollView contentContainerStyle={styles.scroll}>
      <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
        {title}
      </Text>
      <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
        <Text style={[styles.cardTitle, { color: colors.text }]}>Still on the web app</Text>
        <Text style={[styles.body, { color: colors.textMuted }]}>
          {title} has not moved into this app yet. Nothing is missing: it is where it has always
          been, in the Edify web app.
        </Text>
        <WebLink label={`Open ${title} on the web`} url={`${environment.identityUrl}${webPath}`} />
      </View>
    </ScrollView>
  );
}

interface MenuScreenProps {
  readonly session: Session;
  readonly sections: readonly NavSection[];
  /** Whether a path has a native screen. */
  readonly isNative: (url: string) => boolean;
  readonly onOpen: (url: string, label: string) => void;
}

export function MenuScreen({ session, sections, isNative, onOpen }: MenuScreenProps) {
  const { signOut } = useSession();
  const { colors } = useTheme();
  return (
    <ScrollView contentContainerStyle={styles.scroll}>
      <View style={[styles.card, styles.account, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
        <View style={styles.accountText}>
          <Text style={[styles.cardTitle, { color: colors.text }]}>{session.name}</Text>
          <Text style={[styles.body, styles.accountBody, { color: colors.textMuted }]}>
            {session.activeRole} · {session.email}
          </Text>
        </View>
      </View>

      {sections.map((section) => (
        <View key={section.label} style={styles.section}>
          <Text style={[styles.sectionLabel, { color: colors.textSubtle }]}>{section.label}</Text>
          <View style={[styles.group, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
            {section.items.map((item, index) => (
              <Pressable
                key={`${item.url}-${item.label}`}
                onPress={() => onOpen(item.url, item.label)}
                accessibilityRole="link"
                accessibilityLabel={isNative(item.url) ? item.label : `${item.label}, opens on the web`}
                style={[styles.row, index > 0 && { borderTopWidth: 1, borderTopColor: colors.raisedBorder }]}
              >
                <SvgIcon xml={item.iconSvg} size={20} color={colors.textMuted} />
                <Text style={[styles.rowLabel, { color: colors.text }]} numberOfLines={1}>
                  {item.label}
                </Text>
                {isNative(item.url) ? (
                  <ChevronRight size={16} color={colors.textSubtle} />
                ) : (
                  <ExternalLink size={14} color={colors.textSubtle} />
                )}
              </Pressable>
            ))}
          </View>
        </View>
      ))}

      <Pressable
        onPress={() => void signOut()}
        accessibilityRole="button"
        accessibilityLabel="Sign out"
        style={[styles.signOut, { borderColor: colors.borderStrong, backgroundColor: colors.raised }]}
      >
        <LogOut size={18} color={colors.danger} />
        <Text style={[styles.signOutText, { color: colors.danger }]}>Sign out</Text>
      </Pressable>
    </ScrollView>
  );
}

function WebLink({ label, url }: { readonly label: string; readonly url: string }) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={() => void Linking.openURL(url)}
      accessibilityRole="link"
      accessibilityLabel={label}
      style={[styles.webLink, { backgroundColor: colors.primary }]}
    >
      <Text style={[styles.webLinkText, { color: colors.primaryInk }]}>{label}</Text>
      <ExternalLink size={16} color={colors.primaryInk} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: spacing.md, paddingBottom: spacing.xxl },
  title: { fontFamily: fonts.bold, fontSize: type.title, marginTop: spacing.md, marginBottom: spacing.lg },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, marginBottom: spacing.lg },
  cardTitle: { fontFamily: fonts.bold, fontSize: type.control, marginBottom: spacing.sm },
  body: { fontFamily: fonts.regular, fontSize: type.body, lineHeight: 19.5, marginBottom: spacing.lg },
  account: { flexDirection: 'row', alignItems: 'center' },
  accountText: { flex: 1 },
  accountBody: { marginBottom: 0 },
  section: { marginBottom: spacing.lg },
  sectionLabel: {
    fontFamily: fonts.semibold,
    fontSize: type.small,
    textTransform: 'uppercase',
    marginBottom: spacing.sm,
    marginLeft: spacing.xs,
  },
  group: { borderWidth: 1, borderRadius: radius.lg, overflow: 'hidden' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    minHeight: 48,
    paddingHorizontal: 14,
  },
  rowLabel: { flex: 1, fontFamily: fonts.semibold, fontSize: type.body },
  webLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    minHeight: 44,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.lg,
  },
  webLinkText: { fontFamily: fonts.semibold, fontSize: type.body },
  signOut: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    minHeight: 48,
    borderWidth: 1,
    borderRadius: radius.sm,
  },
  signOutText: { fontFamily: fonts.semibold, fontSize: type.control - 1 },
});
