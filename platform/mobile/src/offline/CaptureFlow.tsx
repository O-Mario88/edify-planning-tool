/**
 * Capture School Location / Verify / Replace Location (offline capture
 * brief, 2026-11-14, parts 2, 3 and 12). Open School → Capture GPS →
 * Confirm → Saved Offline / Synced; a correction adds its reason. Large
 * buttons, short words, the accuracy in plain sight, easy retry, and never
 * a word suggesting the server has the change when only the phone does.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Check, Crosshair, MapPin, RefreshCw, X } from 'lucide-react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { RouteMapView } from '../screens/route/RouteMapView';
import type { MapScene } from '../screens/route/routeMapHtml';
import { fonts, radius, spacing, useTheme } from '../theme';
import { captureGps, prepareGps, PROBLEM_TEXT } from './gps';
import type { GpsCapture, GpsProblem } from './gps';
import { BAND_TEXT, bandOf, metersBetween, summarize } from './gpsMath';
import type { GpsFix, GpsSample } from './gpsMath';
import { useOffline } from './OfflineContext';
import { STATUS_TEXT } from './queueLogic';
import type { CachedSchool, CaptureKind, CaptureTarget, QueuedCapture } from './store';

const BLUE = '#1d6fe0';
const BAND_COLOR = { good: '#15803d', confirm: '#b45309', recapture: '#b91c1c' } as const;

export const REASONS = ['The pin is in the wrong place', 'The school has moved', 'The pin is on the road, not the school', 'Other'] as const;

type Step =
  | { name: 'start' }
  | { name: 'capturing'; samples: number; best: number | null }
  | { name: 'problem'; problem: GpsProblem }
  | { name: 'result'; fix: GpsFix }
  | { name: 'saving' }
  | { name: 'saved'; capture: QueuedCapture };

export interface CaptureFlowProps {
  readonly school: CachedSchool;
  /** school (its own location) or entrance (road access). */
  readonly target: CaptureTarget;
  readonly onClose: (saved: QueuedCapture | null) => void;
}

/** Whether a capture of this target is a first location or a correction. */
export function kindFor(school: CachedSchool, target: CaptureTarget): CaptureKind {
  const has = target === 'entrance' ? school.entranceLat !== null : school.lat !== null;
  return has ? 'correction' : 'new';
}

