/**
 * Dropdowns as the web app draws them: the panel opens at its button and
 * drops down below it, never flipped up over the button and never from a
 * fixed spot on the screen (owner rule, 2026-09-27). Near the foot of the
 * screen the page scrolls up to make room; if it still runs short, the panel
 * scrolls inside itself. It stays clear of the bottom navigation.
 */
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { ComponentRef, ReactNode } from 'react';
import { Animated, BackHandler, Easing, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';
import { Check } from 'lucide-react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { fonts, useTheme } from '../theme';
import { placePanel, roomToMake } from './dropdownPlacement';
import type { Anchor } from './dropdownPlacement';

export type { Anchor } from './dropdownPlacement';

/**
 * Scrolls the screen a dropdown sits in up by the given pixels, so the
 * panel has room to drop down. Screens and drawers that scroll provide it.
 */
export type MakeRoom = (pixels: number) => void;
export const MakeRoomContext = createContext<MakeRoom | null>(null);

/** Time for a scroll to land before the button is measured again. */
const SETTLE_MS = 60;
const OPEN_MS = 140;

type ViewRef = ComponentRef<typeof View>;

function measure(view: ViewRef | null): Promise<Anchor | null> {
  return new Promise((resolve) => {
    if (!view) {
      resolve(null);
      return;
    }
    view.measureInWindow((x, y, width, height) => resolve({ x, y, width, height }));
  });
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * The layer dropdown panels are drawn in. It covers its window (the app, or a
 * drawer), and buttons and the layer are measured in that same window, so a
 * panel lands under its button on every platform. (A separate pop-up window
 * was measured from a different origin on Android: one status bar too high.)
 */
interface Layer {
  readonly frame: Anchor;
  readonly show: (key: string, node: ReactNode) => void;
  readonly hide: (key: string) => void;
}

const LayerContext = createContext<Layer | null>(null);
const NO_FRAME: Anchor = { x: 0, y: 0, width: 0, height: 0 };

export function DropdownLayer({ children }: { readonly children: ReactNode }) {
  const host = useRef<ViewRef>(null);
  const [frame, setFrame] = useState<Anchor>(NO_FRAME);
  const [panels, setPanels] = useState<Readonly<Record<string, ReactNode>>>({});

  const show = useCallback((key: string, node: ReactNode) => {
    setPanels((current) => ({ ...current, [key]: node }));
  }, []);
  const hide = useCallback((key: string) => {
    setPanels((current) => {
      if (!(key in current)) {
        return current;
      }
      const { [key]: _gone, ...rest } = current;
      return rest;
    });
  }, []);
  const layer = useMemo(() => ({ frame, show, hide }), [frame, show, hide]);

  const remeasure = useCallback(() => {
    void measure(host.current).then((rect) => rect && setFrame(rect));
  }, []);

  return (
    <LayerContext.Provider value={layer}>
      <View style={styles.fill}>
        {children}
        <View ref={host} onLayout={remeasure} pointerEvents="box-none" style={styles.layer}>
          {Object.entries(panels).map(([key, node]) => (
            <View key={key} pointerEvents="box-none" style={StyleSheet.absoluteFill}>
              {node}
            </View>
          ))}
        </View>
      </View>
    </LayerContext.Provider>
  );
}

/**
 * Opens and closes one dropdown. `panelHeight` is roughly how tall the panel
 * wants to be; the screen scrolls up when that much room is missing. The
 * anchor is kept in the layer's own coordinates.
 */
export function useDropdown(panelHeight: number) {
  const triggerRef = useRef<ViewRef>(null);
  const makeRoom = useContext(MakeRoomContext);
  const layer = useContext(LayerContext);
  const insets = useSafeAreaInsets();
  const [anchor, setAnchor] = useState<Anchor | null>(null);

  const open = useCallback(async () => {
    const frame = layer?.frame ?? NO_FRAME;
    const local = (rect: Anchor): Anchor => ({ ...rect, x: rect.x - frame.x, y: rect.y - frame.y });
    const first = await measure(triggerRef.current);
    if (!first) {
      return;
    }
    let rect = local(first);
    const screen = { width: frame.width, height: frame.height, bottomInset: insets.bottom };
    const shortBy = roomToMake(rect, panelHeight, screen);
    if (shortBy > 0 && makeRoom) {
      makeRoom(shortBy);
      await wait(SETTLE_MS);
      const again = await measure(triggerRef.current);
      rect = again ? local(again) : rect;
    }
    setAnchor(rect);
  }, [insets.bottom, layer, makeRoom, panelHeight]);

  const close = useCallback(() => setAnchor(null), []);
  const toggle = useCallback(() => {
    if (anchor) {
      setAnchor(null);
    } else {
      void open();
    }
  }, [anchor, open]);

  return { triggerRef, anchor, isOpen: anchor !== null, open, close, toggle };
}

interface DropdownProps {
  readonly anchor: Anchor | null;
  readonly onClose: () => void;
  /**
   * `end` lines the panel's right edge up with the button's (row Actions,
   * More); `start` its left edge; `stretch` makes it the button's width.
   */
  readonly align: 'start' | 'end' | 'stretch';
  readonly width?: number;
  readonly minWidth?: number;
  /** The panel's own look: padding, corner radius, background. */
  readonly panelStyle?: StyleProp<ViewStyle>;
  readonly contentStyle?: StyleProp<ViewStyle>;
  readonly accessibilityLabel: string;
  readonly children: ReactNode;
}

/** Shows the panel in the nearest DropdownLayer while `anchor` is set. */
export function Dropdown(props: DropdownProps) {
  const layer = useContext(LayerContext);
  const key = useId();
  const { anchor, onClose } = props;

  // Re-sent after every render so the panel shows current choices.
  useEffect(() => {
    if (anchor && layer) {
      layer.show(key, <Panel {...props} anchor={anchor} frame={layer.frame} />);
    }
  });
  useEffect(() => {
    if (!anchor || !layer) {
      return undefined;
    }
    const back = BackHandler.addEventListener('hardwareBackPress', () => {
      onClose();
      return true;
    });
    return () => {
      back.remove();
      layer.hide(key);
    };
  }, [anchor, key, layer, onClose]);

  return null;
}

function Panel({
  anchor,
  frame,
  onClose,
  align,
  width,
  minWidth = 0,
  panelStyle,
  contentStyle,
  accessibilityLabel,
  children,
}: DropdownProps & { readonly anchor: Anchor; readonly frame: Anchor }) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const progress = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(progress, {
      toValue: 1,
      duration: OPEN_MS,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [progress]);

  const { top, maxHeight, ...place } = placePanel(
    anchor,
    { width: frame.width, height: frame.height, bottomInset: insets.bottom },
    { align, width, minWidth },
  );

  return (
    <>
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Close menu" />
      <Animated.View
        accessibilityLabel={accessibilityLabel}
        accessibilityViewIsModal
        style={[
          styles.panel,
          place,
          { top, maxHeight, backgroundColor: colors.raised, borderColor: colors.border },
          {
            opacity: progress,
            transform: [{ translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [-4, 0] }) }],
          },
          panelStyle,
        ]}
      >
        <ScrollView bounces={false} contentContainerStyle={contentStyle} keyboardShouldPersistTaps="handled">
          {children}
        </ScrollView>
      </Animated.View>
    </>
  );
}

