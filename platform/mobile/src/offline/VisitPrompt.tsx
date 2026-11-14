/**
 * GPS capture as part of an ordinary visit (owner, 2026-11-14): opening a
 * school with planned work today asks once a day, "This school has no GPS
 * location. Capture it now?" or "Is this school's location correct?" with
 * Yes or Correct Location. Offline, the answer and any new point are kept
 * on the phone until they sync.
 */
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { MapPinned } from 'lucide-react-native';

import { fonts, radius, spacing } from '../theme';
import { todayLocal, useOffline } from './OfflineContext';
import type { CachedSchool } from './store';
import { useCachedSchool } from './useCachedSchool';

const BLUE = '#1d6fe0';

export interface VisitPromptProps {
  /** The school, as the phone holds it (null when it is not among the person's schools). */
  readonly school: CachedSchool | null;
  /** The school has planned work today by some other reckoning (the route's day). */
  readonly isVisitDay?: boolean;
}

export function VisitPrompt({ school, isVisitDay = false }: VisitPromptProps) {
  const { store, account, canCapture, saveCapture, markChanged, openCapture } = useOffline();
  const [isShown, setIsShown] = useState(false);
  const [thanks, setThanks] = useState('');
  const today = todayLocal();

  useEffect(() => {
    if (!store || !account || !school || !canCapture) return;
    let isCurrent = true;
    void (async () => {
      const planned = isVisitDay || (await store.plannedOn(account.userId, today)).some((v) => v.schoolId === school.schoolId);
      const asked = await store.wasPrompted(account.userId, school.schoolId, today);
      if (isCurrent) setIsShown(planned && !asked);
    })();
    return () => {
      isCurrent = false;
    };
  }, [store, account, school, canCapture, isVisitDay, today]);

  if (!school || (!isShown && !thanks)) return null;
  const done = async (message: string) => {
    if (store && account) await store.markPrompted(account.userId, school.schoolId, today);
    setIsShown(false);
    setThanks(message);
    markChanged();
  };
  const hasPoint = school.lat !== null;
  const capture = () =>
    openCapture({
      school,
      target: 'school',
      onDone: (saved) => {
        if (saved) void done(saved.status === 'saved_offline' ? 'Location saved on this phone. It syncs when you are online.' : saved.note);
      },
    });

  return (
    <View style={styles.card} accessibilityLiveRegion="polite">
      {thanks ? (
        <Text style={styles.text}>{thanks}</Text>
      ) : (
        <>
          <View style={styles.row}>
            <MapPinned size={22} color={BLUE} />
            <Text style={styles.question}>{hasPoint ? 'Is this school’s location correct?' : 'This school has no GPS location. Capture it now?'}</Text>
          </View>
          <View style={styles.buttons}>
            {hasPoint ? (
              <>
                <Pressable
                  style={styles.primary}
                  accessibilityRole="button"
                  onPress={() =>
                    void saveCapture({
                      school, target: 'school', kind: 'confirm', pointSource: 'none', lat: null, lng: null, accuracyM: 0,
                      capturedAt: null, sampleCount: 0, spreadM: 0, reason: '', accessNote: '',
                    }).then(() => done('Thank you. Your answer is saved and syncs with your visit.'))
                  }
                >
                  <Text style={styles.primaryText}>Yes</Text>
                </Pressable>
                <Pressable style={styles.outline} accessibilityRole="button" onPress={capture}>
                  <Text style={styles.outlineText}>Correct Location</Text>
                </Pressable>
              </>
            ) : (
              <Pressable style={styles.primary} accessibilityRole="button" onPress={capture}>
                <Text style={styles.primaryText}>Capture now</Text>
              </Pressable>
            )}
            <Pressable style={styles.plain} accessibilityRole="button" onPress={() => void done('')}>
              <Text style={styles.plainText}>Not now</Text>
            </Pressable>
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: '#e8f1fd', borderRadius: radius.md, padding: spacing.md, gap: spacing.sm, marginBottom: spacing.md, borderWidth: 1, borderColor: '#a9c8f3' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  question: { flex: 1, fontFamily: fonts.semibold, fontSize: 16, color: '#0b3a7a' },
  text: { fontFamily: fonts.medium, fontSize: 15, color: '#0b3a7a' },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, alignItems: 'center' },
  primary: { backgroundColor: BLUE, borderRadius: radius.sm, paddingHorizontal: 18, minHeight: 48, justifyContent: 'center' },
  primaryText: { fontFamily: fonts.semibold, fontSize: 16, color: '#fff' },
  outline: { borderWidth: 1.5, borderColor: BLUE, borderRadius: radius.sm, paddingHorizontal: 16, minHeight: 48, justifyContent: 'center', backgroundColor: '#fff' },
  outlineText: { fontFamily: fonts.semibold, fontSize: 16, color: BLUE },
  plain: { minHeight: 48, justifyContent: 'center', paddingHorizontal: 8 },
  plainText: { fontFamily: fonts.semibold, fontSize: 15, color: '#475569' },
});

/** The prompt for a school the profile opened, from the phone's copy of it. */
export function SchoolVisitPrompt({ schoolId }: { readonly schoolId: string }) {
  const school = useCachedSchool(schoolId);
  return <VisitPrompt school={school} />;
}
