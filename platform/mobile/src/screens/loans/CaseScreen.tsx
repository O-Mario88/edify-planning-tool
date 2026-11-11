/**
 * One lender case, drawn from what the gateway returns: its sections (lines
 * and tables) and the actions this person may take now, each a small form.
 * Every rule — who may act, when, what is refused — lives in the gateway;
 * this page only draws and sends. Money is posted to the existing ledger by
 * the gateway, as the signed-in person.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import { ChevronDown, ChevronRight, MessageSquare, Paperclip } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ActionField, CaseAction, CaseSection, CaseView } from '../../gen/edify/loans/v1/lending_pb';
import { LendingService } from '../../gen/edify/loans/v1/lending_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { Select } from '../../ui/Select';
import { LoanProgressScreen } from './LoanProgressScreen';
import { LoanHero, LoanSheet, PrimaryButton, StatusChip } from './loanUi';

interface CaseScreenProps {
  readonly applicationId: string;
  readonly onBack: () => void;
}

/** Files the gateway accepts: PDF, JPEG or PNG up to 5 MB. */
const MAX_FILE_BYTES = 5 * 1024 * 1024;

export function CaseScreen({ applicationId, onBack }: CaseScreenProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [view, setView] = useState<CaseView | null>(null);
  const [open, setOpen] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [isNotifying, setIsNotifying] = useState(false);

  const load = useCallback(() => {
    api
      .call(LendingService.method.getCase, { applicationId })
      .then((answer) => setView(answer.view ?? null))
      .catch((cause: unknown) => setError(describe(cause)));
  }, [api, applicationId]);
  useEffect(load, [load]);

  if (isNotifying) {
    return <LoanProgressScreen applicationId={applicationId} initialPanel="notify" onBack={() => setIsNotifying(false)} />;
  }

  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <LoanHero eyebrow={view?.reference} title={view?.title ?? 'Case'} subtitle={view?.subtitle} onBack={onBack} />
      <LoanSheet>
        {view ? (
          <View style={styles.chips}>
            <StatusChip label={view.stageLabel} tone="brand" />
            {view.servicingLabel ? <StatusChip label={view.servicingLabel} tone="info" /> : null}
          </View>
        ) : null}
        {notice ? (
          <Text style={[styles.note, { color: colors.success }]} accessibilityLiveRegion="polite">
            {notice}
          </Text>
        ) : null}
        {error ? (
          <Text style={[styles.note, { color: colors.danger }]} accessibilityRole="alert">
            {error}
          </Text>
        ) : null}
        {!view && !error ? <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" /> : null}
        {view ? <PrimaryButton label="Send Notification" icon={MessageSquare} onPress={() => setIsNotifying(true)} /> : null}

        {view?.actions.length ? (
          <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
            <Text style={[styles.heading, { color: colors.text }]} accessibilityRole="header">
              What you can do now
            </Text>
            {view.actions.map((action) => (
              <ActionForm
                key={action.key}
                applicationId={applicationId}
                action={action}
                isOpen={open === action.key}
                onToggle={() => setOpen(open === action.key ? '' : action.key)}
                onDone={(message, next) => {
                  setOpen('');
                  setNotice(message);
                  setError('');
                  if (next) {
                    setView(next);
                  }
                }}
              />
            ))}
          </View>
        ) : null}

        {view?.sections.map((section) => (
          <SectionCard key={section.key} section={section} applicationId={applicationId} />
        ))}
      </LoanSheet>
    </ScrollView>
  );
}