export interface MenuEntry {
  readonly key: string;
  readonly label: string;
  /** A count shown in a pill beside the label (the web's view tabs). */
  readonly count?: string;
  /** Why a disabled entry cannot be chosen. */
  readonly reason?: string;
  readonly isDisabled?: boolean;
  readonly isSelected?: boolean;
  /** Drawn in red, as the web's row-menu__item--danger (Cancel Activity). */
  readonly isDanger?: boolean;
  readonly onPress: () => void;
}

interface MenuListProps {
  readonly items: readonly MenuEntry[];
  readonly onClose: () => void;
  /** `row`: the web's row-menu (44px entries); `compact`: its 32px view list. */
  readonly variant?: 'row' | 'compact';
}

/** The entries of a dropdown menu, styled as the web's row menu. */
export function MenuList({ items, onClose, variant = 'row' }: MenuListProps) {
  const { colors } = useTheme();
  const isCompact = variant === 'compact';
  return (
    <View accessibilityRole="menu">
      {items.map((item) => (
        <Pressable
          key={item.key}
          disabled={item.isDisabled}
          onPress={() => {
            onClose();
            item.onPress();
          }}
          accessibilityRole="menuitem"
          accessibilityState={{ disabled: item.isDisabled, selected: item.isSelected }}
          style={({ pressed }) => [
            isCompact ? styles.compactItem : styles.item,
            item.reason ? styles.itemWithReason : null,
            (pressed || item.isSelected) && !item.isDisabled ? { backgroundColor: colors.primarySoft } : null,
          ]}
        >
          <View style={styles.itemLine}>
            <Text
              style={[
                styles.itemText,
                { color: item.isDisabled ? colors.textSubtle : item.isDanger ? colors.danger : colors.text },
              ]}
              numberOfLines={2}
            >
              {item.label}
            </Text>
            {item.count !== undefined ? (
              <View style={[styles.pill, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={[styles.pillText, { color: colors.text }]}>{item.count}</Text>
              </View>
            ) : null}
            {item.isSelected ? <Check size={16} color={colors.primary} style={styles.check} /> : null}
          </View>
          {item.reason ? <Text style={[styles.reason, { color: colors.textMuted }]}>{item.reason}</Text> : null}
        </Pressable>
      ))}
    </View>
  );
}

/** Height a MenuList of this many entries wants, for useDropdown. */
export function menuHeight(count: number, variant: 'row' | 'compact' = 'row'): number {
  return count * (variant === 'compact' ? 32 : 44) + 10;
}

/** The web's dropdown panel shadow. */
export const PANEL_SHADOW =
  '0px 28px 70px -34px rgba(18, 74, 112, 0.3), 0px 8px 20px -14px rgba(18, 74, 112, 0.1)';

const styles = StyleSheet.create({
  fill: { flex: 1 },
  /** Above the page, its bars and its sticky headers on every platform. */
  layer: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, zIndex: 1000, elevation: 1000 },
  panel: {
    position: 'absolute',
    borderWidth: 1,
    borderRadius: 12,
    overflow: 'hidden',
    boxShadow: PANEL_SHADOW,
  },
  item: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 10, borderRadius: 10 },
  compactItem: { minHeight: 32, justifyContent: 'center', paddingHorizontal: 12, borderRadius: 8 },
  itemWithReason: { paddingVertical: 6 },
  itemLine: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  itemText: { flexShrink: 1, fontFamily: fonts.semibold, fontSize: 13 },
  pill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  pillText: { fontFamily: fonts.semibold, fontSize: 12 },
  check: { marginLeft: 'auto' },
  reason: { fontFamily: fonts.regular, fontSize: 12, marginTop: 2 },
});
