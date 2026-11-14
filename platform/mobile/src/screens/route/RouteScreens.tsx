/**
 * The two Smart Route Planner screens as the owner's mobile design draws
 * them: the planner (map first, the recommended route card, the four
 * figures, Optimise Route) and Route Details (itinerary, map, options, the
 * schools near the route, Get Directions and Start Field Day).
 */
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import {
  ArrowLeft,
  Car,
  CheckCircle2,
  ChevronRight,
  Clock,
  List,
  Lock,
  Map as MapIcon,
  MapPin,
  Navigation,
  Play,
  School,
  SlidersHorizontal,
  Sparkles,
  Star,
  Target,
  CalendarDays,
  ArrowDownUp,
} from 'lucide-react-native';

import type { GetFieldDayResponse, Itinerary, ItineraryStop, Suggestion } from '../../gen/edify/routes/v1/routes_pb';
import { fonts, radius, spacing, useTheme } from '../../theme';
import { DateField } from '../../ui/DateField';
import { Select } from '../../ui/Select';
import { PIN_TONES, ROUTE_TEAL, hrMin, km, legFigures, totalFigures } from './routeData';
import type { MapScene } from './routeMapHtml';
import { RouteMapView } from './RouteMapView';

interface Common {
  readonly day: GetFieldDayResponse;
  readonly itinerary: Itinerary | undefined;
  readonly scene: MapScene;
  readonly date: string;
  readonly areaLabel: string;
  readonly notice: string;
  readonly isBusy: boolean;
  readonly onSelectSchool: (schoolId: string) => void;
}

const longDate = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }).replace(',', ',');

