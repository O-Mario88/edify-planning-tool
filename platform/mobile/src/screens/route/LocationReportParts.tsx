/**
 * Verify Location in the app (Smart Route brief, parts 2 and 11): the form
 * that reports a school's location as wrong or missing, what a report says,
 * and a reviewer's Approve / Reject. Nothing changes on the map until
 * someone other than the reporter approves; the School Directory's own
 * coordinates are never changed. The phone's location is asked for only
 * when the person presses Use my location, once, in the foreground.
 */
import * as Location from 'expo-location';
import { useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Check, Crosshair } from 'lucide-react-native';

import { ApiError } from '../../api/connect';
import { useSession } from '../../auth/SessionContext';
import { RoutePlannerService } from '../../gen/edify/routes/v1/routes_pb';
import type { LocationReport, SchoolPin } from '../../gen/edify/routes/v1/routes_pb';
import { fonts, radius, spacing, useTheme } from '../../theme';
import { DEVICE_ACCURACY_MAX_M, LOCATE_TIMEOUT_MS, kindFor, movedText, parsePoint, pointText, reportKey, reportedText, sourceText } from './locationReport';
import type { ReportKind, TypedPoint } from './locationReport';
import { PIN_TONES } from './routeData';

const BLUE = PIN_TONES.planned;

interface DeviceFix extends TypedPoint {
  readonly accuracy: number;
}

/** One reading of the phone's location, asked for now and never kept. */
async function locate(): Promise<DeviceFix> {
  const permission = await Location.requestForegroundPermissionsAsync();
  if (!permission.granted) throw new Error('Location permission was not given. Type the point instead, or allow location for Edify in Settings.');
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error('Your location could not be found. Move into the open and try again, or type the point.')), LOCATE_TIMEOUT_MS);
  });
  try {
    const fix = await Promise.race([Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Highest }), timeout]);
    return { lat: fix.coords.latitude, lng: fix.coords.longitude, accuracy: fix.coords.accuracy ?? Number.POSITIVE_INFINITY };
  } finally {
    clearTimeout(timer);
  }
}

const messageOf = (cause: unknown, fallback: string) => (cause instanceof ApiError || cause instanceof Error ? cause.message : fallback);

interface FieldProps {
  readonly label: string;
  readonly value: string;
  readonly onChange: (next: string) => void;
  readonly placeholder?: string;
  readonly keyboard?: 'default' | 'numbers-and-punctuation';
  readonly multiline?: boolean;
  readonly maxLength: number;
}

function Field({ label, value, onChange, placeholder, keyboard = 'default', multiline = false, maxLength }: FieldProps) {
  const { colors } = useTheme();
  return (
    <View style={styles.field}>
      <Text style={[styles.fieldLabel, { color: colors.text }]}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={colors.textSubtle}
        keyboardType={keyboard}
        multiline={multiline}
        maxLength={maxLength}
        style={[styles.input, multiline && styles.multiline, { color: colors.text, borderColor: colors.border, backgroundColor: colors.card }]}
      />
    </View>
  );
}

function Problem({ text }: { readonly text: string }) {
  const { colors } = useTheme();
  if (!text) return null;
  return (
    <Text style={[styles.problem, { color: colors.danger, backgroundColor: colors.dangerSoft }]} accessibilityRole="alert" accessibilityLiveRegion="polite">
      {text}
    </Text>
  );
}

export interface ReportFormProps {
  readonly school: SchoolPin;
  readonly onFiled: (report: LocationReport) => void;
  readonly onCancel: () => void;
}

