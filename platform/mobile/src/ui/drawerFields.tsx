/**
 * A drawer's parts, drawn natively: its notes, headings, figures and fields
 * — a select, a checklist, a tick box or a text input — as the web's drawers
 * draw them. Shared by the drawers and by the forms a page shows itself.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { KeyboardTypeOptions } from 'react-native';
import { Check } from 'lucide-react-native';

import type { DrawerItem } from '../gen/edify/screens/v1/drawer_pb';
import type { DrawerField } from '../gen/edify/screens/v1/form_pb';
import { fonts, radius, useTheme } from '../theme';
import { Checklist } from './Checklist';
import { DrawerHeading, DrawerInput, DrawerNote, DrawerText, FieldShell, partStyles as styles } from './drawerParts';
import { choicesFor, isShown } from './drawerLogic';
import type { Reloaded, Values } from './drawerLogic';
import { PageBlockView } from './page/PageBlocksView';
import { Select } from './Select';

interface ItemProps {
  readonly item: DrawerItem;
  readonly values: Values;
  readonly reloaded: Reloaded;
  readonly onChange: (field: DrawerField, value: string) => void;
}

export function DrawerItemView({ item, values, reloaded, onChange }: ItemProps) {
  const { colors } = useTheme();
  const kind = item.kind;
  switch (kind.case) {
    case 'note':
      return <DrawerNote tone={kind.value.tone} text={kind.value.text} />;
    case 'heading':
      return <DrawerHeading text={kind.value} />;
    case 'text':
      return <DrawerText text={kind.value} />;
    case 'lines':
      return (
        <View style={styles.lines}>
          {kind.value.facts.map((line) => (
            <View key={line.label} style={styles.line}>
              <Text style={[styles.lineLabel, { color: colors.text }]}>{line.label}</Text>
              <Text style={[styles.lineValue, { color: colors.text }]}>{line.value}</Text>
            </View>
          ))}
        </View>
      );
    case 'facts':
      return (
        <View style={styles.facts}>
          {kind.value.facts.map((fact) => (
            <View key={fact.label} style={styles.fact}>
              <Text style={[styles.factLabel, { color: colors.textMuted }]}>{fact.label}</Text>
              <Text style={[styles.factValue, { color: colors.text }]}>{fact.value}</Text>
            </View>
          ))}
        </View>
      );
    case 'block':
      return <PageBlockView block={kind.value} />;
    case 'field':
      return isShown(kind.value.showWhen, values) ? (
        <Field field={kind.value} values={values} reloaded={reloaded} onChange={onChange} />
      ) : null;
    default:
      return null;
  }
}

function keyboardOf(field: DrawerField): KeyboardTypeOptions {
  switch (field.kind) {
    case 'number':
      return field.step !== undefined && !Number.isInteger(field.step) ? 'decimal-pad' : 'number-pad';
    case 'tel':
      return 'phone-pad';
    case 'email':
      return 'email-address';
    case 'date':
      return 'numbers-and-punctuation';
    default:
      return 'default';
  }
}

interface FieldProps {
  readonly field: DrawerField;
  readonly values: Values;
  readonly reloaded: Reloaded;
  readonly onChange: (field: DrawerField, value: string) => void;
}

function Field({ field, values, reloaded, onChange }: FieldProps) {
  const { colors } = useTheme();
  const value = values[field.name] ?? '';
  if (field.kind === 'checklist') {
    return (
      <Checklist
        field={field}
        choices={choicesFor(field, values, reloaded)}
        value={value}
        isPicked={field.groupBy === '' || Boolean(values[field.groupBy])}
        onChange={(next) => onChange(field, next)}
      />
    );
  }
  let control;
  if (field.kind === 'radio') {
    control = <RadioChoice field={field} value={value} onChange={(next) => onChange(field, next)} />;
  } else if (field.kind === 'select') {
    const [first, ...rest] = choicesFor(field, values, reloaded);
    const hasEmpty = first !== undefined && first.value === '';
    const choices = (hasEmpty ? rest : [first, ...rest]).filter((choice) => choice !== undefined);
    control = (
      <Select
        label={field.label}
        value={value}
        placeholder={hasEmpty ? first.label : ''}
        hasEmptyChoice={hasEmpty}
        choices={choices.map((choice) => ({ value: choice.value, label: choice.label, disabled: choice.disabled }))}
        onChange={(next) => onChange(field, next)}
        isDisabled={field.readOnly || (field.groupBy !== '' && !values[field.groupBy])}
      />
    );
  } else if (field.kind === 'checkbox') {
    const isOn = value !== '';
    control = (
      <Pressable
        onPress={() => onChange(field, isOn ? '' : 'on')}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: isOn }}
        style={[styles.box, { borderColor: colors.borderStrong, backgroundColor: isOn ? colors.primary : 'transparent' }]}
      >
        {isOn ? <Check size={12} color={colors.primaryInk} /> : null}
      </Pressable>
    );
  } else {
    control = (
      <DrawerInput
        value={value}
        onChangeText={(next) => onChange(field, next)}
        isReadOnly={field.readOnly}
        hasError={field.error !== ''}
        multiline={field.kind === 'textarea'}
        keyboardType={keyboardOf(field)}
        maxLength={field.maxLength}
        placeholder={field.kind === 'date' ? 'YYYY-MM-DD' : field.placeholder}
        accessibilityLabel={field.label}
      />
    );
  }
  return (
    <FieldShell label={field.label} isRequired={field.required} help={field.help} error={field.error}>
      {control}
    </FieldShell>
  );
}

/** Radio buttons sharing a name, as the web draws them in a row: one pill
 * per choice, the chosen one filled. */
function RadioChoice({ field, value, onChange }: { readonly field: DrawerField; readonly value: string; readonly onChange: (value: string) => void }) {
  const { colors } = useTheme();
  return (
    <View style={radioStyles.row} accessibilityRole="radiogroup" accessibilityLabel={field.label}>
      {field.options.map((option) => {
        const isOn = option.value === value;
        return (
          <Pressable
            key={option.value}
            onPress={() => onChange(option.value)}
            disabled={option.disabled || field.readOnly}
            accessibilityRole="radio"
            accessibilityState={{ checked: isOn, disabled: option.disabled }}
            style={[
              radioStyles.pill,
              isOn
                ? { borderColor: colors.primary, backgroundColor: colors.primarySoft }
                : { borderColor: colors.outlineBorder, backgroundColor: colors.raised },
            ]}
          >
            <View style={[radioStyles.dot, { borderColor: isOn ? colors.primary : colors.borderStrong }]}>
              {isOn ? <View style={[radioStyles.dotFill, { backgroundColor: colors.primary }]} /> : null}
            </View>
            <Text style={[radioStyles.text, { color: isOn ? colors.link : colors.text }]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const radioStyles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 36, borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 12 },
  dot: { width: 14, height: 14, borderRadius: 7, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  dotFill: { width: 8, height: 8, borderRadius: 4 },
  text: { fontFamily: fonts.semibold, fontSize: 12 },
});