export function CaptureFlow({ school, target, onClose }: CaptureFlowProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { policy, saveCapture, isSignedIn } = useOffline();
  const kind = kindFor(school, target);
  const [step, setStep] = useState<Step>({ name: 'start' });
  const [reason, setReason] = useState('');
  const [other, setOther] = useState('');
  const [access, setAccess] = useState(target === 'school' ? '' : school.accessNote);
  const [confirmedAtSchool, setConfirmedAtSchool] = useState(false);
  const [error, setError] = useState('');
  const gps = useRef<GpsCapture | null>(null);

  // Leaving the screen stops the readings.
  useEffect(() => () => gps.current?.stop(), []);

  const start = async () => {
    setError('');
    const problem = await prepareGps();
    if (problem) {
      setStep({ name: 'problem', problem });
      return;
    }
    setStep({ name: 'capturing', samples: 0, best: null });
    const run = captureGps(policy, (samples: readonly GpsSample[], startedAt: number) => {
      const fix = summarize(samples, startedAt);
      setStep({ name: 'capturing', samples: samples.length, best: fix?.accuracy ?? null });
    });
    gps.current = run;
    try {
      const fix = await run.result;
      gps.current = null;
      setStep(fix ? { name: 'result', fix } : { name: 'problem', problem: 'no_fix' });
    } catch {
      gps.current = null;
      setStep({ name: 'problem', problem: 'error' });
    }
  };

  const cancel = () => {
    gps.current?.stop();
    gps.current = null;
    onClose(null);
  };

  const save = async (fix: GpsFix) => {
    if (!confirmedAtSchool) {
      setError('Please confirm that you are physically at the school premises.');
      return;
    }
    const why = reason === 'Other' ? other.trim() : reason;
    if (kind === 'correction' && !why) {
      setError('Choose why the location is being corrected.');
      return;
    }
    setError('');
    setStep({ name: 'saving' });
    try {
      const capture = await saveCapture({
        school,
        target,
        kind,
        pointSource: 'device',
        lat: fix.lat,
        lng: fix.lng,
        accuracyM: Math.round(fix.accuracy * 10) / 10,
        capturedAt: fix.at,
        sampleCount: fix.sampleCount,
        spreadM: fix.spread,
        reason: why,
        accessNote: access.trim(),
      });
      setStep({ name: 'saved', capture });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The location could not be saved on this phone.');
      setStep({ name: 'result', fix });
    }
  };

  const title = target === 'entrance' ? 'School entrance' : kind === 'new' ? 'Add School GPS' : 'Update School GPS';
  const previous = target === 'entrance' ? (school.entranceLat !== null ? { lat: school.entranceLat, lng: school.entranceLng! } : null) : school.lat !== null ? { lat: school.lat, lng: school.lng! } : null;

  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={cancel}>
      <View style={[styles.sheet, { backgroundColor: colors.bg, paddingBottom: insets.bottom + spacing.md }]}>
        <View style={styles.header}>
          <View style={styles.flex}>
            <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
              {title}
            </Text>
            <Text style={[styles.sub, { color: colors.textMuted }]}>
              {school.name} · School ID {school.code || '—'}
            </Text>
          </View>
          <Pressable onPress={cancel} accessibilityRole="button" accessibilityLabel="Close" hitSlop={10} style={styles.close}>
            <X size={24} color={colors.text} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled" automaticallyAdjustKeyboardInsets>
          {step.name === 'start' ? (
            <>
              <Text style={[styles.lead, { color: colors.text }]}>
                {target === 'entrance'
                  ? 'Stand at the school gate or where the road reaches the school, then press Capture GPS.'
                  : 'Stand at the school (in the compound, in the open), then press Capture GPS.'}
              </Text>
              <Text style={[styles.hint, { color: colors.textMuted }]}>
                Works without internet. Your location is read once for this school and never tracked.
              </Text>
              <BigButton label="Capture GPS" icon={<Crosshair size={22} color="#fff" />} onPress={() => void start()} />
            </>
          ) : null}
          {step.name === 'capturing' ? (
            <View style={styles.center} accessibilityLiveRegion="polite">
              <ActivityIndicator size="large" color={BLUE} />
              <Text style={[styles.lead, { color: colors.text }]}>Capturing GPS…</Text>
              <Text style={[styles.hint, { color: colors.textMuted }]}>
                {step.best === null ? 'Waiting for satellites' : `Best so far: ${Math.round(step.best)} m (${step.samples} readings)`}
              </Text>
              <Pressable onPress={cancel} accessibilityRole="button" style={styles.plain}>
                <Text style={[styles.plainText, { color: colors.textMuted }]}>Cancel</Text>
              </Pressable>
            </View>
          ) : null}
          {step.name === 'problem' ? (
            <>
              <Text style={[styles.problem, { color: colors.danger, backgroundColor: colors.dangerSoft }]} accessibilityRole="alert">
                {PROBLEM_TEXT[step.problem]}
              </Text>
              <BigButton label="Try again" icon={<RefreshCw size={20} color="#fff" />} onPress={() => void start()} />
            </>
          ) : null}
          {step.name === 'result' || step.name === 'saving' ? (
            <Result
              school={school}
              fix={step.name === 'result' ? step.fix : null}
              previous={previous}
              policy={policy}
              kind={kind}
              target={target}
              reason={reason}
              other={other}
              access={access}
              confirmedAtSchool={confirmedAtSchool}
              error={error}
              isSaving={step.name === 'saving'}
              onReason={setReason}
              onOther={setOther}
              onAccess={setAccess}
              onConfirmAtSchool={setConfirmedAtSchool}
              onRetry={() => {
                setConfirmedAtSchool(false);
                void start();
              }}
              onSave={(fix) => void save(fix)}
            />
          ) : null}
          {step.name === 'saved' ? <Saved capture={step.capture} isSignedIn={isSignedIn} onDone={() => onClose(step.capture)} /> : null}
        </ScrollView>
      </View>
    </Modal>
  );
}