function SectionCard({ section, applicationId }: { readonly section: CaseSection; readonly applicationId: string }) {
  const { colors } = useTheme();
  const { api } = useSession();
  const [note, setNote] = useState('');
  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <Text style={[styles.heading, { color: colors.text }]} accessibilityRole="header">
        {section.title}
      </Text>
      {section.note ? <Text style={[styles.note, { color: colors.textMuted }]}>{section.note}</Text> : null}
      {section.lines.map((line) => (
        <View key={line.label} style={[styles.line, { borderTopColor: colors.border }]}>
          <Text style={[styles.lineLabel, { color: colors.textMuted }]}>{line.label}</Text>
          <Text style={[styles.lineValue, { color: line.tone ? toneColors(colors, line.tone).fg : colors.text }]} selectable>
            {line.value || '—'}
          </Text>
        </View>
      ))}
      {section.table?.rows.map((row, index) => (
        <View key={`${section.key}-${index}`} style={[styles.row, { borderTopColor: colors.border, borderLeftColor: row.tone ? toneColors(colors, row.tone).fg : 'transparent' }]}>
          {row.cells.map((cell, at) =>
            cell ? (
              <Text key={at} style={[styles.cell, { color: at === 0 ? colors.text : colors.textMuted }]}>
                {at === 0 ? '' : `${section.table?.columns[at]}: `}
                {cell}
              </Text>
            ) : null,
          )}
          {row.documentId ? (
            <Pressable
              accessibilityRole="button"
              onPress={() =>
                api
                  .call(LendingService.method.getDocument, { applicationId, documentId: row.documentId })
                  .then((document) => setNote(`${document.fileName} (${Math.ceil(document.content.length / 1024)} KB) is on the case; open it on the web app.`))
                  .catch((cause: unknown) => setNote(describe(cause)))
              }
            >
              <Text style={[styles.cell, { color: colors.link }]}>Document</Text>
            </Pressable>
          ) : null}
        </View>
      ))}
      {note ? <Text style={[styles.note, { color: colors.textMuted }]}>{note}</Text> : null}
    </View>
  );
}

interface ActionFormProps {
  readonly applicationId: string;
  readonly action: CaseAction;
  readonly isOpen: boolean;
  readonly onToggle: () => void;
  readonly onDone: (message: string, view: CaseView | undefined) => void;
}

interface PickedFile {
  readonly name: string;
  readonly bytes: Uint8Array;
}

function ActionForm({ applicationId, action, isOpen, onToggle, onDone }: ActionFormProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(action.fields.map((field) => [field.key, field.value])),
  );
  const [file, setFile] = useState<PickedFile | null>(null);
  const [error, setError] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const set = (key: string) => (value: string) => setValues((current) => ({ ...current, [key]: value }));

  const pick = async () => {
    const result = await DocumentPicker.getDocumentAsync({ type: ['application/pdf', 'image/jpeg', 'image/png'], copyToCacheDirectory: true });
    if (result.canceled || !result.assets[0]) {
      return;
    }
    const asset = result.assets[0];
    const bytes = new Uint8Array(await (await fetch(asset.uri)).arrayBuffer());
    if (bytes.length > MAX_FILE_BYTES) {
      setError('Files must be 5 MB or smaller.');
      return;
    }
    setFile({ name: asset.name, bytes });
  };
  const run = () => {
    setIsBusy(true);
    setError('');
    api
      .call(LendingService.method.runCaseAction, {
        applicationId, action: action.key, values, file: file?.bytes ?? new Uint8Array(), fileName: file?.name ?? '',
      })
      .then((answer) => onDone(answer.message, answer.view))
      .catch((cause: unknown) => setError(describe(cause)))
      .finally(() => setIsBusy(false));
  };

  return (
    <View style={[styles.action, { borderTopColor: colors.border }]}>
      <Pressable onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded: isOpen }} style={styles.actionHead}>
        <Text style={[styles.actionLabel, { color: action.isDanger ? colors.danger : colors.link }]}>{action.label}</Text>
        {isOpen ? <ChevronDown size={18} color={colors.textMuted} /> : <ChevronRight size={18} color={colors.textMuted} />}
      </Pressable>
      {isOpen ? (
        <View style={styles.form}>
          {action.description ? <Text style={[styles.note, { color: colors.textMuted }]}>{action.description}</Text> : null}
          {action.fields.map((field) => (
            <FieldInput key={field.key} field={field} value={values[field.key] ?? ''} onChange={set(field.key)} file={file} onPick={pick} />
          ))}
          {error ? (
            <Text style={[styles.note, { color: colors.danger }]} accessibilityRole="alert">
              {error}
            </Text>
          ) : null}
          <PrimaryButton label={isBusy ? 'Working…' : action.label} onPress={run} isDisabled={isBusy} />
        </View>
      ) : null}
    </View>
  );
}

