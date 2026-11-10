/**
 * The parts every cluster operations screen is drawn with: the card, a
 * section title, a labelled field, a row of choices, and the badge that
 * names a school's mobilisation state or a plan's status in its colour.
 */
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { fonts, radius, toneColors, useTheme } from '../../theme';

/** What each state is called and how it is coloured (green done, blue planned, amber waiting, red refused). */
const STATES: Readonly<Record<string, { readonly label: string; readonly tone: string }>> = {
  not_invited: { label: 'Not invited', tone: 'plain' },
  invited: { label: 'Invited', tone: 'info' },
  acknowledged: { label: 'Acknowledged', tone: 'info' },
  confirmed: { label: 'Confirmed', tone: 'good' },
  declined: { label: 'Declined', tone: 'alert' },
  no_response: { label: 'No response', tone: 'caution' },
  attended: { label: 'Attended', tone: 'good' },
  absent: { label: 'Absent', tone: 'alert' },
  draft: { label: 'Draft', tone: 'plain' },
  submitted: { label: 'Awaiting review', tone: 'info' },
  returned: { label: 'Returned', tone: 'caution' },
  approved: { label: 'Approved', tone: 'good' },
  scheduled: { label: 'Scheduled', tone: 'good' },
  cancelled: { label: 'Cancelled', tone: 'plain' },
  open: { label: 'Open', tone: 'info' },
  done: { label: 'Done', tone: 'good' },
  answered: { label: 'Answered', tone: 'good' },
};

export function stateLabel(state: string): string {
  return STATES[state]?.label ?? state.replace(/_/g, ' ');
}

export function StateBadge({ state }: { readonly state: string }) {
  const { colors } = useTheme();
  const tone = toneColors(colors, STATES[state]?.tone ?? 'plain');
  return (
    <View style={[styles.badge, { backgroundColor: tone.soft }]}>
      <Text style={[styles.badgeText, { color: tone.fg }]}>{stateLabel(state)}</Text>
    </View>
  );
}

export function OpsCard({ children }: { readonly children: ReactNode }) {
  const { colors } = useTheme();
  return <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>{children}</View>;
}

export function OpsTitle({ eyebrow, title, copy }: { readonly eyebrow?: string; readonly title: string; readonly copy?: string }) {
  const { colors } = useTheme();
  return (
    <View style={styles.head}>
      {eyebrow ? <Text style={[styles.eyebrow, { color: colors.eyebrow }]}>{eyebrow.toUpperCase()}</Text> : null}
      <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
        {title}
      </Text>
      {copy ? <Text style={[styles.copy, { color: colors.textMuted }]}>{copy}</Text> : null}
    </View>
  );
}

export function SectionLabel({ children }: { readonly children: string }) {
  const { colors } = useTheme();
  return (
    <Text style={[styles.section, { color: colors.text }]} accessibilityRole="header">
      {children}
    </Text>
  );
}

export function Muted({ children }: { readonly children: ReactNode }) {
  const { colors } = useTheme();
  return <Text style={[styles.copy, { color: colors.textMuted }]}>{children}</Text>;
}

interface FieldProps {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly placeholder?: string;
  readonly isMultiline?: boolean;
  readonly isNumeric?: boolean;
  readonly isReadOnly?: boolean;
}

export function Field({ label, value, onChange, placeholder, isMultiline, isNumeric, isReadOnly }: FieldProps) {
  const { colors } = useTheme();
  return (
    <View style={styles.field}>
      <Text style={[styles.label, { color: colors.text }]}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={colors.textSubtle}
        accessibilityLabel={label}
        editable={!isReadOnly}
        multiline={isMultiline}
        keyboardType={isNumeric ? 'number-pad' : 'default'}
        style={[
          styles.input,
          isMultiline && styles.multiline,
          { color: colors.text, borderColor: colors.fieldBorder, backgroundColor: isReadOnly ? colors.surfaceMuted : colors.surface },
        ]}
      />
    </View>
  );
}

interface ChoiceRowProps {
  readonly label: string;
  readonly value: string;
  readonly choices: readonly { readonly value: string; readonly label: string }[];
  readonly onChange: (value: string) => void;
}

/** A short set of options as pressable chips that wrap (a meeting kind, a channel). */
export function ChoiceRow({ label, value, choices, onChange }: ChoiceRowProps) {
  const { colors } = useTheme();
  return (
    <View style={styles.field}>
      <Text style={[styles.label, { color: colors.text }]}>{label}</Text>
      <View style={styles.chips} accessibilityRole="radiogroup" accessibilityLabel={label}>
        {choices.map((choice) => {
          const isOn = choice.value === value;
          return (
            <Pressable
              key={choice.value}
              onPress={() => onChange(choice.value)}
              accessibilityRole="radio"
              accessibilityState={{ checked: isOn }}
              style={[styles.chip, { backgroundColor: isOn ? colors.primary : colors.surface, borderColor: isOn ? colors.primary : colors.border }]}
            >
              <Text style={[styles.chipText, { color: isOn ? colors.primaryInk : colors.text }]}>{choice.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

/** A message after an action, or the gateway's refusal, in its colour. */
export function Notice({ text, isError }: { readonly text: string; readonly isError?: boolean }) {
  const { colors } = useTheme();
  if (!text) {
    return null;
  }
  return (
    <Text
      accessibilityRole={isError ? 'alert' : undefined}
      accessibilityLiveRegion="polite"
      style={[styles.notice, { color: isError ? colors.danger : colors.success }]}
    >
      {text}
    </Text>
  );
}

export const opsStyles = StyleSheet.create({
  page: { padding: 12, gap: 10, paddingBottom: 40 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  spread: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  grow: { flex: 1, gap: 2 },
  name: { fontFamily: fonts.semibold, fontSize: 15 },
  meta: { fontFamily: fonts.medium, fontSize: 12 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  small: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6 },
  smallText: { fontFamily: fonts.semibold, fontSize: 12 },
});

const styles = StyleSheet.create({
  head: { gap: 6, marginBottom: 2 },
  eyebrow: { fontFamily: fonts.bold, fontSize: 11, letterSpacing: 1.2 },
  title: { fontFamily: fonts.bold, fontSize: 22, letterSpacing: -0.2 },
  copy: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  section: { fontFamily: fonts.bold, fontSize: 16, marginTop: 6 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 8 },
  badge: { alignSelf: 'flex-start', borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 3 },
  badgeText: { fontFamily: fonts.semibold, fontSize: 11 },
  field: { gap: 6 },
  label: { fontFamily: fonts.semibold, fontSize: 13 },
  input: { minHeight: 44, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10, fontFamily: fonts.medium, fontSize: 16 },
  multiline: { minHeight: 96, textAlignVertical: 'top' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 14, paddingVertical: 8 },
  chipText: { fontFamily: fonts.semibold, fontSize: 13 },
  notice: { fontFamily: fonts.semibold, fontSize: 13 },
});
