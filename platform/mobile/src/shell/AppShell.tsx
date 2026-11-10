/**
 * The app frame: Edify's top bar and bottom navigation, as on the web app's
 * phone layout. The bottom bar's destinations and icons are the reader's own,
 * built by the existing application for their role.
 */
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Bell, Menu, MessageCircleMore, Moon, Search, Sun } from 'lucide-react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { NavItem } from '../gen/edify/screens/v1/navigation_pb';
import { fonts, radius, sizes, spacing, type, useTheme } from '../theme';
import { SvgIcon } from '../ui/SvgIcon';

/** The path that stands for the menu behind "More". */
export const MENU_URL = 'app:menu';

const ICON_SIZE = 22;
const TOPBAR_ICON = 20;
const ACTIVE_MARK_WIDTH = 42;

interface AppShellProps {
  readonly bottom: readonly NavItem[];
  /** The path being shown, or MENU_URL. */
  readonly activeUrl: string;
  readonly onOpen: (url: string, label: string) => void;
  readonly initials: string;
  readonly onSearch: () => void;
  readonly children: ReactNode;
}

function pathOf(url: string): string {
  return url.split(/[?#]/)[0].replace(/\/+$/, '') || '/';
}

export function AppShell({ bottom, activeUrl, onOpen, initials, onSearch, children }: AppShellProps) {
  const { colors, isDark, toggle } = useTheme();
  const insets = useSafeAreaInsets();
  const active = pathOf(activeUrl);
  const inBar = bottom.some((item) => pathOf(item.url) === active);

  return (
    <View style={[styles.frame, { backgroundColor: colors.bg }]}>
      <View
        style={[
          styles.topbar,
          {
            paddingTop: insets.top,
            height: sizes.topbar + insets.top,
            backgroundColor: colors.topbar,
            borderBottomColor: colors.border,
          },
        ]}
      >
        <Pressable
          onPress={onSearch}
          style={[styles.round, { backgroundColor: colors.primary }]}
          accessibilityRole="button"
          accessibilityLabel="Search"
        >
          <Search size={18} color={colors.primaryInk} />
        </Pressable>
        <View style={styles.topbarRight}>
          <Pressable
            onPress={() => onOpen('/messages', 'Messages')}
            style={styles.control}
            accessibilityRole="button"
            accessibilityLabel="Messages"
          >
            <MessageCircleMore size={TOPBAR_ICON} color={colors.textMuted} />
          </Pressable>
          <Pressable
            onPress={() => onOpen('/notifications', 'Notification centre')}
            style={styles.control}
            accessibilityRole="button"
            accessibilityLabel="Notifications"
          >
            <Bell size={TOPBAR_ICON} color={colors.textMuted} />
          </Pressable>
          <Pressable
            onPress={toggle}
            style={styles.control}
            accessibilityRole="button"
            accessibilityLabel={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {isDark ? (
              <Sun size={TOPBAR_ICON} color={colors.textMuted} />
            ) : (
              <Moon size={TOPBAR_ICON} color={colors.textMuted} />
            )}
          </Pressable>
          <Pressable
            onPress={() => onOpen(MENU_URL, 'More')}
            style={[styles.round, { backgroundColor: colors.primary }]}
            accessibilityRole="button"
            accessibilityLabel="Your account"
          >
            <Text style={[styles.initials, { color: colors.primaryInk }]}>{initials}</Text>
          </Pressable>
        </View>
      </View>

      <View style={styles.content}>{children}</View>

      <View
        accessibilityRole="tablist"
        style={[
          styles.bottomNav,
          {
            paddingBottom: insets.bottom,
            height: sizes.bottomNav + insets.bottom,
            backgroundColor: colors.card,
            borderTopColor: colors.border,
          },
        ]}
      >
        {bottom.map((item) => {
          const isActive = pathOf(item.url) === active;
          const tint = isActive ? colors.primary : colors.textMuted;
          return (
            <Pressable
              key={item.url}
              onPress={() => onOpen(item.url, item.label)}
              style={styles.tab}
              accessibilityRole="tab"
              accessibilityLabel={item.label}
              accessibilityState={{ selected: isActive }}
            >
              <View style={[styles.activeMark, isActive && { backgroundColor: colors.primary }]} />
              <SvgIcon xml={item.iconSvg} size={ICON_SIZE} color={tint} />
              <Text style={[styles.tabLabel, { color: tint }]} numberOfLines={1}>
                {item.label}
              </Text>
            </Pressable>
          );
        })}
        <Pressable
          onPress={() => onOpen(MENU_URL, 'More')}
          style={styles.tab}
          accessibilityRole="tab"
          accessibilityLabel="More"
          accessibilityState={{ selected: !inBar }}
        >
          <View style={[styles.activeMark, !inBar && { backgroundColor: colors.primary }]} />
          <Menu size={ICON_SIZE} color={inBar ? colors.textMuted : colors.primary} />
          <Text style={[styles.tabLabel, { color: inBar ? colors.textMuted : colors.primary }]}>More</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { flex: 1 },
  topbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    borderBottomWidth: 1,
  },
  topbarRight: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  control: { width: sizes.control, height: sizes.control, alignItems: 'center', justifyContent: 'center' },
  round: {
    width: sizes.control,
    height: sizes.control,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  initials: { fontFamily: fonts.semibold, fontSize: type.body },
  content: { flex: 1 },
  bottomNav: { flexDirection: 'row', borderTopWidth: 1 },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 2 },
  activeMark: {
    position: 'absolute',
    top: 0,
    height: 2,
    width: ACTIVE_MARK_WIDTH,
    backgroundColor: 'transparent',
  },
  tabLabel: { fontFamily: fonts.semibold, fontSize: type.body },
});