interface FieldInputProps {
  readonly field: ActionField;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly file: PickedFile | null;
  readonly onPick: () => void;
}

function FieldInput({ field, value, onChange, file, onPick }: FieldInputProps) {
  const { colors } = useTheme();
  const label = `${field.label}${field.required ? '' : ' (optional)'}`;
  const help = field.help ? <Text style={[styles.note, { color: colors.textSubtle }]}>{field.help}</Text> : null;
  switch (field.kind) {
    case 'choice':
      return (
        <View style={styles.field}>
          <Select label={label} value={value} placeholder={`Choose ${field.label.toLowerCase()}`} choices={field.choices} onChange={onChange} />
          {help}
        </View>
      );
    case 'date':
      return (
        <View style={styles.field}>
          <DateField label={label} value={value} onChange={onChange} isRequired={field.required} />
          {help}
        </View>
      );
    case 'check':
      return (
        <View style={[styles.field, styles.check]}>
          <Text style={[styles.fieldLabel, { color: colors.text, flex: 1 }]}>{field.label}</Text>
          <Switch value={value === 'true'} onValueChange={(on) => onChange(on ? 'true' : '')} accessibilityLabel={field.label} />
        </View>
      );
    case 'file':
      return (
        <View style={styles.field}>
          <Pressable onPress={onPick} accessibilityRole="button" style={[styles.file, { borderColor: colors.fieldBorder, backgroundColor: colors.surface }]}>
            <Paperclip size={16} color={colors.link} />
            <Text style={[styles.fieldLabel, { color: colors.link }]}>{file ? file.name : label}</Text>
          </Pressable>
          {help}
        </View>
      );
    default:
      return (
        <View style={styles.field}>
          <Text style={[styles.fieldLabel, { color: colors.text }]}>{label}</Text>
          <TextInput
            value={value}
            onChangeText={onChange}
            accessibilityLabel={field.label}
            multiline={field.kind === 'multiline' || field.kind === 'dates'}
            keyboardType={field.kind === 'money' || field.kind === 'number' ? 'number-pad' : field.kind === 'percent' ? 'decimal-pad' : 'default'}
            style={[styles.input, (field.kind === 'multiline' || field.kind === 'dates') && styles.multiline,
              { color: colors.text, borderColor: colors.fieldBorder, backgroundColor: colors.surface }]}
          />
          {help}
        </View>
      );
  }
}

const styles = StyleSheet.create({
  page: { paddingBottom: 32 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  note: { fontFamily: fonts.medium, fontSize: 12.5, lineHeight: 18 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 6 },
  heading: { fontFamily: fonts.bold, fontSize: 16 },
  line: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, paddingTop: 7, borderTopWidth: StyleSheet.hairlineWidth },
  lineLabel: { fontFamily: fonts.medium, fontSize: 13, maxWidth: '50%' },
  lineValue: { fontFamily: fonts.semibold, fontSize: 13, flex: 1, textAlign: 'right', fontVariant: ['tabular-nums'] },
  row: { gap: 2, paddingTop: 7, paddingLeft: 8, borderTopWidth: StyleSheet.hairlineWidth, borderLeftWidth: 3 },
  cell: { fontFamily: fonts.medium, fontSize: 12.5 },
  action: { borderTopWidth: StyleSheet.hairlineWidth },
  actionHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 46 },
  actionLabel: { fontFamily: fonts.bold, fontSize: 14, flex: 1 },
  form: { gap: 10, paddingBottom: 12 },
  field: { gap: 4 },
  fieldLabel: { fontFamily: fonts.semibold, fontSize: 13 },
  check: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  file: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderStyle: 'dashed', borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 44 },
  input: { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10, fontFamily: fonts.medium, fontSize: 15, minHeight: 44 },
  multiline: { minHeight: 80, textAlignVertical: 'top' },
});
