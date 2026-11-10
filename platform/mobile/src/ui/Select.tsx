/**
 * The web app's select fields: the small centred filter selects of a page's
 * filter bar, and the larger form selects inside drawers. Pressing one drops
 * its choices down below the field (see Dropdown).
 */
import { Pressable, StyleSheet, Text } from 'react-native';
import { ChevronDown, ChevronUp } from 'lucide-react-native';

import { fonts, radius, useTheme } from '../theme';
import { Dropdown, MenuList, menuHeight, useDropdown } from './Dropdown';

export interface Choice {
  readonly value: string;
  readonly label: string;
  /** Listed but not choosable, as a disabled option on the web. */
  readonly disabled?: boolean;
}

interface SelectProps {
  readonly label: string;
  readonly value: string;
  readonly choices: readonly Choice[];
  /** Shown when nothing is chosen, e.g. "All". */
  readonly placeholder: string;
  /** Whether the list starts with the empty "nothing chosen" choice; a web
   * select without one (a school's partner type) has none. */
  readonly hasEmptyChoice?: boolean;
  readonly onChange: (value: string) => void;
  /** `filter`: 32px, centred, 12px text; `form`: 40px drawer field. */
  readonly variant?: 'filter' | 'form';
  /** Greyed and not pressable, as the web's Sub-county before a District. */
  readonly isDisabled?: boolean;
  /** On the card colour (a profile's year filter) instead of the field colour. */
  readonly isRaised?: boolean;
}

/** The web's menus are at least this wide, even under a narrow field. */
const MIN_MENU_WIDTH = 176;

export function Select({
  label,
  value,
  choices,
  placeholder,
  onChange,
  variant = 'form',
  isDisabled = false,
  isRaised = false,
  hasEmptyChoice = true,
}: SelectProps) {
  const { colors } = useTheme();
  const options: readonly Choice[] = hasEmptyChoice ? [{ value: '', label: placeholder }, ...choices] : choices;
  const dropdown = useDropdown(menuHeight(options.length));
  const selected = choices.find((choice) => choice.value === value);
  const isFilter = variant === 'filter';
  const Chevron = dropdown.isOpen ? ChevronUp : ChevronDown;

  return (
    <>
      <Pressable
        ref={dropdown.triggerRef}
        onPress={dropdown.toggle}
        disabled={isDisabled}
        accessibilityRole="button"
        accessibilityLabel={`${label}: ${selected?.label ?? placeholder}`}
        accessibilityState={{ expanded: dropdown.isOpen, disabled: isDisabled }}
        style={[
          isFilter ? styles.filter : styles.form,
          {
            backgroundColor: isDisabled ? colors.surfaceMuted : isRaised ? colors.raised : colors.surface,
            borderColor: dropdown.isOpen ? colors.primary : isFilter ? colors.border : colors.fieldBorder,
          },
        ]}
      >
        <Text
          style={[
            isFilter ? styles.filterText : styles.formText,
            { color: isDisabled ? colors.textSubtle : colors.text },
          ]}
          numberOfLines={1}
        >
          {selected?.label ?? placeholder}
        </Text>
        <Chevron size={isFilter ? 12 : 16} color={colors.textSubtle} />
      </Pressable>
      <Dropdown
        anchor={dropdown.anchor}
        onClose={dropdown.close}
        align="stretch"
        minWidth={MIN_MENU_WIDTH}
        contentStyle={styles.menu}
        accessibilityLabel={`${label} choices`}
      >
        <MenuList
          onClose={dropdown.close}
          items={options.map((choice) => ({
            key: choice.value || 'none',
            label: choice.label,
            isDisabled: choice.disabled,
            isSelected: choice.value === value,
            onPress: () => onChange(choice.value),
          }))}
        />
      </Dropdown>
    </>
  );
}

const styles = StyleSheet.create({
  filter: {
    height: 32,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingLeft: 8,
    paddingRight: 6,
  },
  filterText: { flex: 1, fontFamily: fonts.medium, fontSize: 12, textAlign: 'center' },
  form: {
    minHeight: 40,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingLeft: 12,
    paddingRight: 10,
  },
  formText: { flex: 1, fontFamily: fonts.medium, fontSize: 16 },
  menu: { padding: 4 },
});
