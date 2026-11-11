/**
 * The loan screens' own frame, after the owner's mockups (2026-11-11) in
 * Edify's blue: a hero band with the page's title, counter tiles with an
 * icon, segmented tabs, status chips and small icon actions. Status colours
 * keep their meaning (green done, amber due, red overdue, blue in hand).
 */
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { ChevronLeft, type LucideIcon } from 'lucide-react-native';

import { fonts, radius, toneColors, useTheme } from '../../theme';

interface LoanHeroProps {
  readonly eyebrow?: string;
  readonly title: string;
  readonly subtitle?: string;
  readonly onBack?: () => void;
}

/** The blue band at the top of a loan page. */
export function LoanHero({ eyebrow, title, subtitle, onBack }: LoanHeroProps) {
  const { colors } = useTheme();
  return (
    <LinearGradient colors={colors.heroGradient} style={styles.hero}>
      {onBack ? (
        <Pressable onPress={onBack} accessibilityRole="button" accessibilityLabel="Back" hitSlop={12} style={styles.back}>
          <ChevronLeft size={22} color="#ffffff" />
        </Pressable>
      ) : null}
      {eyebrow ? <Text style={styles.heroEyebrow}>{eyebrow.toUpperCase()}</Text> : null}
      <Text style={styles.heroTitle} accessibilityRole="header">
        {title}
      </Text>
      {subtitle ? <Text style={styles.heroSubtitle}>{subtitle}</Text> : null}
    </LinearGradient>
  );
}

/** The sheet that overlaps the hero, holding the page. */
export function LoanSheet({ children }: { readonly children: ReactNode }) {
  return <View style={styles.sheet}>{children}</View>;
}

interface CounterTileProps {
  readonly label: string;
  readonly value: string;
  readonly detail?: string;
  readonly icon: LucideIcon;
  readonly tone: 'info' | 'caution' | 'good' | 'alert' | 'brand';
  readonly isSelected?: boolean;
  readonly onPress?: () => void;
}

