/**
 * A page header's parts, as the web's edify-page-header draws them on a
 * phone: the description (a "Label: value" line set bold after its colon),
 * the header's pills, its buttons, and the profile tab rail.
 */
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { PageAction, PageBadge } from '../../gen/edify/screens/v1/page_pb';
import { fonts, toneColors, useTheme } from '../../theme';

export function Description({ text }: { readonly text: string }) {
  const { colors } = useTheme();
  const at = text.indexOf(': ');
  return (
    <Text style={[styles.description, { color: colors.textMuted }]}>
      {at > 0 ? (
        <>
          {text.slice(0, at + 2)}
          <Text style={[styles.descriptionValue, { color: colors.text }]}>{text.slice(at + 2)}</Text>
        </>
      ) : (
        text
      )}
    </Text>
  );
}

export function Badge({ badge, isWide }: { readonly badge: PageBadge; readonly isWide: boolean }) {
  const { colors } = useTheme();
  const tone = badge.tone === 'plain' ? undefined : toneColors(colors, badge.tone);
  return (
    <View
      accessibilityLabel={badge.title ? `${badge.text}. ${badge.title}` : badge.text}
      style={[
        styles.badge,
        isWide && styles.wide,
        tone ? { backgroundColor: tone.soft, borderColor: tone.fg, borderWidth: 1 } : { backgroundColor: colors.surfaceMuted },
      ]}
    >
      <Text style={[styles.badgeText, { color: tone ? tone.fg : colors.textMuted }]}>{badge.text}</Text>
    </View>
  );
}

export function ActionButton({ action, onPress }: { readonly action: PageAction; readonly onPress: () => void }) {
  const { colors } = useTheme();
  const look = action.primary
    ? { backgroundColor: colors.primary, borderColor: colors.primary }
    : action.enabled
      ? { backgroundColor: colors.raised, borderColor: colors.border }
      : { backgroundColor: colors.surfaceMuted, borderColor: colors.border };
  const ink = action.primary ? colors.primaryInk : action.enabled ? colors.text : colors.textSubtle;
  return (
    <Pressable
      onPress={onPress}
      disabled={!action.enabled}
      accessibilityRole="button"
      accessibilityLabel={action.enabled ? action.label : `${action.label} unavailable: ${action.reason}`}
      accessibilityState={{ disabled: !action.enabled }}
      style={[styles.action, look, action.primary ? styles.primaryShadow : styles.shadow]}
    >
      <Text style={[styles.actionText, { color: ink }]}>{action.label}</Text>
    </Pressable>
  );
}

export interface TabItem {
  readonly key: string;
  readonly label: string;
  readonly active: boolean;
}

/** The profile's tab rail: straight dividers, the open tab filled, the rail
 * scrolling sideways when it is longer than the screen. */
export function TabRail({ tabs, onPick }: { readonly tabs: readonly TabItem[]; readonly onPick: (key: string) => void }) {
  const { colors } = useTheme();
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={[styles.rail, { backgroundColor: colors.surface }]}
      accessibilityRole="tablist"
    >
      {tabs.map((tab, index) => {
        const next = tabs[index + 1];
        const hasRule = next !== undefined && !tab.active && !next.active;
        return (
          <Pressable
            key={tab.key}
            onPress={() => onPick(tab.key)}
            accessibilityRole="tab"
            accessibilityState={{ selected: tab.active }}
            style={[styles.tab, tab.active && { backgroundColor: colors.segmentActive }, tab.active && index === 0 && styles.tabFirst]}
          >
            <Text style={[styles.tabText, tab.active ? styles.tabOn : { color: colors.textMuted }]}>{tab.label}</Text>
            {hasRule ? <View style={[styles.tabRule, { backgroundColor: colors.border }]} /> : null}
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  description: { fontFamily: fonts.medium, fontSize: 13, marginTop: 4 },
  descriptionValue: { fontFamily: fonts.bold },
  badge: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2, alignItems: 'center' },
  wide: { width: '100%' },
  badgeText: { fontFamily: fonts.semibold, fontSize: 12 },
  action: {
    flexGrow: 1,
    height: 32,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  shadow: { boxShadow: '0px 1px 3px 0px rgba(0, 0, 0, 0.1), 0px 1px 2px -1px rgba(0, 0, 0, 0.1)' },
  primaryShadow: { boxShadow: '0px 6px 14px -10px rgba(14, 93, 163, 0.44)' },
  actionText: { fontFamily: fonts.semibold, fontSize: 12 },
  rail: { flexGrow: 0, borderRadius: 10 },
  tab: { height: 32, paddingHorizontal: 14, justifyContent: 'center' },
  tabFirst: { borderTopLeftRadius: 8, borderBottomLeftRadius: 8 },
  tabText: { fontFamily: fonts.semibold, fontSize: 13 },
  tabOn: { fontFamily: fonts.bold, color: '#ffffff' },
  tabRule: { position: 'absolute', right: 0, top: 8, bottom: 8, width: 1 },
});
