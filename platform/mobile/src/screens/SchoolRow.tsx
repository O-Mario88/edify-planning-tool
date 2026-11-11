/**
 * One School Directory row, as the web's phone list draws it: tick box,
 * School ID pill, name and an Actions button whose menu drops down below
 * it. Pressing the row shows the school's details.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Check, ChevronDown, ChevronUp } from 'lucide-react-native';

import type { DirectorySchool } from '../gen/edify/screens/v1/school_directory_pb';
import { fonts, radius, toneColors, useTheme } from '../theme';
import { Dropdown, MenuList, menuHeight, useDropdown } from '../ui/Dropdown';
import type { MenuEntry } from '../ui/Dropdown';

/** The server's tones for the SSA mark (ssa_average_tone) and badges. */
function badgeTone(tone: string): string {
  switch (tone) {
    case 'success':
    case 'good':
      return 'good';
    case 'warning':
      return 'caution';
    case 'danger':
      return 'alert';
    case 'info':
    case 'primary':
      return 'info';
    default:
      return 'plain';
  }
}


interface SchoolRowProps {
  readonly school: DirectorySchool;
  readonly isOpen: boolean;
  readonly isLast: boolean;
  readonly canAct: boolean;
  readonly isSelected: boolean;
  readonly onSelect: () => void;
  readonly onToggle: () => void;
  /** The row's Actions menu entries, as the web lists them. */
  readonly actions: readonly MenuEntry[];
  /** Opens the school's profile from its name, for a reader it lets in. */
  readonly onOpen?: () => void;
}

export function SchoolRow({
  school,
  isOpen,
  isLast,
  canAct,
  isSelected,
  onSelect,
  onToggle,
  actions,
  onOpen,
}: SchoolRowProps) {
  const { colors } = useTheme();
  const menu = useDropdown(menuHeight(actions.length));
  const visitTone = toneColors(colors, badgeTone(school.visitStatusTone));
  const ssaTone = toneColors(colors, badgeTone(school.ssaTone));
  const trainingColor =
    school.clusterTrainingState === 'positive'
      ? colors.success
      : school.clusterTrainingState === 'attention'
        ? colors.warning
        : colors.text;
  const facts: readonly (readonly [string, string])[] = [
    ['District', school.district],
    ['Shipping Address', school.shippingAddress],
    ['School Type', school.schoolType],
    ['Cluster', school.clusterName],
    ['Enrollment', school.enrolment.toLocaleString()],
    ['Phone', school.phone],
    ['Primary Contact', school.contact],
    ['Staff Name', school.staffName],
  ];
  return (
    <View
      style={[
        styles.row,
        { backgroundColor: menu.isOpen ? colors.primarySoft : colors.raised, borderColor: colors.raisedBorder },
        isLast && styles.rowLast,
      ]}
    >
      <View style={styles.summary}>
        {canAct ? (
          <Pressable
            onPress={onSelect}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: isSelected }}
            accessibilityLabel={`Select ${school.name}`}
            hitSlop={8}
          >
            <TickBox isChecked={isSelected} />
          </Pressable>
        ) : null}
        <Pressable
          onPress={onToggle}
          accessibilityRole="button"
          accessibilityState={{ expanded: isOpen }}
          accessibilityLabel={`${isOpen ? 'Hide' : 'Show'} details for ${school.name}, School ID ${school.schoolId}`}
          style={[styles.summaryTap, onOpen ? null : styles.grow]}
        >
          <View style={[styles.idPill, { borderColor: colors.borderStrong, backgroundColor: colors.surfaceMuted }]}>
            <Text style={[styles.idText, { color: colors.text }]}>{school.schoolId}</Text>
          </View>
          {onOpen ? null : <Name school={school} isOpen={isOpen} />}
        </Pressable>
        {onOpen ? (
          // The name is a link to the profile, as on the web; the rest of the
          // row shows its details. Siblings, not nested, so each takes its tap.
          <Pressable
            onPress={onOpen}
            accessibilityRole="link"
            accessibilityLabel={`Open ${school.name}'s profile`}
            style={styles.nameLink}
          >
            <Name school={school} isOpen={isOpen} />
          </Pressable>
        ) : null}
        {canAct && actions.length > 0 ? (
          <Pressable
            ref={menu.triggerRef}
            onPress={menu.toggle}
            accessibilityRole="button"
            accessibilityLabel={`Actions for ${school.name}`}
            accessibilityState={{ expanded: menu.isOpen }}
            hitSlop={6}
            style={[
              styles.actions,
              menu.isOpen
                ? { borderColor: colors.primary, backgroundColor: colors.primarySoft }
                : { borderColor: colors.outlineBorder, backgroundColor: colors.raised },
            ]}
          >
            <Text style={[styles.actionsText, { color: colors.link }]}>Actions</Text>
            {menu.isOpen ? <ChevronUp size={14} color={colors.link} /> : <ChevronDown size={14} color={colors.link} />}
          </Pressable>
        ) : null}
      </View>
      {isOpen ? (
        <View style={[styles.details, { borderTopColor: colors.raisedBorder }]}>
          {facts.map(([label, value]) => (
            <View key={label} style={styles.fact}>
              <Text style={[styles.factLabel, { color: colors.textSubtle }]}>{label}:</Text>
              <Text style={[styles.factValue, { color: colors.link }]}>{value}</Text>
            </View>
          ))}
          <View style={styles.fact}>
            <Text style={[styles.factLabel, { color: colors.textSubtle }]}>SSA:</Text>
            <Text style={[styles.factValue, { color: school.ssaAverage !== undefined ? ssaTone.fg : colors.text }]}>
              {school.ssaAverage !== undefined ? `${Number(school.ssaAverage.toFixed(1))}/10` : 'Not assessed'}
            </Text>
          </View>
          <View style={styles.fact}>
            <Text style={[styles.factLabel, { color: colors.textSubtle }]}>Visit status:</Text>
            <View style={[styles.badge, { backgroundColor: visitTone.soft }]}>
              <Text style={[styles.badgeText, { color: visitTone.fg }]}>{school.visitStatusLabel}</Text>
            </View>
            {school.nextVisitDate ? (
              <Text style={[styles.caption, { color: colors.textSubtle }]}>
                {new Date(`${school.nextVisitDate}T00:00:00`).toLocaleDateString('en-GB', {
                  day: 'numeric',
                  month: 'short',
                  year: 'numeric',
                })}
              </Text>
            ) : null}
          </View>
          <View style={styles.fact}>
            <Text style={[styles.factLabel, { color: colors.textSubtle }]}>Cluster training:</Text>
            <Text style={[styles.factValue, { color: trainingColor }]}>
              {school.clusterTrainingLabel}
              {school.clusterTrainingReason ? (
                <Text style={[styles.caption, { color: colors.textSubtle }]}> {school.clusterTrainingReason}</Text>
              ) : null}
            </Text>
          </View>
          <View style={styles.fact}>
            <Text style={[styles.factLabel, { color: colors.textSubtle }]}>Visit:</Text>
            <Text style={[styles.factValue, { color: school.visitCount ? colors.success : colors.warning }]}>
              {school.visitCount}
            </Text>
            <Text style={[styles.factLabel, styles.factGap, { color: colors.textSubtle }]}>Training:</Text>
            <Text style={[styles.factValue, { color: school.trainingCount ? colors.success : colors.warning }]}>
              {school.trainingCount}
            </Text>
          </View>
          {school.ssaGroups
            .filter((group) => group.items.length > 0)
            .map((group) => {
              const tone = toneColors(colors, badgeTone(group.tone));
              return (
                <View key={group.key} style={[styles.ssaGroup, { borderColor: colors.raisedBorder }]}>
                  <Text style={[styles.ssaTitle, { color: tone.fg }]}>{group.title}</Text>
                  {group.items.map((item) => {
                    const band = toneColors(colors, badgeTone(item.bandTone));
                    return (
                      <View key={item.label} style={styles.ssaItem}>
                        <Text style={[styles.factValue, styles.ssaLabel, { color: colors.text }]}>{item.label}</Text>
                        <Text style={[styles.factValue, { color: colors.text }]}>{item.score.toFixed(1)}</Text>
                        <View style={[styles.badge, { backgroundColor: band.soft }]}>
                          <Text style={[styles.badgeText, { color: band.fg }]}>{item.band}</Text>
                        </View>
                      </View>
                    );
                  })}
                </View>
              );
            })}
        </View>
      ) : null}
      <Dropdown
        anchor={menu.anchor}
        onClose={menu.close}
        align="end"
        minWidth={176}
        contentStyle={styles.menu}
        accessibilityLabel={`Actions for ${school.name}`}
      >
        <MenuList items={actions} onClose={menu.close} />
      </Dropdown>
    </View>
  );
}