/** A counter: icon, figure and label on the tone's soft colour; it filters. */
export function CounterTile({ label, value, detail, icon: Icon, tone, isSelected, onPress }: CounterTileProps) {
  const { colors } = useTheme();
  const toneSet = toneColors(colors, tone);
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : 'summary'}
      accessibilityState={{ selected: Boolean(isSelected) }}
      accessibilityLabel={`${label}: ${value}${detail ? `, ${detail}` : ''}`}
      style={({ pressed }) => [
        styles.counter,
        { backgroundColor: toneSet.soft, borderColor: isSelected ? toneSet.fg : 'transparent', opacity: pressed ? 0.85 : 1 },
      ]}
    >
      <Icon size={22} color={toneSet.fg} />
      <View style={styles.counterText}>
        <Text style={[styles.counterLabel, { color: colors.text }]} numberOfLines={1}>
          {label}
        </Text>
        <Text style={[styles.counterValue, { color: tone === 'alert' ? toneSet.fg : colors.text }]}>{value}</Text>
        {detail ? (
          <Text style={[styles.counterDetail, { color: colors.textMuted }]} numberOfLines={1}>
            {detail}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

export function CounterGrid({ children }: { readonly children: ReactNode }) {
  return <View style={styles.counterGrid}>{children}</View>;
}

interface SegmentTabsProps<T extends string> {
  readonly tabs: readonly { readonly key: T; readonly label: string }[];
  readonly value: T;
  readonly onChange: (key: T) => void;
}

/** Segmented tabs: the chosen one filled in blue. */
export function SegmentTabs<T extends string>({ tabs, value, onChange }: SegmentTabsProps<T>) {
  const { colors } = useTheme();
  return (
    <View style={[styles.segments, { backgroundColor: colors.surfaceMuted }]} accessibilityRole="tablist">
      {tabs.map((tab) => {
        const isOn = tab.key === value;
        return (
          <Pressable
            key={tab.key}
            onPress={() => onChange(tab.key)}
            accessibilityRole="tab"
            accessibilityState={{ selected: isOn }}
            style={[styles.segment, isOn && { backgroundColor: colors.primary }]}
          >
            <Text style={[styles.segmentText, { color: isOn ? colors.primaryInk : colors.text }]} numberOfLines={1}>
              {tab.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** A status chip in its tone. */
export function StatusChip({ label, tone }: { readonly label: string; readonly tone: string }) {
  const { colors } = useTheme();
  const toneSet = toneColors(colors, tone);
  return (
    <View style={[styles.chip, { backgroundColor: toneSet.soft }]} accessibilityLabel={label}>
      <Text style={[styles.chipText, { color: toneSet.fg }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

interface IconActionProps {
  readonly label: string;
  readonly icon: LucideIcon;
  readonly onPress: () => void;
  readonly isDisabled?: boolean;
}

/** A small icon-and-word action, as under a school card. */
export function IconAction({ label, icon: Icon, onPress, isDisabled }: IconActionProps) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      disabled={isDisabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => [styles.iconAction, { opacity: isDisabled ? 0.45 : pressed ? 0.7 : 1 }]}
    >
      <Icon size={17} color={colors.link} />
      <Text style={[styles.iconActionText, { color: colors.link }]}>{label}</Text>
    </Pressable>
  );
}

interface PrimaryButtonProps {
  readonly label: string;
  readonly icon?: LucideIcon;
  readonly onPress: () => void;
  readonly isOutline?: boolean;
  readonly isDisabled?: boolean;
}

/** The page's main button, in Edify blue (or outlined). */
export function PrimaryButton({ label, icon: Icon, onPress, isOutline, isDisabled }: PrimaryButtonProps) {
  const { colors } = useTheme();
  const ink = isOutline ? colors.primary : colors.primaryInk;
  return (
    <Pressable
      onPress={onPress}
      disabled={isDisabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => [
        styles.primary,
        isOutline ? { borderColor: colors.primary, borderWidth: 1.5 } : { backgroundColor: colors.primary },
        { opacity: isDisabled ? 0.5 : pressed ? 0.85 : 1 },
      ]}
    >
      {Icon ? <Icon size={18} color={ink} /> : null}
      <Text style={[styles.primaryText, { color: ink }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  hero: { paddingTop: 18, paddingHorizontal: 20, paddingBottom: 40, marginBottom: -24, gap: 4 },
  back: { alignSelf: 'flex-start', marginLeft: -6, marginBottom: 4, minHeight: 32, justifyContent: 'center' },
  heroEyebrow: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 1.4, color: 'rgba(215, 230, 239, 0.88)' },
  heroTitle: { fontFamily: fonts.bold, fontSize: 24, letterSpacing: -0.3, color: '#ffffff' },
  heroSubtitle: { fontFamily: fonts.medium, fontSize: 14, lineHeight: 20, color: 'rgba(255,255,255,0.9)' },
  sheet: { paddingHorizontal: 12, gap: 12, paddingBottom: 28 },
  counterGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  counter: { flexGrow: 1, flexBasis: '45%', minWidth: 140, flexDirection: 'row', gap: 10, alignItems: 'flex-start', borderWidth: 1.5, borderRadius: radius.md, padding: 12 },
  counterText: { flex: 1, gap: 1 },
  counterLabel: { fontFamily: fonts.semibold, fontSize: 13 },
  counterValue: { fontFamily: fonts.bold, fontSize: 24, fontVariant: ['tabular-nums'] },
  counterDetail: { fontFamily: fonts.medium, fontSize: 11 },
  segments: { flexDirection: 'row', borderRadius: radius.pill, padding: 4, gap: 4 },
  segment: { flex: 1, minHeight: 38, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 8 },
  segmentText: { fontFamily: fonts.semibold, fontSize: 13 },
  chip: { alignSelf: 'flex-start', borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 3 },
  chipText: { fontFamily: fonts.bold, fontSize: 12 },
  iconAction: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, paddingHorizontal: 4 },
  iconActionText: { fontFamily: fonts.semibold, fontSize: 13 },
  primary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, minHeight: 48, borderRadius: radius.md, paddingHorizontal: 16 },
  primaryText: { fontFamily: fonts.bold, fontSize: 15 },
});