/** Report Location: what is wrong, the right point (typed or this phone's), directions and a note. */
export function ReportForm({ school, onFiled, onCancel }: ReportFormProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [kind, setKind] = useState<ReportKind>(() => kindFor(school.locationStatus));
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [fix, setFix] = useState<DeviceFix | null>(null);
  const [access, setAccess] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [isLocating, setIsLocating] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const key = useRef(reportKey());
  const fromDevice = fix !== null && lat === fix.lat.toFixed(6) && lng === fix.lng.toFixed(6);

  const useDevice = async () => {
    setError('');
    setIsLocating(true);
    try {
      const got = await locate();
      if (got.accuracy > DEVICE_ACCURACY_MAX_M) {
        setError(`Your location is only accurate to ${Math.round(got.accuracy)} m. Move into the open and try again, or type the point.`);
        return;
      }
      setFix(got);
      setLat(got.lat.toFixed(6));
      setLng(got.lng.toFixed(6));
    } catch (cause) {
      setError(messageOf(cause, 'Your location could not be found.'));
    } finally {
      setIsLocating(false);
    }
  };

  const send = async () => {
    setError('');
    if (!note.trim()) {
      setError('Say what is wrong with the location.');
      return;
    }
    let proposed: TypedPoint | undefined;
    if (lat.trim() !== '' || lng.trim() !== '') {
      const parsed = parsePoint(lat, lng);
      if (typeof parsed === 'string') {
        setError(parsed);
        return;
      }
      proposed = parsed;
    } else if (kind === 'missing') {
      setError("Give the school's location: type it or use your location.");
      return;
    }
    const device = fromDevice && proposed ? fix : null;
    const point = device ?? proposed;
    setIsSending(true);
    try {
      const answer = await api.call(RoutePlannerService.method.reportSchoolLocation, {
        schoolId: school.schoolId,
        kind,
        proposed: point ? { lat: point.lat, lng: point.lng } : undefined,
        pointSource: device ? 'device' : point ? 'typed' : 'none',
        accuracyM: device ? device.accuracy : 0,
        accessNote: access,
        note,
        idempotencyKey: key.current,
      });
      if (answer.report) onFiled(answer.report);
    } catch (cause) {
      setError(messageOf(cause, 'The report could not be sent. Please try again.'));
    } finally {
      setIsSending(false);
    }
  };

  return (
    <View style={[styles.form, { borderColor: colors.border }]} accessibilityLabel="Report location">
      <Text style={[styles.fieldLabel, { color: colors.text }]}>What is wrong?</Text>
      <View style={styles.choices} accessibilityRole="radiogroup">
        {(['wrong', 'missing'] as const).map((k) => (
          <Pressable
            key={k}
            onPress={() => setKind(k)}
            accessibilityRole="radio"
            accessibilityState={{ checked: kind === k }}
            style={[styles.choice, { borderColor: kind === k ? BLUE : colors.border, backgroundColor: kind === k ? '#e8f1fd' : colors.card }]}
          >
            <Text style={[styles.choiceText, { color: kind === k ? '#0b4a9e' : colors.text }]}>{k === 'wrong' ? 'Location is wrong' : 'No location'}</Text>
          </Pressable>
        ))}
      </View>
      <View style={styles.pair}>
        <View style={styles.half}>
          <Field label="Latitude" value={lat} onChange={setLat} placeholder="0.347600" keyboard="numbers-and-punctuation" maxLength={20} />
        </View>
        <View style={styles.half}>
          <Field label="Longitude" value={lng} onChange={setLng} placeholder="32.582500" keyboard="numbers-and-punctuation" maxLength={20} />
        </View>
      </View>
      <Pressable onPress={useDevice} disabled={isLocating} style={[styles.outline, isLocating && styles.dim]} accessibilityRole="button" accessibilityLabel="Use my location">
        {isLocating ? <ActivityIndicator color={BLUE} /> : <Crosshair size={18} color={BLUE} />}
        <Text style={styles.outlineText}>{isLocating ? 'Finding you…' : 'Use my location'}</Text>
      </Pressable>
      <Text style={[styles.hint, { color: colors.textMuted }]}>
        {fromDevice && fix
          ? `From this phone, accurate to ${Math.round(fix.accuracy)} m. Only use it while you are at the school.`
          : 'Type the point, or press Use my location while you are at the school. Your location is read once and never tracked.'}
      </Text>
      <Field label="Directions to the school (optional)" value={access} onChange={setAccess} placeholder="Turn left at the trading centre" maxLength={300} />
      <Field label="What is wrong with the location?" value={note} onChange={setNote} multiline maxLength={1000} />
      <Problem text={error} />
      <View style={styles.buttons}>
        <Pressable onPress={send} disabled={isSending} style={[styles.primary, isSending && styles.dim]} accessibilityRole="button">
          <Text style={styles.primaryText}>{isSending ? 'Sending…' : 'Send for review'}</Text>
        </Pressable>
        <Pressable onPress={onCancel} style={styles.plain} accessibilityRole="button">
          <Text style={[styles.plainText, { color: colors.textMuted }]}>Cancel</Text>
        </Pressable>
      </View>
    </View>
  );
}

function Line({ label, value }: { readonly label: string; readonly value: string }) {
  const { colors } = useTheme();
  return (
    <View>
      <Text style={[styles.label, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.value, { color: colors.text }]}>{value}</Text>
    </View>
  );
}

