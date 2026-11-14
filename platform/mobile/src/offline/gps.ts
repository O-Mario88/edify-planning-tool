/**
 * Capturing a school's position on the phone (offline capture brief,
 * 2026-11-14, part 3). Asks for location only when the person presses
 * Capture, in the foreground and never in the background; checks that
 * location services are on and that precise (not approximate) location was
 * allowed; then takes fresh readings for up to 30 seconds and stops the
 * moment it is done or cancelled. Nothing is kept of the readings but the
 * one point. Needs no connection: GPS works in airplane mode.
 */
import * as Location from 'expo-location';
import { Platform } from 'react-native';

import { CAPTURE_TIMEOUT_MS, isSettled, summarize } from './gpsMath';
import type { GpsFix, GpsPolicy, GpsSample } from './gpsMath';

export type GpsProblem = 'denied' | 'blocked' | 'services_off' | 'approximate' | 'no_fix' | 'error';

export const PROBLEM_TEXT: Record<GpsProblem, string> = {
  denied: 'Location was not allowed. Edify needs it only while you capture a school’s location.',
  blocked: 'Location is turned off for Edify. Allow it in Settings, then try again.',
  services_off: 'Location services are off on this phone. Turn them on, then try again.',
  approximate: 'Only approximate location is allowed for Edify. Allow precise location in Settings to capture a school.',
  no_fix: 'No GPS reading came. Move into the open, away from buildings and trees, and try again.',
  error: 'The phone’s GPS could not be read. Please try again.',
};

/** Checks, and asks for, what a capture needs; null when all is well. */
export async function prepareGps(): Promise<GpsProblem | null> {
  try {
    let permission = await Location.getForegroundPermissionsAsync();
    if (!permission.granted) {
      if (!permission.canAskAgain) return 'blocked';
      permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted) return permission.canAskAgain ? 'denied' : 'blocked';
    }
    if (!(await Location.hasServicesEnabledAsync())) return 'services_off';
    const precise =
      Platform.OS === 'ios' ? permission.ios?.accuracy !== 'reduced' : Platform.OS === 'android' ? permission.android?.accuracy !== 'coarse' : true;
    return precise ? null : 'approximate';
  } catch {
    return 'error';
  }
}

export interface GpsCapture {
  /** The point, or null when no fresh reading came in time. */
  readonly result: Promise<GpsFix | null>;
  /** Stops the readings now (cancel, or the screen closed). */
  stop(): void;
}

/**
 * Takes readings until enough good ones agree, or 30 seconds pass, and
 * reports each as it comes. Always stops the readings when it ends.
 */
export function captureGps(policy: GpsPolicy, onProgress: (samples: readonly GpsSample[], startedAt: number) => void): GpsCapture {
  const startedAt = Date.now();
  const samples: GpsSample[] = [];
  let subscription: Location.LocationSubscription | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let finish: (fix: GpsFix | null) => void = () => undefined;
  let isDone = false;

  const end = () => {
    if (isDone) return;
    isDone = true;
    subscription?.remove();
    subscription = null;
    if (timer) clearTimeout(timer);
    finish(summarize(samples, startedAt));
  };

  const result = new Promise<GpsFix | null>((resolve, reject) => {
    finish = resolve;
    timer = setTimeout(end, CAPTURE_TIMEOUT_MS);
    Location.watchPositionAsync(
      { accuracy: Location.Accuracy.BestForNavigation, timeInterval: 1000, distanceInterval: 0, mayShowUserSettingsDialog: true },
      (location) => {
        samples.push({
          lat: location.coords.latitude,
          lng: location.coords.longitude,
          accuracy: location.coords.accuracy ?? Number.POSITIVE_INFINITY,
          at: location.timestamp,
        });
        onProgress(samples, startedAt);
        if (isSettled(samples, startedAt, policy)) end();
      },
    )
      .then((sub) => {
        if (isDone) sub.remove();
        else subscription = sub;
      })
      .catch((cause: unknown) => {
        isDone = true;
        if (timer) clearTimeout(timer);
        reject(cause instanceof Error ? cause : new Error('gps'));
      });
  });
  return { result, stop: end };
}
