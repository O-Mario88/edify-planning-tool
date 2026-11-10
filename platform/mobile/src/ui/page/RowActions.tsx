/**
 * A table row's actions as the web draws them (partials/my_plan/
 * activity_row.html): the row's own button (Complete, Enter SSA) and its
 * Actions menu, which opens at the button and drops down. What an action
 * opens is the screen's to decide (PageLinkContext).
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ChevronDown, ChevronUp } from 'lucide-react-native';

import type { PageAction } from '../../gen/edify/screens/v1/page_pb';
import { fonts, radius, useTheme } from '../../theme';
import { Dropdown, MenuList, menuHeight, useDropdown } from '../Dropdown';
import { usePageLink } from './shared';

export function RowActions({ actions, label }: { readonly actions: readonly PageAction[]; readonly label: string }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const buttons = actions.filter((action) => action.key === 'button');
  const items = actions.filter((action) => action.key !== 'button');
  const menu = useDropdown(menuHeight(items.length));
  return (
    <View style={styles.cell}>
      {buttons.map((action) => (
        <Pressable
          key={action.href}
          onPress={() => openLink(action.href, action.drawer)}
          disabled={!action.enabled}
          accessibilityRole="button"
          accessibilityHint={action.reason || undefined}
          style={[styles.button, { backgroundColor: colors.primary, opacity: action.enabled ? 1 : 0.5 }]}
        >
          <Text style={[styles.buttonText, { color: colors.primaryInk }]}>{action.label}</Text>
        </Pressable>
      ))}
      {items.length > 0 ? (
        <Pressable
          ref={menu.triggerRef}
          onPress={menu.toggle}
          accessibilityRole="button"
          accessibilityLabel={`Actions for ${label}`}
          accessibilityState={{ expanded: menu.isOpen }}
          hitSlop={6}
          style={[
            styles.trigger,
            menu.isOpen
              ? { borderColor: colors.primary, backgroundColor: colors.primarySoft }
              : { borderColor: colors.outlineBorder, backgroundColor: colors.raised },
          ]}
        >
          <Text style={[styles.triggerText, { color: colors.link }]}>Actions</Text>
          {menu.isOpen ? <ChevronUp size={14} color={colors.link} /> : <ChevronDown size={14} color={colors.link} />}
        </Pressable>
      ) : null}
      <Dropdown
        anchor={menu.anchor}
        onClose={menu.close}
        align="end"
        minWidth={176}
        contentStyle={styles.menu}
        accessibilityLabel={`Actions for ${label}`}
      >
        <MenuList
          onClose={menu.close}
          items={items.map((action) => ({
            key: action.href,
            label: action.label,
            isDisabled: !action.enabled,
            reason: action.reason || undefined,
            isDanger: action.key === 'danger',
            onPress: () => openLink(action.href, action.drawer),
          }))}
        />
      </Dropdown>
    </View>
  );
}

const styles = StyleSheet.create({
  cell: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 6 },
  button: { height: 24, borderRadius: radius.sm, paddingHorizontal: 8, alignItems: 'center', justifyContent: 'center' },
  buttonText: { fontFamily: fonts.semibold, fontSize: 12 },
  trigger: { flexDirection: 'row', alignItems: 'center', gap: 4, height: 24, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 8 },
  triggerText: { fontFamily: fonts.semibold, fontSize: 12 },
  menu: { padding: 4 },
});
