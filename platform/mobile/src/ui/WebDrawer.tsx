/**
 * One of the web's drawers, drawn natively: read from the drawer the web
 * renders for the same person and saved by the web view that saves it
 * (apps.mobile_feed SchoolDrawerFeedView). Its parts are the drawer's own —
 * notes, headings, figures and fields, in order — and what its script does
 * (a field shown for one choice, a list another field reloads, a list tied
 * to another field's choice) follows drawerLogic. A refused save comes back
 * as the drawer again, the web's errors in it.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, Text, View } from 'react-native';
import type { KeyboardTypeOptions } from 'react-native';
import { Check } from 'lucide-react-native';

import { ApiError } from '../api/connect';
import { describe, useSession } from '../auth/SessionContext';
import type { DrawerField, DrawerItem, PageDrawer } from '../gen/edify/screens/v1/drawer_pb';
import { useTheme } from '../theme';
import { Drawer } from './Drawer';
import {
  DiscardPrompt,
  DrawerButton,
  DrawerHeading,
  DrawerInput,
  DrawerNote,
  DrawerText,
  FieldShell,
  partStyles as styles,
} from './drawerParts';
import { Select } from './Select';
import { PageBlockView } from './page/PageBlocksView';
import { Checklist } from './Checklist';
import { choicesFor, clearedBy, initialValues, isShown, missingField, valuesToSend } from './drawerLogic';
import type { Reloaded, Values } from './drawerLogic';

/** Which drawer: one of a school's (edit, close, ssa-entry), or any drawer a
 * page opens, by its web path. */
export type DrawerSource = { readonly schoolId: string; readonly kind: string } | { readonly path: string };

interface WebDrawerProps {
  readonly source: DrawerSource;
  readonly onClose: () => void;
  /** Saved: the web's confirmation, and where the web went next (or ''). */
  readonly onSaved: (message: string, redirect: string) => void;
  /** The feed does not draw this drawer: its opener takes it elsewhere. */
  readonly onUnavailable?: () => void;
}

export function WebDrawer({ source, onClose, onSaved, onUnavailable }: WebDrawerProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [drawer, setDrawer] = useState<PageDrawer | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [reloaded, setReloaded] = useState<Reloaded>({});
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [refusals, setRefusals] = useState(0);

  /** As the web's drawer: closing with typed changes asks first. */
  function requestClose() {
    if (isDirty) {
      setIsAsking(true);
      return;
    }
    onClose();
  }

  const sourceKey = 'path' in source ? source.path : `${source.schoolId}/${source.kind}`;
  useEffect(() => {
    const loading =
      'path' in source
        ? api.getDrawer(source.path).then((answer) => {
            if (!answer.drawer) {
              throw new Error(answer.refusal || 'This drawer could not be loaded. Please try again.');
            }
            return answer.drawer;
          })
        : api.getSchoolDrawer(source.schoolId, source.kind);
    loading
      .then((answer) => {
        setDrawer(answer);
        setValues(initialValues(answer));
      })
      .catch((cause: unknown) => {
        if (onUnavailable && cause instanceof ApiError && cause.code === 'not_found') {
          onUnavailable();
          return;
        }
        setError(describe(cause));
      });
    // The source is named by its key; a new object for the same drawer does not reload it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, sourceKey]);

  function change(field: DrawerField, value: string) {
    if (!drawer) {
      return;
    }
    setIsDirty(true);
    const cleared = clearedBy(drawer, field.name);
    setValues((current) => ({
      ...current,
      [field.name]: value,
      ...Object.fromEntries(cleared.map((name) => [name, ''])),
    }));
    if (field.reloadsPath && field.reloadsTarget) {
      const target = field.reloadsTarget;
      api
        .getDrawerOptions({ source: field.reloadsPath, name: field.name, value })
        .then((options) => setReloaded((current) => ({ ...current, [target]: options })))
        .catch((cause: unknown) => setError(describe(cause)));
    }
  }

  async function save() {
    if (!drawer) {
      return;
    }
    // As the browser does, a required field left empty stops the save here.
    const missing = missingField(drawer, values);
    if (missing) {
      setError(`${missing} is required.`);
      setRefusals((count) => count + 1);
      return;
    }
    setIsBusy(true);
    setError('');
    try {
      const sent = valuesToSend(drawer, values);
      const answer =
        'path' in source ? await api.saveDrawer(source.path, sent) : await api.saveSchoolDrawer(source.schoolId, source.kind, sent);
      if (answer.saved) {
        onSaved(answer.message, answer.redirect);
        return;
      }
      if (answer.drawer) {
        setDrawer(answer.drawer);
        setValues({ ...initialValues(answer.drawer), ...values });
      }
      setError(answer.error);
      setRefusals((count) => count + 1);
    } catch (cause) {
      setError(describe(cause));
      setRefusals((count) => count + 1);
    } finally {
      setIsBusy(false);
    }
  }

  const footer = drawer ? (
    <>
      <DrawerButton label={drawer.cancelLabel || 'Cancel'} onPress={requestClose} />
      {drawer.canSubmit ? (
        <DrawerButton label={drawer.submitLabel} onPress={() => void save()} isPrimary isBusy={isBusy} />
      ) : null}
    </>
  ) : undefined;

  return (
    <Drawer
      title={drawer?.title ?? ''}
      subtitle={drawer?.subtitle}
      onClose={requestClose}
      hasRequired={drawer?.hasRequired}
      footer={footer}
      topKey={refusals}
      overlay={isAsking ? <DiscardPrompt onKeep={() => setIsAsking(false)} onDiscard={onClose} /> : undefined}
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      {drawer ? (
        drawer.items.map((item, index) =>
          isShown(item.showWhen, values) ? (
            <Item key={`${item.kind.case}-${index}`} item={item} values={values} reloaded={reloaded} onChange={change} />
          ) : null,
        )
      ) : error ? null : (
        <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />
      )}
    </Drawer>
  );
}

interface ItemProps {
  readonly item: DrawerItem;
  readonly values: Values;
  readonly reloaded: Reloaded;
  readonly onChange: (field: DrawerField, value: string) => void;
}

function Item({ item, values, reloaded, onChange }: ItemProps) {
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
  if (field.kind === 'select') {
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