/** What a report says, for the profile and the review list. */
export function ReportDetails({ report }: { readonly report: LocationReport }) {
  return (
    <View style={styles.details}>
      <Line label="Reported" value={`${report.kind === 'missing' ? 'No location' : 'Wrong location'} · ${reportedText(report)}`} />
      <Line label="Proposed point" value={pointText(report.proposed)} />
      <Line label="Source" value={sourceText(report)} />
      <Line label="Change" value={movedText(report)} />
      <Line label="Note" value={report.note} />
      {report.accessNote ? <Line label="Directions" value={report.accessNote} /> : null}
      {report.status !== 'pending' ? (
        <Line label={report.status === 'approved' ? 'Approved by' : 'Rejected by'} value={`${report.reviewedByName}${report.reviewNote ? ` · ${report.reviewNote}` : ''}`} />
      ) : null}
    </View>
  );
}

export interface ReviewControlsProps {
  readonly report: LocationReport;
  readonly onDecided: (report: LocationReport) => void;
}

/** Approve (the point becomes the verified location) or Reject with a reason. */
export function ReviewControls({ report, onDecided }: ReviewControlsProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [isSending, setIsSending] = useState(false);
  if (report.isOwn) {
    return <Text style={[styles.hint, { color: colors.textMuted }]}>You reported this, so someone else reviews it.</Text>;
  }
  const decide = async (decision: 'approve' | 'reject') => {
    setError('');
    if (decision === 'reject' && !note.trim()) {
      setError('Say why the report is rejected.');
      return;
    }
    setIsSending(true);
    try {
      const answer = await api.call(RoutePlannerService.method.reviewLocationReport, { reportId: report.id, decision, note });
      if (answer.report) onDecided(answer.report);
    } catch (cause) {
      setError(messageOf(cause, 'The review could not be saved. Please try again.'));
    } finally {
      setIsSending(false);
    }
  };
  return (
    <View style={styles.review}>
      <Field label="Review note (needed to reject)" value={note} onChange={setNote} maxLength={1000} />
      <Problem text={error} />
      <View style={styles.buttons}>
        <Pressable
          onPress={() => decide('approve')}
          disabled={isSending || !report.proposed}
          style={[styles.primary, (isSending || !report.proposed) && styles.dim]}
          accessibilityRole="button"
        >
          <Check size={18} color="#fff" />
          <Text style={styles.primaryText}>Approve location</Text>
        </Pressable>
        <Pressable onPress={() => decide('reject')} disabled={isSending} style={[styles.outline, isSending && styles.dim]} accessibilityRole="button">
          <Text style={styles.outlineText}>Reject</Text>
        </Pressable>
      </View>
      {!report.proposed ? <Text style={[styles.hint, { color: colors.textMuted }]}>There is no point to approve; reject it with a note.</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  form: { borderWidth: 1, borderRadius: radius.sm, padding: spacing.sm, gap: spacing.sm, marginTop: spacing.sm },
  field: { gap: 4 },
  fieldLabel: { fontFamily: fonts.semibold, fontSize: 14 },
  input: { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 44, fontFamily: fonts.regular, fontSize: 15 },
  multiline: { minHeight: 88, paddingTop: 10, textAlignVertical: 'top' },
  choices: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  choice: { borderWidth: 1.5, borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 44, justifyContent: 'center' },
  choiceText: { fontFamily: fonts.semibold, fontSize: 14 },
  pair: { flexDirection: 'row', gap: spacing.sm },
  half: { flex: 1 },
  hint: { fontFamily: fonts.regular, fontSize: 13 },
  problem: { fontFamily: fonts.medium, fontSize: 14, borderRadius: radius.sm, padding: spacing.sm },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, alignItems: 'center' },
  primary: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: BLUE, borderRadius: radius.sm, paddingHorizontal: 14, minHeight: 44 },
  primaryText: { fontFamily: fonts.semibold, fontSize: 15, color: '#fff' },
  outline: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: 8, borderWidth: 1.5, borderColor: BLUE, borderRadius: radius.sm, paddingHorizontal: 14, minHeight: 44 },
  outlineText: { fontFamily: fonts.semibold, fontSize: 15, color: BLUE },
  plain: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 8 },
  plainText: { fontFamily: fonts.semibold, fontSize: 15 },
  dim: { opacity: 0.6 },
  details: { gap: 6 },
  label: { fontFamily: fonts.regular, fontSize: 13 },
  value: { fontFamily: fonts.medium, fontSize: 14 },
  review: { gap: spacing.sm, marginTop: spacing.sm },
});
