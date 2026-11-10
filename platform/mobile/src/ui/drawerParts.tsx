/**
 * The parts every native drawer is drawn from, as the web's drawers draw
 * them (components/drawers/base_drawer.html and the field partials): notes,
 * labelled fields, inputs, read-only boxes, the footer buttons and the
 * "Discard your changes?" prompt. WebDrawer and PlanningDrawer share them so
 * the two look the same.
 */
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import type { TextInputProps } from 'react-native';

import { fonts, radius, toneColors, useTheme } from '../theme';

/** The web's discard button (rgb 225, 29, 72). */
const DISCARD_RED = '#e11d48';

const NOTE_TONES: Readonly<Record<string, string>> = {
  danger: 'alert',
  warning: 'caution',
  info: 'info',
  success: 'good',
};

interface DrawerNoteProps {
  readonly tone: string;
  readonly text: string;
  /** Drawn bold over the text (the web's .edify-note__title). */
  readonly title?: string;
  readonly children?: ReactNode;
}

export function DrawerNote({ tone, text, title, children }: DrawerNoteProps) {
  const { colors } = useTheme();
  const colour = toneColors(colors, NOTE_TONES[tone] ?? 'info');
  return (
    <View
      accessibilityRole={tone === 'danger' ? 'alert' : undefined}
      style={[styles.note, { backgroundColor: colour.soft }]}
    >
      {title ? <Text style={[styles.noteTitle, { color: colour.fg }]}>{title}</Text> : null}
      {text ? <Text style={[styles.noteText, { color: colour.fg }]}>{text}</Text> : null}
      {children}
    </View>
  );
}

export function DrawerHeading({ text }: { readonly text: string }) {
  const { colors } = useTheme();
  return (
    <Text style={[styles.heading, { color: colors.textMuted }]} accessibilityRole="header">
      {text}
    </Text>
  );
}

/** A helper line: muted, or in the warning or danger colour. */
export function DrawerText({ text, tone }: { readonly text: string; readonly tone?: 'warning' | 'danger' }) {
  const { colors } = useTheme();
  if (!text) {
    return null;
  }
  const colour = tone === 'danger' ? colors.danger : tone === 'warning' ? colors.warning : colors.textMuted;
  return (
    <Text
      accessibilityRole={tone === 'danger' ? 'alert' : undefined}
      style={[tone ? styles.help : styles.text, { color: colour }]}
    >
      {text}
    </Text>
  );
}

interface FieldShellProps {
  readonly label: string;
  readonly isRequired?: boolean;
  /** Shows the web's muted " (optional)". */
  readonly isOptional?: boolean;
  readonly help?: string;
  readonly error?: string;
  readonly children: ReactNode;
}

/** A field's label (with its * or "(optional)"), control, helper and error. */
export function FieldShell({ label, isRequired, isOptional, help, error, children }: FieldShellProps) {
  const { colors } = useTheme();
  return (
    <View style={styles.field}>
      {label ? (
        <Text style={[styles.label, { color: colors.text }]}>
          {label}
          {isRequired ? <Text style={{ color: colors.danger }}> *</Text> : null}
          {isOptional ? <Text style={[styles.optional, { color: colors.textMuted }]}> (optional)</Text> : null}
        </Text>
      ) : null}
      {children}
      {help ? <Text style={[styles.help, { color: colors.textMuted }]}>{help}</Text> : null}
      {error ? (
        <Text accessibilityRole="alert" style={[styles.help, { color: colors.danger }]}>
          {error}
        </Text>
      ) : null}
    </View>
  );
}

interface DrawerInputProps extends TextInputProps {
  readonly hasError?: boolean;
  readonly isReadOnly?: boolean;
}

export function DrawerInput({ hasError, isReadOnly, multiline, style, ...props }: DrawerInputProps) {
  const { colors } = useTheme();
  return (
    <TextInput
      {...props}
      multiline={multiline}
      editable={!isReadOnly}
      placeholderTextColor={colors.textSubtle}
      style={[
        styles.input,
        {
          borderColor: hasError ? colors.danger : colors.fieldBorder,
          color: colors.text,
          backgroundColor: isReadOnly ? colors.surfaceMuted : colors.surface,
        },
        multiline ? styles.textarea : null,
        style,
      ]}
    />
  );
}

/** The web's grey read-only box ("Data Gathering", the responsible person). */
export function ReadOnlyBox({ text, placeholder }: { readonly text: string; readonly placeholder?: string }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.readOnly, { borderColor: colors.fieldBorder, backgroundColor: colors.surfaceMuted }]}>
      <Text style={[styles.readOnlyText, { color: text ? colors.text : colors.textSubtle }]}>{text || placeholder}</Text>
    </View>
  );
}

