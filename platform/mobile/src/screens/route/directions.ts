/** Directions in the person's own maps app, chosen by them (keyless links). */
import { Alert, Linking, Platform } from 'react-native';

import type { SchoolPin } from '../../gen/edify/routes/v1/routes_pb';
import { directionsUrl } from './routeData';
import type { MapsApp } from './routeData';

export function chooseDirections(stops: readonly SchoolPin[]): void {
  const go = (app: MapsApp) => {
    const target = directionsUrl(stops, app);
    if (target) void Linking.openURL(target);
  };
  if (Platform.OS === 'web') return go('google');
  Alert.alert('Get directions', 'Open the route in your maps app.', [
    { text: 'Google Maps', onPress: () => go('google') },
    ...(Platform.OS === 'ios' ? [{ text: 'Apple Maps', onPress: () => go('apple') }] : []),
    { text: 'Waze', onPress: () => go('waze') },
    { text: 'Cancel', style: 'cancel' as const },
  ]);
}
