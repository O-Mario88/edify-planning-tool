/**
 * Buttons that filter the page's rows on the device, as the web's chip rails
 * do in the browser (To-Do's categories and priorities): drawn as the
 * segment rail, the first and the chosen chip showing, the rest under More.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ChevronDown, ChevronUp } from 'lucide-react-native';

import type { PageChip, PageChips } from '../../gen/edify/screens/v1/page_pb';
import { fonts, radius, useTheme } from '../../theme';
import { Dropdown, MenuList, menuHeight, useDropdown } from '../Dropdown';
import { useChips } from './shared';

/** The chips a phone's rail shows: the first and the chosen one. */
function railChips(chips: readonly PageChip[], chosen: string): { shown: PageChip[]; rest: PageChip[] } {
  const open = chips.findIndex((chip) => chip.value === chosen);
  const keep = new Set([0, open > 0 ? open : 1]);
  return { shown: chips.filter((_, i) => keep.has(i)), rest: chips.filter((_, i) => !keep.has(i)) };
}

export function PageChipsView({ chips }: { readonly chips: PageChips }) {
  const { colors } = useTheme();
  const { chosen, choose } = useChips();
  const value = chosen[chips.name] ?? chips.value;
  const { shown, rest } = railChips(chips.chips, value);
  const more = useDropdown(menuHeight(rest.length, 'compact'));
  return (
    <View style={[styles.rail, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]} accessibilityRole="tablist" accessibilityLabel={chips.label}>
      {shown.map((chip, index) => {
        const isOn = chip.value === value;
        return (
          <Pressable
            key={chip.value}
            onPress={() => choose(chips.name, chip.value)}
            accessibilityRole="tab"
            accessibilityState={{ selected: isOn }}
            style={[styles.chip, isOn && { backgroundColor: colors.segmentActive }, index === 0 && styles.first]}
          >
            <Text numberOfLines={1} style={[styles.text, isOn ? styles.on : { color: colors.text }]}>
              {chip.label}
              {chip.count ? ` ${chip.count}` : ''}
            </Text>
          </Pressable>
        );
      })}
      {rest.length > 0 ? (
        <Pressable
          ref={more.triggerRef}
          onPress={more.toggle}
          accessibilityRole="button"
          accessibilityLabel={`More ${chips.label}, ${rest.length}`}
          accessibilityState={{ expanded: more.isOpen }}
          style={styles.chip}
        >
          <View style={styles.moreLine}>
            <Text style={[styles.text, { color: colors.text }]}>More</Text>
            <View style={[styles.count, { backgroundColor: colors.border }]}>
              <Text style={[styles.countText, { color: colors.text }]}>{rest.length}</Text>
            </View>
            {more.isOpen ? <ChevronUp size={14} color={colors.text} /> : <ChevronDown size={14} color={colors.text} />}
          </View>
        </Pressable>
      ) : null}
      <Dropdown anchor={more.anchor} onClose={more.close} align="end" minWidth={176} panelStyle={styles.panel} contentStyle={styles.menu} accessibilityLabel={`More ${chips.label}`}>
        <MenuList
          variant="compact"
          onClose={more.close}
          items={rest.map((chip) => ({
            key: chip.value,
            label: chip.label,
            count: chip.count || undefined,
            onPress: () => choose(chips.name, chip.value),
          }))}
        />
      </Dropdown>
    </View>
  );
}

const styles = StyleSheet.create({
  rail: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', maxWidth: '100%', borderWidth: 1, borderRadius: radius.sm },
  chip: { height: 36, paddingHorizontal: 14, justifyContent: 'center', flexShrink: 1 },
  first: { borderTopLeftRadius: radius.sm - 1, borderBottomLeftRadius: radius.sm - 1 },
  text: { fontFamily: fonts.semibold, fontSize: 12 },
  on: { fontFamily: fonts.bold, color: '#ffffff' },
  moreLine: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  count: { borderRadius: radius.pill, paddingHorizontal: 7, paddingVertical: 1 },
  countText: { fontFamily: fonts.semibold, fontSize: 12 },
  panel: { borderRadius: 10 },
  menu: { padding: 4 },
});
