/**
 * A page's filter bar on a phone: as many selects as the row holds (three;
 * two on a narrow phone, so a value such as "All quarters" is never cut,
 * as the web's phone row does, PhoneFilters.inRowFor) and the rest under More, a dropdown of labelled selects, as the web's
 * micro-ux.js does with its filter toolbars. A change reports the select's
 * name and value; the form's hidden values go with every change.
 */
import { Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { ChevronDown, ChevronUp } from 'lucide-react-native';

import type { PageFilter, PageFilters } from '../../gen/edify/screens/v1/page_pb';
import { fonts, radius, useTheme } from '../../theme';
import { Dropdown, useDropdown } from '../Dropdown';
import { Select } from '../Select';
import { PAGE_GUTTERS, inRowFor } from './filterRow';


const MORE_WIDTH = 272;
/** One labelled select in the More panel, and the panel's padding. */
const MORE_FIELD_HEIGHT = 56;
const MORE_PADDING = 28;

interface PageFilterBarProps {
  readonly filters: PageFilters;
  /** A select changed: its name, its new value, and the form's hidden values. */
  readonly onFilter: (name: string, value: string, hidden: Readonly<Record<string, string>>) => void;
  /** On the card colour (a profile) instead of the field colour (My Plan). */
  readonly isRaised?: boolean;
}

export function PageFilterBar({ filters, onFilter, isRaised = false }: PageFilterBarProps) {
  const { colors } = useTheme();
  const { width } = useWindowDimensions();
  const inRow = inRowFor(width - PAGE_GUTTERS);
  const shown = filters.filters.slice(0, inRow);
  const rest = filters.filters.slice(inRow);
  const more = useDropdown(rest.length * MORE_FIELD_HEIGHT + MORE_PADDING);
  const moreSet = rest.filter((filter) => filter.value !== (filter.options[0]?.value ?? '')).length;
  const change = (filter: PageFilter, value: string) => onFilter(filter.name, value, filters.hidden);
  return (
    // The profile's two selects sit 16px apart; a row with More is the
    // toolbar's tighter 6px (both measured on the web at phone width).
    <View style={[styles.row, rest.length === 0 && styles.roomy]}>
      {shown.map((filter) => (
        <View key={filter.name} style={styles.filter}>
          <Text style={[styles.label, { color: colors.textMuted }]} numberOfLines={1}>
            {filter.label}
          </Text>
          <FilterSelect filter={filter} isRaised={isRaised} onChange={(value) => change(filter, value)} />
        </View>
      ))}
      {rest.length > 0 ? (
        <Pressable
          ref={more.triggerRef}
          onPress={more.toggle}
          accessibilityRole="button"
          accessibilityLabel={`More filters${moreSet ? `, ${moreSet} set` : ''}`}
          accessibilityState={{ expanded: more.isOpen }}
          style={[
            styles.moreButton,
            {
              borderColor: more.isOpen ? colors.primary : colors.border,
              backgroundColor: more.isOpen ? colors.surface : colors.raised,
            },
          ]}
        >
          <Text style={[styles.moreText, { color: more.isOpen ? colors.link : colors.text }]}>
            More{moreSet ? ` ${moreSet}` : ''}
          </Text>
          {more.isOpen ? <ChevronUp size={14} color={colors.link} /> : <ChevronDown size={14} color={colors.text} />}
        </Pressable>
      ) : null}
      <Dropdown
        anchor={more.anchor}
        onClose={more.close}
        align="end"
        width={MORE_WIDTH}
        panelStyle={styles.morePanel}
        contentStyle={styles.moreContent}
        accessibilityLabel="More filters"
      >
        {rest.map((filter) => (
          <View key={filter.name} style={styles.moreField}>
            <Text style={[styles.label, { color: colors.textMuted }]}>{filter.label}</Text>
            <FilterSelect filter={filter} onChange={(value) => change(filter, value)} />
          </View>
        ))}
      </Dropdown>
    </View>
  );
}

/** The page lists every choice, its default first; the Select offers that
 * first one as its "nothing chosen" line. */
function FilterSelect({ filter, onChange, isRaised = false }: {
  readonly filter: PageFilter;
  readonly onChange: (value: string) => void;
  readonly isRaised?: boolean;
}) {
  const [first, ...rest] = filter.options;
  const empty = first?.value ?? '';
  return (
    <Select
      variant="filter"
      isRaised={isRaised}
      label={filter.label}
      value={filter.value === empty ? '' : filter.value}
      placeholder={first?.label ?? ''}
      choices={rest.map((option) => ({ value: option.value, label: option.label }))}
      onChange={(value) => onChange(value === '' ? empty : value)}
    />
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-end', gap: 6 },
  roomy: { gap: 16 },
  filter: { flex: 1, gap: 4 },
  label: { fontFamily: fonts.medium, fontSize: 12 },
  moreButton: { height: 32, flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 10 },
  moreText: { fontFamily: fonts.bold, fontSize: 12 },
  morePanel: { borderRadius: 16 },
  moreContent: { padding: 14, gap: 12 },
  moreField: { gap: 6 },
});