interface DrawerButtonProps {
  readonly label: string;
  readonly onPress: () => void;
  readonly isPrimary?: boolean;
  readonly isBusy?: boolean;
  readonly isDisabled?: boolean;
}

export function DrawerButton({ label, onPress, isPrimary, isBusy, isDisabled }: DrawerButtonProps) {
  const { colors } = useTheme();
  const isOff = Boolean(isBusy || isDisabled);
  return (
    <Pressable
      onPress={onPress}
      disabled={isOff}
      accessibilityRole="button"
      accessibilityState={{ busy: isBusy, disabled: isDisabled }}
      style={[
        styles.button,
        isPrimary
          ? { backgroundColor: colors.primary, borderColor: colors.primary, opacity: isOff ? 0.5 : 1 }
          : { borderColor: colors.outlineBorder, backgroundColor: colors.raised },
      ]}
    >
      {isBusy ? (
        <ActivityIndicator color={colors.primaryInk} />
      ) : (
        <Text style={[styles.buttonText, { color: isPrimary ? colors.primaryInk : colors.link }]}>{label}</Text>
      )}
    </Pressable>
  );
}

/** The web's "Discard your changes?" panel (base_drawer.html). */
export function DiscardPrompt({ onKeep, onDiscard }: { readonly onKeep: () => void; readonly onDiscard: () => void }) {
  const { colors } = useTheme();
  return (
    <View style={[StyleSheet.absoluteFill, styles.discardShade]} accessibilityViewIsModal>
      <View style={[styles.discard, { backgroundColor: colors.raised, borderColor: colors.border }]} accessibilityRole="alert">
        <Text style={[styles.discardTitle, { color: colors.text }]}>Discard your changes?</Text>
        <Text style={[styles.text, { color: colors.textMuted }]}>
          What you have typed here has not been saved and will be lost.
        </Text>
        <View style={styles.discardActions}>
          <Pressable
            onPress={onKeep}
            accessibilityRole="button"
            style={[styles.button, { borderColor: colors.borderStrong, backgroundColor: colors.raised }]}
          >
            <Text style={[styles.buttonText, { color: colors.text }]}>Keep editing</Text>
          </Pressable>
          <Pressable
            onPress={onDiscard}
            accessibilityRole="button"
            style={[styles.button, { borderColor: DISCARD_RED, backgroundColor: DISCARD_RED }]}
          >
            <Text style={[styles.buttonText, { color: '#ffffff' }]}>Discard changes</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}

export const partStyles = StyleSheet.create({
  text: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 17 },
  lines: { gap: 4 },
  line: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  lineLabel: { flex: 1, fontFamily: fonts.regular, fontSize: 13 },
  lineValue: { fontFamily: fonts.semibold, fontSize: 13 },
  facts: { flexDirection: 'row', flexWrap: 'wrap', rowGap: 8 },
  fact: { width: '50%', gap: 2 },
  factLabel: { fontFamily: fonts.medium, fontSize: 12 },
  factValue: { fontFamily: fonts.semibold, fontSize: 13 },
  box: { width: 20, height: 20, borderWidth: 1, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
});

const styles = StyleSheet.create({
  button: { minHeight: 36, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12 },
  buttonText: { fontFamily: fonts.semibold, fontSize: 12 },
  note: { borderRadius: radius.sm, padding: 10, gap: 4 },
  noteTitle: { fontFamily: fonts.bold, fontSize: 13, lineHeight: 19 },
  noteText: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  heading: { fontFamily: fonts.semibold, fontSize: 12 },
  text: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 17 },
  field: { gap: 7 },
  label: { fontFamily: fonts.semibold, fontSize: 13 },
  optional: { fontFamily: fonts.regular, fontSize: 13 },
  input: { minHeight: 40, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, fontFamily: fonts.medium, fontSize: 16 },
  textarea: { minHeight: 66, paddingTop: 9, paddingBottom: 9, textAlignVertical: 'top' },
  help: { fontFamily: fonts.semibold, fontSize: 13, lineHeight: 16 },
  readOnly: { minHeight: 40, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 9, justifyContent: 'center' },
  readOnlyText: { fontFamily: fonts.semibold, fontSize: 14 },
  discardShade: { backgroundColor: 'rgba(28, 44, 68, 0.58)', justifyContent: 'center', padding: 20 },
  discard: { borderWidth: 1, borderRadius: 14, padding: 20, gap: 8 },
  discardTitle: { fontFamily: fonts.bold, fontSize: 15 },
  discardActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: 10, marginTop: 8 },
});
