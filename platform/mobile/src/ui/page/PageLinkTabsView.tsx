/**
 * Tabs that are links (My Plan's This Week … This FY) as the web draws them
 * on a phone: the segment rail with two tabs showing — the first and the
 * open one — the rest under "More n", and the link beside the rail (Open
 * Calendar, a square calendar button).
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CalendarDays, ChevronDown, ChevronUp } from 'lucide-react-native';

import type { PageLinkTabs } from '../../gen/edify/screens/v1/page_pb';
import { fonts, radius, useTheme } from '../../theme';
import { Dropdown, MenuList, menuHeight, useDropdown } from '../Dropdown';
import { railTabs } from './pageLinks';
import { usePageLink } from './shared';

export function PageLinkTabsView({ tabs }: { readonly tabs: PageLinkTabs }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const { shown, rest } = railTabs(tabs.tabs);
  const more = useDropdown(menuHeight(rest.length, 'compact'));
  return (
    <View style={styles.row}>
      <View style={[styles.rail, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]} accessibilityRole="tablist">
        {shown.map((tab, index) => (
          <Pressable
            key={tab.href}
            onPress={() => openLink(tab.href)}
            accessibilityRole="tab"
            accessibilityState={{ selected: tab.active }}
            style={[
              styles.tab,
              tab.active && { backgroundColor: colors.segmentActive },
              index === 0 && styles.first,
            ]}
          >
            <Text style={[styles.tabText, tab.active ? styles.tabOn : { color: colors.text }]} numberOfLines={1}>
              {tab.label}
            </Text>
          </Pressable>
        ))}
        {rest.length > 0 ? (
          <Pressable
            ref={more.triggerRef}
            onPress={more.toggle}
            accessibilityRole="button"
            accessibilityLabel={`More tabs, ${rest.length}`}
            accessibilityState={{ expanded: more.isOpen }}
            style={styles.tab}
          >
            <View style={styles.moreLine}>
              <Text style={[styles.tabText, { color: colors.text }]}>More</Text>
              <View style={[styles.count, { backgroundColor: colors.border }]}>
                <Text style={[styles.countText, { color: colors.text }]}>{rest.length}</Text>
              </View>
              {more.isOpen ? <ChevronUp size={14} color={colors.text} /> : <ChevronDown size={14} color={colors.text} />}
            </View>
          </Pressable>
        ) : null}
      </View>
      {tabs.beside ? (
        <Pressable
          onPress={() => tabs.beside && openLink(tabs.beside.href)}
          accessibilityRole="button"
          accessibilityLabel={tabs.beside.label}
          style={[styles.beside, { backgroundColor: colors.primary }]}
        >
          <CalendarDays size={16} color={colors.primaryInk} />
        </Pressable>
      ) : null}
      <Dropdown
        anchor={more.anchor}
        onClose={more.close}
        align="end"
        minWidth={176}
        panelStyle={styles.panel}
        contentStyle={styles.menu}
        accessibilityLabel="More tabs"
      >
        <MenuList
          variant="compact"
          onClose={more.close}
          items={rest.map((tab) => ({ key: tab.href, label: tab.label, onPress: () => openLink(tab.href) }))}
        />
      </Dropdown>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  rail: { flexDirection: 'row', alignItems: 'center', flexShrink: 1, borderWidth: 1, borderRadius: radius.sm },
  tab: { height: 36, paddingHorizontal: 16, justifyContent: 'center' },
  first: { borderTopLeftRadius: radius.sm - 1, borderBottomLeftRadius: radius.sm - 1 },
  tabText: { fontFamily: fonts.semibold, fontSize: 12 },
  tabOn: { fontFamily: fonts.bold, color: '#ffffff' },
  moreLine: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  count: { borderRadius: radius.pill, paddingHorizontal: 7, paddingVertical: 1 },
  countText: { fontFamily: fonts.semibold, fontSize: 12 },
  beside: { width: 36, height: 32, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  panel: { borderRadius: 10 },
  menu: { padding: 4 },
});
