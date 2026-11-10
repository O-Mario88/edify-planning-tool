/**
 * A list of tick boxes in a drawer, as the web draws it
 * (partials/clusters/create_cluster_drawer.html and its kin): a Select all
 * line, then a bordered list of boxes — each with its words and the line
 * under them — scrolling once it is long, and the label counting what is
 * ticked. A list tied to another field (a district's sub-counties) asks for
 * that field first, as the web's list does.
 */
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Check, Minus } from 'lucide-react-native';

import type { DrawerField, DrawerOption } from '../gen/edify/screens/v1/form_pb';
import { fonts, radius, useTheme } from '../theme';
import { FieldShell } from './drawerParts';
import { ticked, withTicked } from './drawerLogic';

/** The web's list stops growing at about six lines (max-h-48) and scrolls. */
const LIST_HEIGHT = 240;

interface ChecklistProps {
  readonly field: DrawerField;
  /** The choices that apply now (those of the chosen district). */
  readonly choices: readonly DrawerOption[];
  readonly value: string;
  /** Whether the field this list is tied to has been chosen. */
  readonly isPicked: boolean;
  readonly onChange: (value: string) => void;
}

export function Checklist({ field, choices, value, isPicked, onChange }: ChecklistProps) {
  const { colors } = useTheme();
  const chosen = new Set(ticked(value));
  const open = choices.filter((choice) => !choice.disabled).map((choice) => choice.value);
  const tickedHere = open.filter((choice) => chosen.has(choice)).length;
  const isAll = open.length > 0 && tickedHere === open.length;
  const label = field.label ? `${field.label} (${chosen.size} selected)` : '';
  let body;
  if (!isPicked) {
    body = <Empty text={`Choose the ${pickerName(field.groupBy)} to see its choices.`} />;
  } else if (choices.length === 0) {
    body = <Empty text="There is nothing to choose here yet." />;
  } else {
    body = (
      <ScrollView style={styles.scroll} nestedScrollEnabled keyboardShouldPersistTaps="handled">
        {choices.map((choice, index) => (
          <Row
            key={choice.value}
            choice={choice}
            isOn={chosen.has(choice.value)}
            isFirst={index === 0}
            onPress={() => onChange(withTicked(value, choices, [choice.value], !chosen.has(choice.value)))}
          />
        ))}
      </ScrollView>
    );
  }
  return (
    <FieldShell label={label} isRequired={field.required} help={field.help} error={field.error}>
      {isPicked && open.length > 1 ? (
        <Pressable
          onPress={() => onChange(withTicked(value, choices, open, !isAll))}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: isAll ? true : tickedHere > 0 ? 'mixed' : false }}
          accessibilityLabel={`Select all ${field.label}`}
          hitSlop={6}
          style={styles.all}
        >
          <Box isOn={isAll} isPart={!isAll && tickedHere > 0} />
          <Text style={[styles.allText, { color: colors.textMuted }]}>Select all</Text>
        </Pressable>
      ) : null}
      <View
        style={[styles.list, { borderColor: field.error ? colors.danger : colors.border, backgroundColor: colors.raised }]}
        accessibilityRole="list"
        accessibilityLabel={field.label}
      >
        {body}
      </View>
    </FieldShell>
  );
}

interface RowProps {
  readonly choice: DrawerOption;
  readonly isOn: boolean;
  readonly isFirst: boolean;
  readonly onPress: () => void;
}

function Row({ choice, isOn, isFirst, onPress }: RowProps) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      disabled={choice.disabled}
      accessibilityRole="checkbox"
      accessibilityState={{ checked: isOn, disabled: choice.disabled }}
      accessibilityLabel={choice.detail ? `${choice.label}, ${choice.detail}` : choice.label}
      style={({ pressed }) => [
        styles.row,
        !isFirst && { borderTopWidth: 1, borderTopColor: colors.raisedBorder },
        pressed && { backgroundColor: colors.surfaceMuted },
        choice.disabled && { opacity: 0.5 },
      ]}
    >
      <Box isOn={isOn} />
      <View style={styles.words}>
        <Text style={[styles.label, { color: colors.text }]}>{choice.label}</Text>
        {choice.detail ? <Text style={[styles.detail, { color: colors.textMuted }]}>{choice.detail}</Text> : null}
      </View>
    </Pressable>
  );
}

function Box({ isOn, isPart = false }: { readonly isOn: boolean; readonly isPart?: boolean }) {
  const { colors } = useTheme();
  const isFilled = isOn || isPart;
  return (
    <View
      style={[
        styles.box,
        { borderColor: isFilled ? colors.primary : colors.borderStrong, backgroundColor: isFilled ? colors.primary : colors.raised },
      ]}
    >
      {isOn ? <Check size={12} color={colors.primaryInk} /> : isPart ? <Minus size={12} color={colors.primaryInk} /> : null}
    </View>
  );
}

function Empty({ text }: { readonly text: string }) {
  const { colors } = useTheme();
  return <Text style={[styles.empty, { color: colors.textMuted }]}>{text}</Text>;
}

/** "district_id" → "district". */
function pickerName(groupBy: string): string {
  return groupBy.replace(/_id$/, '').replace(/_/g, ' ') || 'field above';
}

const styles = StyleSheet.create({
  all: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start' },
  allText: { fontFamily: fonts.semibold, fontSize: 12 },
  list: { borderWidth: 1, borderRadius: radius.md, overflow: 'hidden' },
  scroll: { maxHeight: LIST_HEIGHT },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 10, minHeight: 44 },
  words: { flex: 1, gap: 2 },
  label: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 16 },
  detail: { fontFamily: fonts.medium, fontSize: 11, lineHeight: 15 },
  box: { width: 16, height: 16, borderWidth: 1, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  empty: { fontFamily: fonts.medium, fontSize: 12, textAlign: 'center', padding: 16 },
});
