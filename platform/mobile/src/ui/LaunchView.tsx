/**
 * What shows while the app confirms a saved sign-in (owner brief,
 * 2026-11-11): exactly the native launch screen, so the hand-over from it is
 * invisible. Only a start slower than LOADING_HINT_AFTER_MS adds "Loading
 * Edify…" and the wave; a quick one goes straight to the person's home.
 * When Edify cannot be reached it says so and offers to try again, keeping
 * the saved sign-in.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import brand from '../../assets/brand/brand.json';
import { LOADING_HINT_AFTER_MS } from '../auth/launch';
import { fonts } from '../theme';

// The same images and sizes as the native launch screen (app.json).
const MARK = Platform.select({
  ios: { source: require('../../assets/splash-lockup.png'), width: 260, height: 260 * (180 / 961) },
  default: { source: require('../../assets/splash-icon.png'), width: 200, height: 200 },
});

type WaveName = keyof typeof brand.waves;

/** A wave from brand.json as an SVG path in its 1000 x 1000 box. */
function wavePath(name: WaveName): string {
  const { from, c1, c2, to } = brand.waves[name];
  return `M${from[0]} ${from[1]} C${c1[0]} ${c1[1]} ${c2[0]} ${c2[1]} ${to[0]} ${to[1]} L1000 1000 L0 1000 Z`;
}

/** The brand's two waves along the bottom edge, stretched to the width. */
export function BrandWave({ height }: { readonly height: number }) {
  return (
    <Svg width="100%" height={height} viewBox="0 560 1000 440" preserveAspectRatio="none" style={styles.wave} pointerEvents="none">
      <Path d={wavePath('back')} fill={brand.waveBack} />
      <Path d={wavePath('front')} fill={brand.waveFront} />
    </Svg>
  );
}

interface LaunchViewProps {
  /** Shown when Edify could not be reached; with it, the retry controls. */
  readonly problem?: string;
  readonly onRetry?: () => void;
  readonly onSignOut?: () => void;
}

export function LaunchView({ problem, onRetry, onSignOut }: LaunchViewProps) {
  const [isSlow, setIsSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setIsSlow(true), LOADING_HINT_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);
  const isWaiting = !problem;
  return (
    <View style={styles.page} accessibilityLabel={problem ? undefined : 'Loading Edify'}>
      {isSlow || problem ? <BrandWave height={220} /> : null}
      <Image source={MARK.source} style={{ width: MARK.width, height: MARK.height }} resizeMode="contain" accessibilityLabel="Edify Planning and Monitoring" />
      <View style={styles.below}>
        {isWaiting && isSlow ? (
          <>
            <ActivityIndicator color="#ffffff" />
            <Text style={styles.hint}>Loading Edify…</Text>
          </>
        ) : null}
        {problem ? (
          <>
            <Text style={styles.problem} accessibilityRole="alert">
              {problem}
            </Text>
            <Pressable onPress={onRetry} accessibilityRole="button" style={({ pressed }) => [styles.retry, pressed && styles.pressed]}>
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
            <Pressable onPress={onSignOut} accessibilityRole="button" hitSlop={8}>
              <Text style={styles.other}>Sign in as someone else</Text>
            </Pressable>
          </>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: brand.navy },
  wave: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  below: { position: 'absolute', top: '58%', left: 24, right: 24, alignItems: 'center', gap: 14 },
  hint: { fontFamily: fonts.semibold, fontSize: 15, color: '#ffffff' },
  problem: { fontFamily: fonts.medium, fontSize: 15, lineHeight: 22, color: '#ffffff', textAlign: 'center', maxWidth: 340 },
  retry: { minHeight: 48, minWidth: 180, paddingHorizontal: 24, borderRadius: 10, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ffffff' },
  pressed: { opacity: 0.85 },
  retryText: { fontFamily: fonts.semibold, fontSize: 15, color: brand.navy },
  other: { fontFamily: fonts.semibold, fontSize: 14, color: '#cfe3f5', textDecorationLine: 'underline' },
});
