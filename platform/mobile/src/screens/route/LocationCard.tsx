/**
 * A school's Location & Directions card on its profile (Smart Route brief,
 * part 11): the school on the map, how sure its location is, directions in
 * the person's own maps app, and its nearby schools in the planner. A school
 * with no usable location says so and stays in every list and plan.
 */
import { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { MapPin, Navigation, Route } from 'lucide-react-native';

import { useSession } from '../../auth/SessionContext';
import { RoutePlannerService } from '../../gen/edify/routes/v1/routes_pb';
import type { GetSchoolLocationResponse } from '../../gen/edify/routes/v1/routes_pb';
import { fonts, radius, spacing, useTheme } from '../../theme';
import { chooseDirections } from './directions';
import { PIN_TONES, ROUTE_URL, shortName } from './routeData';
import { RouteMapView } from './RouteMapView';

const STATUS: Record<string, string> = {
  verified: 'Verified location',
  recorded: 'From the School Directory (not yet verified)',
  missing: 'No location recorded',
  invalid: 'The recorded location looks wrong',
};

export interface LocationCardProps {
  readonly schoolId: string;
  /** Opens the route planner; absent where the profile cannot. */
  readonly onOpenRoute?: (url: string) => void;
}

export function LocationCard({ schoolId, onOpenRoute }: LocationCardProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [answer, setAnswer] = useState<GetSchoolLocationResponse | null>(null);

  useEffect(() => {
    let isCurrent = true;
    api
      .call(RoutePlannerService.method.getSchoolLocation, { schoolId })
      .then((next) => isCurrent && setAnswer(next))
      // Without its location the profile is shown as it was.
      .catch(() => undefined);
    return () => {
      isCurrent = false;
    };
  }, [api, schoolId]);

  const school = answer?.school;
  const point = school?.point;
  const scene = useMemo(
    () => ({
      pins: point && school ? [{ id: school.schoolId, order: '', name: shortName(school.name), detail: '', lat: point.lat, lng: point.lng, tone: PIN_TONES.planned }] : [],
      path: [],
      legend: [],
    }),
    [school, point],
  );
  if (!answer || !school) return null;

  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]} accessibilityLabel="Location and directions">
      <View style={styles.title}>
        <MapPin size={20} color={PIN_TONES.planned} />
        <Text style={[styles.titleText, { color: colors.text }]} accessibilityRole="header">
          Location &amp; Directions
        </Text>
      </View>
      {point ? (
        <>
          <View style={[styles.map, { borderColor: colors.border }]}>
            <RouteMapView scene={scene} onSelect={() => undefined} />
          </View>
          <Text style={[styles.label, { color: colors.textMuted }]}>GPS location</Text>
          <Text style={[styles.value, { color: colors.text }]}>
            {point.lat.toFixed(6)}, {point.lng.toFixed(6)}
          </Text>
          <Text style={[styles.label, { color: colors.textMuted }]}>Location status</Text>
          <Text style={[styles.value, { color: colors.text }]}>{STATUS[school.locationStatus] ?? school.locationStatus}</Text>
          <Text style={[styles.label, { color: colors.textMuted }]}>Nearby</Text>
          <Text style={[styles.value, { color: colors.text }]}>
            {answer.nearbySchools} of your schools within {answer.nearbyRadiusKm} km (straight line)
          </Text>
          <View style={styles.buttons}>
            <Pressable onPress={() => chooseDirections([school])} style={styles.primary} accessibilityRole="button">
              <Navigation size={18} color="#fff" />
              <Text style={styles.primaryText}>Get Directions</Text>
            </Pressable>
            {answer.canPlan && onOpenRoute ? (
              <Pressable onPress={() => onOpenRoute(ROUTE_URL)} style={styles.outline} accessibilityRole="button">
                <Route size={18} color={PIN_TONES.planned} />
                <Text style={styles.outlineText}>Find Nearby Schools</Text>
              </Pressable>
            ) : null}
          </View>
        </>
      ) : (
        <Text style={styles.missing} accessibilityRole="text">
          {STATUS[school.locationStatus]}. Directions and route planning need a location; the school still appears in every list
          and plan.
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: 4, marginTop: spacing.md },
  title: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: spacing.sm },
  titleText: { fontFamily: fonts.semibold, fontSize: 16 },
  map: { height: 220, borderRadius: radius.sm, borderWidth: 1, overflow: 'hidden', marginBottom: spacing.sm },
  label: { fontFamily: fonts.regular, fontSize: 13, marginTop: spacing.xs },
  value: { fontFamily: fonts.medium, fontSize: 14 },
  buttons: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.md },
  primary: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: PIN_TONES.planned, borderRadius: radius.sm, paddingHorizontal: 14, minHeight: 44 },
  primaryText: { fontFamily: fonts.semibold, fontSize: 15, color: '#fff' },
  outline: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1.5, borderColor: PIN_TONES.planned, borderRadius: radius.sm, paddingHorizontal: 14, minHeight: 44 },
  outlineText: { fontFamily: fonts.semibold, fontSize: 15, color: PIN_TONES.planned },
  missing: { fontFamily: fonts.regular, fontSize: 14, color: '#92400e', backgroundColor: '#fffbeb', borderRadius: radius.sm, padding: spacing.sm },
});