function Name({ school, isOpen }: { readonly school: DirectorySchool; readonly isOpen: boolean }) {
  const { colors } = useTheme();
  return (
    <Text style={[styles.name, { color: colors.text }]} numberOfLines={isOpen ? 3 : 1}>
      {school.name}
    </Text>
  );
}

export function TickBox({ isChecked }: { readonly isChecked: boolean }) {
  const { colors } = useTheme();
  return (
    <View
      style={[
        styles.tick,
        { borderColor: isChecked ? colors.primary : colors.borderStrong, backgroundColor: isChecked ? colors.primary : colors.raised },
      ]}
    >
      {isChecked ? <Check size={12} color={colors.primaryInk} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { borderLeftWidth: 1, borderRightWidth: 1, borderTopWidth: 1 },
  rowLast: { borderBottomWidth: 1, borderBottomLeftRadius: radius.lg, borderBottomRightRadius: radius.lg },
  summary: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 37, paddingHorizontal: 12, paddingVertical: 6 },
  summaryTap: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 32 },
  // Only while the name sits inside this button; with a name link the
  // button keeps the pill's own width (web reads flex: 0 as zero width).
  grow: { flex: 1 },
  nameLink: { flex: 1, minHeight: 32, flexDirection: 'row', alignItems: 'center' },
  idPill: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 1, minWidth: 44, alignItems: 'center' },
  idText: { fontFamily: fonts.semibold, fontSize: 12 },
  name: { flex: 1, fontFamily: fonts.semibold, fontSize: 12 },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    height: 24,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
  },
  actionsText: { fontFamily: fonts.semibold, fontSize: 12 },
  details: { borderTopWidth: 1, paddingHorizontal: 16, paddingVertical: 12, gap: 6 },
  fact: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6 },
  factLabel: { fontFamily: fonts.medium, fontSize: 12 },
  factGap: { marginLeft: 12 },
  factValue: { fontFamily: fonts.semibold, fontSize: 12, flexShrink: 1 },
  caption: { fontFamily: fonts.regular, fontSize: 12 },
  badge: { borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 1 },
  badgeText: { fontFamily: fonts.medium, fontSize: 12 },
  ssaGroup: { borderWidth: 1, borderRadius: radius.md, padding: 10, gap: 6, marginTop: 6 },
  ssaTitle: { fontFamily: fonts.bold, fontSize: 12 },
  ssaItem: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  ssaLabel: { flex: 1 },
  tick: { width: 18, height: 18, borderWidth: 1, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  menu: { padding: 4 },
});