function Figure({ icon, value, label, tint }: { icon: React.ReactNode; value: string; label: string; tint?: string }) {
  const { colors } = useTheme();
  return (
    <View style={styles.figure} accessible accessibilityLabel={`${value} ${label}`}>
      <View style={{ height: 26, justifyContent: 'center' }}>{icon}</View>
      <Text style={[styles.figureValue, { color: tint ?? colors.text }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>
        {value}
      </Text>
      <Text style={[styles.figureLabel, { color: colors.textMuted }]} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.75}>
        {label}
      </Text>
    </View>
  );
}

function Segment<T extends string>({ value, options, onChange }: { value: T; options: readonly { key: T; label: string; icon: React.ReactNode }[]; onChange: (v: T) => void }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.segment, { backgroundColor: colors.surface, borderColor: colors.border }]} accessibilityRole="tablist">
      {options.map((o) => {
        const active = o.key === value;
        return (
          <Pressable
            key={o.key}
            onPress={() => onChange(o.key)}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            style={[styles.segmentItem, active && { backgroundColor: ROUTE_TEAL }]}
          >
            {o.icon}
            <Text style={[styles.segmentText, { color: active ? '#fff' : colors.text }]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Notice({ text }: { text: string }) {
  const { colors } = useTheme();
  if (!text) return null;
  return <Text style={[styles.notice, { color: colors.text, backgroundColor: colors.surface, borderColor: colors.border }]}>{text}</Text>;
}

function StopList({ stops, onSelect }: { stops: readonly ItineraryStop[]; onSelect: (id: string) => void }) {
  const { colors } = useTheme();
  return (
    <View>
      {stops.map((s) => (
        <Pressable key={s.school?.schoolId} onPress={() => s.school && onSelect(s.school.schoolId)} style={[styles.listRow, { borderColor: colors.border }]}>
          <View style={[styles.dot, { backgroundColor: s.kind === 'recommended' ? PIN_TONES.suggested : PIN_TONES.planned }]}>
            <Text style={styles.dotText}>{s.order}</Text>
          </View>
          <View style={styles.flex}>
            <Text style={[styles.rowTitle, { color: colors.text }]}>{s.school?.name}</Text>
            <Text style={[styles.rowSub, { color: colors.textMuted }]}>
              Arrive {s.arrival} · {legFigures(s.leg) ? `${km(legFigures(s.leg)!.meters)} • ${hrMin(legFigures(s.leg)!.seconds)}` : 'First stop'}
            </Text>
          </View>
        </Pressable>
      ))}
    </View>
  );
}

export function RoutePlannerScreen({
  day,
  itinerary,
  scene,
  date,
  district,
  notice,
  isBusy,
  onDate,
  onDistrict,
  onOptimise,
  onOpenDetails,
  onSelectSchool,
}: Common & {
  readonly district: string;
  readonly onDate: (v: string) => void;
  readonly onDistrict: (v: string) => void;
  readonly onOptimise: () => void;
  readonly onOpenDetails: () => void;
}) {
  const { colors } = useTheme();
  const [view, setView] = useState<'map' | 'list'>('map');
  const total = totalFigures(itinerary?.totals);
  const stops = itinerary?.stops ?? [];
  const recommended = stops.filter((s) => s.kind === 'recommended').length;
  return (
    <ScrollView contentContainerStyle={styles.page} style={{ backgroundColor: colors.bg }}>
      <View style={styles.titleRow}>
        <MapPin size={34} color="#1d6fe0" fill="#1d6fe0" stroke="#ffffff" strokeWidth={1.5} />
        <View style={styles.flex}>
          <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
            Smart Route Planner
          </Text>
          <Text style={[styles.subtitle, { color: colors.textMuted }]}>Plan, optimise and navigate your school visits</Text>
        </View>
      </View>
      <View style={styles.pickers}>
        <View style={styles.flex}>
          <DateField label="Field day" value={date} onChange={(v) => v && onDate(v)} />
        </View>
        <View style={styles.flex}>
          <Select
            label="District"
            value={district}
            placeholder="All districts"
            hasEmptyChoice
            choices={day.districts.map((d) => ({ value: d.value, label: `${d.label} District` }))}
            onChange={onDistrict}
            variant="filter"
          />
        </View>
      </View>
      <Segment
        value={view}
        onChange={setView}
        options={[
          { key: 'map', label: 'Map View', icon: <MapIcon size={20} color={view === 'map' ? '#fff' : colors.text} /> },
          { key: 'list', label: 'List View', icon: <List size={20} color={view === 'list' ? '#fff' : colors.text} /> },
        ]}
      />
      <Notice text={notice} />
      {view === 'map' ? (
        <View style={[styles.mapCard, { borderColor: colors.border }]}>
          <RouteMapView scene={scene} onSelect={onSelectSchool} />
          {stops.length ? (
            <Pressable onPress={onOpenDetails} style={styles.routeCard} accessibilityRole="button" accessibilityLabel="Open the recommended route">
              <CheckCircle2 size={26} color="#ffffff" fill="#16a34a" />
              <View>
                <Text style={styles.routeCardTitle}>Recommended Route</Text>
                <Text style={styles.routeCardSub}>
                  {km(total.meters)} • {hrMin(total.seconds)}
                </Text>
              </View>
              <ChevronRight size={20} color="#0f172a" />
            </Pressable>
          ) : null}
        </View>
      ) : (
        <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          {stops.length ? <StopList stops={stops} onSelect={onSelectSchool} /> : <Text style={[styles.rowSub, { color: colors.textMuted }]}>No school visits are planned on {longDate(date)}.</Text>}
        </View>
      )}
      <View style={[styles.figures, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <Figure icon={<Car size={26} color={colors.text} />} value={km(total.meters)} label="Distance" />
        <Figure icon={<Clock size={24} color={colors.text} />} value={hrMin(total.seconds)} label="Travel Time" />
        <Figure icon={<School size={24} color={colors.text} />} value={String(itinerary?.totals?.selected ?? 0)} label="Schools" />
        <Figure icon={<Star size={24} color="#f59e0b" fill="#f59e0b" />} value={String(recommended)} label="Recommended" />
      </View>
      {!total.road && stops.length > 1 ? (
        <Text style={[styles.measure, { color: colors.textMuted }]}>Straight-line distances: road distances are unavailable just now.</Text>
      ) : null}
      <Pressable
        onPress={onOptimise}
        disabled={isBusy || stops.length === 0}
        style={[styles.primary, { opacity: isBusy || stops.length === 0 ? 0.6 : 1 }]}
        accessibilityRole="button"
      >
        <Sparkles size={22} color="#fff" />
        <Text style={styles.primaryText}>{isBusy ? 'Working…' : 'Optimise Route'}</Text>
      </Pressable>
    </ScrollView>
  );
}

function SuggestionRow({ s, onAdd, onSelect }: { s: Suggestion; onAdd: () => void; onSelect: () => void }) {
  const { colors } = useTheme();
  const high = s.label === 'High Priority';
  return (
    <View style={[styles.suggestion, { borderColor: colors.border }]}>
      <Pressable onPress={onSelect} style={styles.photo} accessibilityLabel={`Open ${s.school?.name}`}>
        <School size={34} color="#15803d" />
      </Pressable>
      <View style={styles.flex}>
        <View style={styles.pillRow}>
          <Text style={[styles.rowTitle, { color: colors.text }]}>{s.school?.name}</Text>
          <Text style={[styles.pill, high ? styles.pillHigh : styles.pillEligible]}>{s.label}</Text>
        </View>
        <View style={styles.inline}>
          <MapPin size={16} color={colors.textMuted} />
          <Text style={[styles.rowSub, { color: colors.text }]}>
            {Number(s.addedMeters) < 100 ? 'On the way' : km(s.addedMeters)} (≈ {hrMin(s.addedSeconds)} detour{s.measure === 'road' ? '' : ', straight line'})
          </Text>
        </View>
        <View style={styles.inline}>
          <Target size={16} color={colors.textMuted} />
          <Text style={[styles.rowSub, { color: colors.text }]}>{high ? 'Needs SSA support' : 'Support visit open'}</Text>
        </View>
      </View>
      <Pressable onPress={onAdd} style={styles.outline} accessibilityRole="button">
        <Text style={styles.outlineText}>Add to Plan</Text>
      </Pressable>
    </View>
  );
}

export function RouteDetailsScreen({
  day,
  itinerary,
  scene,
  date,
  areaLabel,
  notice,
  isBusy,
  locked,
  isFieldDay,
  onBack,
  onToggleLock,
  onRecalculate,
  onKeepOrder,
  onAddToPlan,
  onDirections,
  onStartFieldDay,
  onRefresh,
  onSelectSchool,
}: Common & {
  readonly locked: ReadonlySet<string>;
  readonly isFieldDay: boolean;
  readonly onBack: () => void;
  readonly onToggleLock: (id: string) => void;
  readonly onRecalculate: () => void;
  readonly onKeepOrder: () => void;
  readonly onAddToPlan: (id: string) => void;
  readonly onDirections: () => void;
  readonly onStartFieldDay: () => void;
  readonly onRefresh: () => void;
}) {
  const { colors } = useTheme();
  const [tab, setTab] = useState<'itinerary' | 'map' | 'options'>('itinerary');
  const [allNearby, setAllNearby] = useState(false);
  const total = totalFigures(itinerary?.totals);
  const stops = itinerary?.stops ?? [];
  const conflicts = itinerary?.conflicts ?? [];
  const next = stops.find((s) => s.school?.status !== 'completed');
  const nearby = allNearby ? day.suggestions : day.suggestions.slice(0, 1);
  return (
    <View style={[styles.flex, { backgroundColor: colors.bg }]}>
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.titleRow}>
          <Pressable onPress={onBack} accessibilityRole="button" accessibilityLabel="Back to the planner" hitSlop={10}>
            <ArrowLeft size={26} color={colors.text} />
          </Pressable>
          <View style={styles.flex}>
            <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
              Route Details
            </Text>
            <Text style={[styles.subtitle, { color: colors.textMuted }]}>
              {longDate(date)}
              {areaLabel ? ` • ${areaLabel} District` : ''}
            </Text>
          </View>
        </View>
        {conflicts.length ? (
          <View style={[styles.banner, styles.bannerWarn]}>
            <Text style={styles.bannerTitleWarn}>This day does not fit</Text>
            {conflicts.map((c) => (
              <Text key={c} style={styles.bannerTextWarn}>
                {c}
              </Text>
            ))}
          </View>
        ) : stops.length ? (
          <View style={[styles.banner, styles.bannerOk]}>
            <CheckCircle2 size={40} color="#ffffff" fill="#16a34a" />
            <View style={styles.flex}>
              <Text style={styles.bannerTitle}>{isFieldDay ? 'Field day started' : 'Recommended Field Day'}</Text>
              <Text style={styles.bannerText}>
                {isFieldDay && next
                  ? `Next: ${next.school?.name}. Complete each visit through its usual workflow; finished visits drop off this route.`
                  : 'An efficient and feasible route based on your planned schools, school priorities and travel time.'}
              </Text>
            </View>
          </View>
        ) : null}
        <Segment
          value={tab}
          onChange={setTab}
          options={[
            { key: 'itinerary', label: 'Itinerary', icon: <List size={20} color={tab === 'itinerary' ? '#fff' : colors.text} /> },
            { key: 'map', label: 'Map', icon: <MapIcon size={20} color={tab === 'map' ? '#fff' : colors.text} /> },
            { key: 'options', label: 'Options', icon: <SlidersHorizontal size={20} color={tab === 'options' ? '#fff' : colors.text} /> },
          ]}
        />
        <Notice text={notice} />
        <View style={[styles.figures, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Figure icon={<Car size={26} color={colors.text} />} value={km(total.meters)} label="Total Distance" />
          <Figure icon={<Clock size={24} color={colors.text} />} value={hrMin(total.seconds)} label="Total Travel" />
          <Figure icon={<School size={24} color={colors.text} />} value={hrMin((itinerary?.totals?.visitMinutes ?? 0) * 60).replace(' min', ' min')} label="Visit Time" />
          <Figure icon={<CalendarDays size={24} color={colors.text} />} value={String(itinerary?.totals?.selected ?? 0)} label="Visits" />
        </View>
        {tab === 'map' ? (
          <View style={[styles.mapCard, { borderColor: colors.border }]}>
            <RouteMapView scene={scene} onSelect={onSelectSchool} />
          </View>
        ) : null}
        {tab === 'itinerary' ? (
          <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <View style={styles.inline}>
              <ArrowDownUp size={22} color={colors.text} />
              <Text style={[styles.sectionTitle, { color: colors.text }]}>Visit Sequence (Recommended)</Text>
            </View>
            {stops.map((s, i) => {
              const f = legFigures(s.leg);
              const from = i === 0 ? 'From Start' : `From ${i}`;
              const recommended = s.kind === 'recommended';
              const done = s.school?.status === 'completed';
              return (
                <Pressable key={s.school?.schoolId} onPress={() => s.school && onSelectSchool(s.school.schoolId)} style={styles.stop} accessibilityRole="button">
                  <View style={styles.timeline}>
                    <View style={[styles.dot, { backgroundColor: done ? PIN_TONES.completed : recommended ? PIN_TONES.suggested : PIN_TONES.planned }]}>
                      <Text style={styles.dotText}>{s.order}</Text>
                    </View>
                    {i < stops.length - 1 ? <View style={[styles.rail, { backgroundColor: colors.border }]} /> : null}
                  </View>
                  <View style={styles.flex}>
                    <View style={styles.pillRow}>
                      <Text style={[styles.rowTitle, { color: colors.text }]}>{s.school?.name}</Text>
                      <Text style={[styles.pill, done ? styles.pillDone : recommended ? styles.pillRecommended : styles.pillEligible]}>
                        {done ? 'Completed' : recommended ? 'Recommended' : 'Planned'}
                      </Text>
                    </View>
                    <View style={styles.inline}>
                      <Clock size={16} color={colors.textMuted} />
                      <Text style={[styles.rowSub, { color: colors.text }]}>
                        Visit: {s.visitMinutes} min · Arrive {s.arrival}
                      </Text>
                    </View>
                    <View style={styles.inline}>
                      <Car size={16} color={colors.textMuted} />
                      <Text style={[styles.rowSub, { color: colors.text }]}>
                        {f ? `${from}: ${km(f.meters)} • ${hrMin(f.seconds)}${f.road ? '' : ' (straight line)'}` : 'First stop of the day'}
                      </Text>
                    </View>
                    {s.conflict ? <Text style={[styles.rowSub, { color: '#b91c1c' }]}>{s.conflict}</Text> : null}
                  </View>
                  <ChevronRight size={22} color={colors.text} />
                </Pressable>
              );
            })}
            {(itinerary?.unplaced ?? []).map((p) => (
              <Text key={p.schoolId} style={[styles.rowSub, { color: '#92400e' }]}>
                {p.name} has no usable location and is not on the route; it stays on your plan.
              </Text>
            ))}
          </View>
        ) : null}
        {tab === 'options' ? (
          <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Text style={[styles.sectionTitle, { color: colors.text }]}>Keep a school in its place</Text>
            <Text style={[styles.rowSub, { color: colors.textMuted }]}>A kept school stays where it is when the route is worked out again.</Text>
            {stops.map((s) => {
              const id = s.school?.schoolId ?? '';
              const isLocked = locked.has(id);
              return (
                <Pressable key={id} onPress={() => onToggleLock(id)} style={[styles.listRow, { borderColor: colors.border }]} accessibilityRole="switch" accessibilityState={{ checked: isLocked }}>
                  <Lock size={18} color={isLocked ? ROUTE_TEAL : colors.textMuted} />
                  <Text style={[styles.rowTitle, styles.flex, { color: colors.text }]}>
                    {s.order}. {s.school?.name}
                  </Text>
                  <Text style={[styles.rowSub, { color: isLocked ? ROUTE_TEAL : colors.textMuted }]}>{isLocked ? 'Kept' : 'Free'}</Text>
                </Pressable>
              );
            })}
            <View style={styles.buttons}>
              <Pressable onPress={onKeepOrder} disabled={isBusy} style={[styles.outlineWide, styles.flex]} accessibilityRole="button">
                <Text style={styles.outlineText}>Time my order</Text>
              </Pressable>
              <Pressable onPress={onRecalculate} disabled={isBusy} style={[styles.primarySmall, styles.flex]} accessibilityRole="button">
                <Text style={styles.primaryText}>{isBusy ? 'Working…' : 'Recalculate'}</Text>
              </Pressable>
            </View>
            {isFieldDay ? (
              <Pressable onPress={onRefresh} style={styles.outlineWide} accessibilityRole="button">
                <Text style={styles.outlineText}>Refresh completed visits</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <View style={styles.headerRow}>
            <View style={styles.inline}>
              <Star size={22} color="#f59e0b" fill="#f59e0b" />
              <Text style={[styles.sectionTitle, { color: colors.text }]}>Schools Near My Route</Text>
            </View>
            {day.suggestions.length > 1 ? (
              <Pressable onPress={() => setAllNearby(!allNearby)} accessibilityRole="button">
                <Text style={[styles.link, { color: colors.text }]}>{allNearby ? 'Show fewer' : 'View All →'}</Text>
              </Pressable>
            ) : null}
          </View>
          {nearby.length === 0 ? <Text style={[styles.rowSub, { color: colors.textMuted }]}>No eligible schools near this route.</Text> : null}
          {nearby.map((s) => (
            <SuggestionRow key={s.school?.schoolId} s={s} onAdd={() => s.school && onAddToPlan(s.school.schoolId)} onSelect={() => s.school && onSelectSchool(s.school.schoolId)} />
          ))}
        </View>
      </ScrollView>
      <View style={[styles.footer, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <Pressable onPress={onDirections} disabled={!stops.length} style={[styles.outlineWide, styles.flex]} accessibilityRole="button">
          <Navigation size={22} color="#0f172a" fill="#0f172a" />
          <Text style={styles.outlineDark}>Get Directions</Text>
        </Pressable>
        <Pressable onPress={onStartFieldDay} disabled={!stops.length} style={[styles.primarySmall, styles.flex]} accessibilityRole="button">
          <Play size={20} color="#fff" fill="#fff" />
          <Text style={styles.primaryText}>{isFieldDay ? 'Refresh Field Day' : 'Start Field Day'}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  page: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl * 2 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  title: { fontFamily: fonts.bold, fontSize: 24 },
  subtitle: { fontFamily: fonts.regular, fontSize: 15, marginTop: 2 },
  pickers: { flexDirection: 'row', gap: spacing.sm },
  segment: { flexDirection: 'row', borderWidth: 1, borderRadius: radius.md, padding: 4, gap: 4 },
  segmentItem: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, minHeight: 46, borderRadius: radius.sm },
  segmentText: { fontFamily: fonts.semibold, fontSize: 16 },
  notice: { fontFamily: fonts.regular, fontSize: 13, borderWidth: 1, borderRadius: radius.sm, padding: spacing.sm },
  mapCard: { height: 420, borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden' },
  routeCard: {
    position: 'absolute',
    right: 10,
    top: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: '#fff',
    borderRadius: 14,
    paddingVertical: 8,
    paddingHorizontal: 12,
    shadowColor: '#0f172a',
    shadowOpacity: 0.18,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
  routeCardTitle: { fontFamily: fonts.semibold, fontSize: 15, color: '#15803d' },
  routeCardSub: { fontFamily: fonts.semibold, fontSize: 15, color: '#0f172a' },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, gap: spacing.sm },
  figures: { flexDirection: 'row', borderWidth: 1, borderRadius: radius.lg, paddingVertical: spacing.md },
  figure: { flex: 1, alignItems: 'center', gap: 2, paddingHorizontal: 2 },
  figureValue: { fontFamily: fonts.bold, fontSize: 17, textAlign: 'center' },
  figureLabel: { fontFamily: fonts.regular, fontSize: 13, textAlign: 'center' },
  measure: { fontFamily: fonts.regular, fontSize: 12, textAlign: 'center' },
  primary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, backgroundColor: ROUTE_TEAL, minHeight: 56, borderRadius: radius.md },
  primarySmall: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: ROUTE_TEAL, minHeight: 52, borderRadius: radius.md },
  primaryText: { fontFamily: fonts.semibold, fontSize: 17, color: '#fff' },
  listRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, paddingVertical: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth },
  dot: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  dotText: { fontFamily: fonts.bold, fontSize: 15, color: '#fff' },
  rowTitle: { fontFamily: fonts.semibold, fontSize: 16, flexShrink: 1 },
  rowSub: { fontFamily: fonts.regular, fontSize: 14 },
  sectionTitle: { fontFamily: fonts.semibold, fontSize: 18 },
  stop: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md, paddingVertical: spacing.sm },
  timeline: { alignItems: 'center', alignSelf: 'stretch' },
  rail: { width: 2, flex: 1, marginTop: 2 },
  pillRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  pill: { fontFamily: fonts.medium, fontSize: 13, paddingHorizontal: 10, paddingVertical: 3, borderRadius: radius.pill, overflow: 'hidden' },
  pillEligible: { backgroundColor: '#dcfce7', color: '#166534' },
  pillRecommended: { backgroundColor: '#ffedd5', color: '#c2410c' },
  pillDone: { backgroundColor: '#15803d', color: '#fff' },
  pillHigh: { backgroundColor: '#ede9fe', color: '#6d28d9' },
  inline: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 2 },
  banner: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderRadius: radius.lg, padding: spacing.md, borderWidth: 1 },
  bannerOk: { backgroundColor: '#dcfce7', borderColor: '#bbf7d0' },
  bannerWarn: { backgroundColor: '#fffbeb', borderColor: '#fcd34d', flexDirection: 'column', alignItems: 'flex-start' },
  bannerTitle: { fontFamily: fonts.semibold, fontSize: 19, color: '#166534' },
  bannerText: { fontFamily: fonts.regular, fontSize: 14, color: '#0f172a', marginTop: 2 },
  bannerTitleWarn: { fontFamily: fonts.semibold, fontSize: 17, color: '#92400e' },
  bannerTextWarn: { fontFamily: fonts.regular, fontSize: 14, color: '#92400e' },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  link: { fontFamily: fonts.semibold, fontSize: 15 },
  suggestion: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: spacing.sm },
  photo: { width: 84, height: 76, borderRadius: 10, backgroundColor: '#dcfce7', alignItems: 'center', justifyContent: 'center' },
  outline: { borderWidth: 2, borderColor: ROUTE_TEAL, borderRadius: radius.md, paddingHorizontal: 14, minHeight: 44, justifyContent: 'center' },
  outlineWide: { flexDirection: 'row', gap: 8, borderWidth: 1.5, borderColor: '#cbd5e1', borderRadius: radius.md, minHeight: 52, alignItems: 'center', justifyContent: 'center', backgroundColor: '#fff' },
  outlineText: { fontFamily: fonts.semibold, fontSize: 15, color: ROUTE_TEAL },
  outlineDark: { fontFamily: fonts.semibold, fontSize: 17, color: '#0f172a' },
  buttons: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  footer: { flexDirection: 'row', gap: spacing.sm, padding: spacing.md, borderTopWidth: 1 },
});