interface ResultProps {
  readonly school: CachedSchool;
  readonly fix: GpsFix | null;
  readonly previous: { lat: number; lng: number } | null;
  readonly policy: { goodM: number; confirmM: number };
  readonly kind: CaptureKind;
  readonly target: CaptureTarget;
  readonly reason: string;
  readonly other: string;
  readonly access: string;
  readonly confirmedAtSchool: boolean;
  readonly error: string;
  readonly isSaving: boolean;
  onReason(next: string): void;
  onOther(next: string): void;
  onAccess(next: string): void;
  onConfirmAtSchool(next: boolean): void;
  onRetry(): void;
  onSave(fix: GpsFix): void;
}

function Result({
  school,
  fix,
  previous,
  policy,
  kind,
  target,
  reason,
  other,
  access,
  confirmedAtSchool,
  error,
  isSaving,
  onReason,
  onOther,
  onAccess,
  onConfirmAtSchool,
  onRetry,
  onSave,
}: ResultProps) {
  const { colors } = useTheme();
  // Kept across the Saving moment.
  const last = useRef<GpsFix | null>(fix);
  if (fix) last.current = fix;
  const shown = last.current;
  const previewScene = useMemo<MapScene>(() => {
    if (!shown) return { pins: [], path: [], legend: [], join: false };
    const pins: MapScene['pins'] = [
      { id: 'proposed-new', order: 'NEW', name: 'Proposed New GPS', detail: `${shown.lat.toFixed(6)}, ${shown.lng.toFixed(6)}`, lat: shown.lat, lng: shown.lng, tone: '#16a34a' },
    ];
    const legend: MapScene['legend'] = [{ label: 'Proposed New GPS', tone: '#16a34a' }];
    if (previous) {
      pins.push({ id: 'previous-old', order: 'OLD', name: 'Existing Stored GPS', detail: `${previous.lat.toFixed(6)}, ${previous.lng.toFixed(6)}`, lat: previous.lat, lng: previous.lng, tone: '#64748b' });
      legend.push({ label: 'Existing Stored GPS', tone: '#64748b' });
    }
    return { pins, path: [], legend, join: false, primaryId: 'proposed-new' };
  }, [shown, previous]);
  if (!shown) return null;
  const band = bandOf(shown.accuracy, policy);
  const moved = previous ? metersBetween(previous, shown) : null;
  const largeMove = moved !== null && moved > 1000;
  return (
    <>
      <View style={[styles.previewMap, { borderColor: colors.border }]}>
        <RouteMapView scene={previewScene} onSelect={() => undefined} />
      </View>
      <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.card }]}>
        <View style={styles.row}>
          <MapPin size={20} color={BLUE} />
          <Text style={[styles.coords, { color: colors.text }]} selectable>
            {shown.lat.toFixed(6)}, {shown.lng.toFixed(6)}
          </Text>
        </View>
        <Text style={[styles.band, { color: BAND_COLOR[band] }]}>
          GPS accuracy ±{Math.round(shown.accuracy)} m · {BAND_TEXT[band]}
        </Text>
        <Text style={[styles.hint, { color: colors.textMuted }]}>
          School: {school.name} (ID {school.code || '—'})
        </Text>
        <Text style={[styles.hint, { color: colors.textMuted }]}>
          Captured: {new Date(shown.at).toLocaleString()} · Source: Device location services
        </Text>
        <Text style={[styles.hint, { color: colors.textMuted }]}>
          {shown.sampleCount} readings, {Math.round(shown.spread)} m spread.
        </Text>
        {moved !== null ? (
          <Text style={[styles.hint, { color: largeMove ? '#b91c1c' : colors.text }]}>
            {largeMove ? 'Warning — large move (>1 km): ' : ''}
            {moved < 1000 ? `${Math.round(moved)} m` : `${(moved / 1000).toFixed(2)} km`} from stored coordinates
            {largeMove ? ' (will be held for supervisor review)' : ''}
          </Text>
        ) : null}
      </View>
      <Pressable
        onPress={() => onConfirmAtSchool(!confirmedAtSchool)}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: confirmedAtSchool }}
        style={[
          styles.confirmRow,
          { borderColor: confirmedAtSchool ? BLUE : colors.border, backgroundColor: confirmedAtSchool ? '#e8f1fd' : colors.card },
        ]}
      >
        <View style={[styles.checkbox, { borderColor: confirmedAtSchool ? BLUE : colors.border, backgroundColor: confirmedAtSchool ? BLUE : 'transparent' }]}>
          {confirmedAtSchool ? <Check size={14} color="#fff" /> : null}
        </View>
        <Text style={[styles.confirmText, { color: colors.text }]}>I confirm I am physically at {school.name}.</Text>
      </Pressable>
      {kind === 'correction' ? (
        <View style={styles.group}>
          <Text style={[styles.label, { color: colors.text }]}>Why is it being corrected?</Text>
          <View style={styles.chips}>
            {REASONS.map((r) => (
              <Pressable
                key={r}
                onPress={() => onReason(r)}
                accessibilityRole="radio"
                accessibilityState={{ checked: reason === r }}
                style={[styles.chip, { borderColor: reason === r ? BLUE : colors.border, backgroundColor: reason === r ? '#e8f1fd' : colors.card }]}
              >
                <Text style={[styles.chipText, { color: reason === r ? '#0b4a9e' : colors.text }]}>{r}</Text>
              </Pressable>
            ))}
          </View>
          {reason === 'Other' ? (
            <TextInput
              value={other}
              onChangeText={onOther}
              placeholder="Say what is wrong"
              placeholderTextColor={colors.textSubtle}
              maxLength={1000}
              accessibilityLabel="Reason"
              style={[styles.input, { color: colors.text, borderColor: colors.border, backgroundColor: colors.card }]}
            />
          ) : null}
        </View>
      ) : null}
      <View style={styles.group}>
        <Text style={[styles.label, { color: colors.text }]}>
          {target === 'entrance' ? 'How to find the entrance (optional)' : 'Landmark or directions (optional)'}
        </Text>
        <TextInput
          value={access}
          onChangeText={onAccess}
          placeholder="Turn left at the trading centre"
          placeholderTextColor={colors.textSubtle}
          maxLength={300}
          accessibilityLabel="Landmark or directions"
          style={[styles.input, { color: colors.text, borderColor: colors.border, backgroundColor: colors.card }]}
        />
      </View>
      {error ? (
        <Text style={[styles.problem, { color: colors.danger, backgroundColor: colors.dangerSoft }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
      {band === 'recapture' ? (
        <>
          <BigButton label="Retake GPS Reading" icon={<RefreshCw size={20} color="#fff" />} onPress={onRetry} isDisabled={isSaving} />
          <Pressable onPress={() => onSave(shown)} disabled={isSaving || !confirmedAtSchool} accessibilityRole="button" style={[styles.plain, !confirmedAtSchool && styles.dim]}>
            <Text style={[styles.plainText, { color: colors.textMuted }]}>Save School Location for Review</Text>
          </Pressable>
        </>
      ) : (
        <>
          <BigButton
            label={isSaving ? 'Saving…' : 'Save School Location'}
            icon={<Check size={22} color="#fff" />}
            onPress={() => onSave(shown)}
            isDisabled={isSaving || !confirmedAtSchool}
          />
          <Pressable onPress={onRetry} disabled={isSaving} accessibilityRole="button" style={styles.plain}>
            <Text style={[styles.plainText, { color: BLUE }]}>Retake GPS Reading</Text>
          </Pressable>
        </>
      )}
    </>
  );
}

function Saved({ capture, isSignedIn, onDone }: { readonly capture: QueuedCapture; readonly isSignedIn: boolean; onDone(): void }) {
  const { colors } = useTheme();
  const local = capture.status === 'saved_offline' || capture.status === 'pending_sync';
  return (
    <View style={styles.center}>
      <View style={[styles.done, { backgroundColor: local ? '#fff7ed' : '#e8f1fd' }]}>
        <Check size={34} color={local ? '#b45309' : BLUE} />
      </View>
      <Text style={[styles.lead, { color: colors.text }]} accessibilityLiveRegion="polite">
        {local ? 'Pending Sync (Saved Offline)' : STATUS_TEXT[capture.status]}
      </Text>
      <Text style={[styles.hint, { color: colors.textMuted, textAlign: 'center' }]}>
        {local
          ? isSignedIn
            ? 'Not saved to PostgreSQL yet. Edify will sync automatically once internet connectivity returns.'
            : 'You are offline. Marked Pending Sync — will upload automatically when back online.'
          : capture.note}
      </Text>
      <BigButton label="Done" onPress={onDone} />
    </View>
  );
}

function BigButton({ label, icon, onPress, isDisabled = false }: { readonly label: string; readonly icon?: React.ReactNode; onPress(): void; readonly isDisabled?: boolean }) {
  return (
    <Pressable onPress={onPress} disabled={isDisabled} accessibilityRole="button" style={[styles.big, isDisabled && styles.dim]}>
      {icon}
      <Text style={styles.bigText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  sheet: { flex: 1 },
  flex: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, padding: spacing.lg, paddingBottom: spacing.sm },
  title: { fontFamily: fonts.bold, fontSize: 22 },
  sub: { fontFamily: fonts.medium, fontSize: 14, marginTop: 2 },
  close: { minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  body: { padding: spacing.lg, gap: spacing.md },
  lead: { fontFamily: fonts.semibold, fontSize: 18, lineHeight: 25 },
  hint: { fontFamily: fonts.regular, fontSize: 14, lineHeight: 20 },
  center: { alignItems: 'center', gap: spacing.md, paddingVertical: spacing.xl },
  problem: { fontFamily: fonts.medium, fontSize: 15, borderRadius: radius.sm, padding: spacing.md, lineHeight: 21 },
  card: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: 6 },
  previewMap: { height: 180, borderRadius: radius.md, borderWidth: 1, overflow: 'hidden' },
  confirmRow: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1.5, borderRadius: radius.md, padding: spacing.md },
  checkbox: { width: 22, height: 22, borderRadius: 5, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  confirmText: { flex: 1, fontFamily: fonts.semibold, fontSize: 14 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  coords: { fontFamily: fonts.semibold, fontSize: 18 },
  band: { fontFamily: fonts.semibold, fontSize: 16 },
  group: { gap: 8 },
  label: { fontFamily: fonts.semibold, fontSize: 15 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1.5, borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 44, justifyContent: 'center' },
  chipText: { fontFamily: fonts.semibold, fontSize: 14 },
  input: { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, minHeight: 48, fontFamily: fonts.regular, fontSize: 16 },
  big: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, backgroundColor: BLUE, borderRadius: radius.md, minHeight: 56, paddingHorizontal: spacing.lg, alignSelf: 'stretch' },
  bigText: { fontFamily: fonts.semibold, fontSize: 18, color: '#fff' },
  plain: { minHeight: 48, alignItems: 'center', justifyContent: 'center' },
  plainText: { fontFamily: fonts.semibold, fontSize: 16 },
  dim: { opacity: 0.6 },
  done: { width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center' },
});
