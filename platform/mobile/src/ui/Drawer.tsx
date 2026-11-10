/**
 * The web app's drawer as it opens on a phone (base_drawer, type-center): a
 * rounded card in the middle of the screen over a dimmed page, growing in
 * from 96% as it fades up. Title and close button on top, the form in a
 * scrolling body, the buttons in a footer.
 */
import { useCallback, useEffect, useRef } from 'react';
import type { ComponentRef, ReactNode } from 'react';
import {
  Animated,
  Easing,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import type { NativeScrollEvent, NativeSyntheticEvent } from 'react-native';
import { X } from 'lucide-react-native';

import { fonts, useTheme } from '../theme';
import { DropdownLayer, MakeRoomContext } from './Dropdown';

/** Card inset from the screen's sides, and its widest size (30rem). */
const SIDE_INSET = 20;
const MAX_WIDTH = 480;
/** The card is never taller than this share of the screen (84svh). */
const MAX_HEIGHT_SHARE = 0.84;
const BACKDROP = 'rgba(28, 44, 68, 0.58)';
const CARD_SHADOW =
  '0px 28px 56px -16px rgba(15, 23, 42, 0.32), 0px 8px 20px -8px rgba(15, 23, 42, 0.16)';
/** The web's drawer easing, cubic-bezier(0.16, 1, 0.3, 1). */
const EASE = Easing.bezier(0.16, 1, 0.3, 1);

interface DrawerProps {
  readonly title: string;
  /** The line under the title, e.g. "1286 · Mukono". */
  readonly subtitle?: string;
  readonly onClose: () => void;
  readonly footer?: ReactNode;
  /** Shows the web's "* Required information" line above the form. */
  readonly hasRequired?: boolean;
  /** Drawn over the card (the "Discard your changes?" prompt). */
  readonly overlay?: ReactNode;
  /** Each new value scrolls the body back to the top, where a refused
   * save's message is drawn. */
  readonly topKey?: number;
  readonly children: ReactNode;
}

export function Drawer({
  title,
  subtitle,
  onClose,
  footer,
  hasRequired = false,
  overlay,
  topKey = 0,
  children,
}: DrawerProps) {
  const { colors } = useTheme();
  const window = useWindowDimensions();
  const fade = useRef(new Animated.Value(0)).current;
  const grow = useRef(new Animated.Value(0)).current;
  const body = useRef<ComponentRef<typeof ScrollView>>(null);
  const offset = useRef(0);

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fade, { toValue: 1, duration: 240, easing: Easing.out(Easing.quad), useNativeDriver: true }),
      Animated.timing(grow, { toValue: 1, duration: 340, easing: EASE, useNativeDriver: true }),
    ]).start();
  }, [fade, grow]);

  useEffect(() => {
    if (topKey === 0) {
      return undefined;
    }
    // After the message is laid out: a scroll started in the same frame is
    // undone when the browser keeps the page anchored as the message appears.
    const frame = requestAnimationFrame(() => body.current?.scrollTo({ y: 0, animated: false }));
    return () => cancelAnimationFrame(frame);
  }, [topKey]);

  const makeRoom = useCallback((pixels: number) => {
    body.current?.scrollTo({ y: offset.current + pixels, animated: false });
  }, []);

  function trackScroll(event: NativeSyntheticEvent<NativeScrollEvent>) {
    offset.current = event.nativeEvent.contentOffset.y;
  }

  const width = Math.min(window.width - SIDE_INSET * 2, MAX_WIDTH);
  return (
    <Modal visible transparent animationType="none" onRequestClose={onClose} statusBarTranslucent navigationBarTranslucent>
      <DropdownLayer>
      <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: BACKDROP, opacity: fade }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Close" />
      </Animated.View>
      <KeyboardAvoidingView
        style={styles.center}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        pointerEvents="box-none"
      >
        <Animated.View
          accessibilityViewIsModal
          style={[
            styles.card,
            {
              width,
              maxHeight: window.height * MAX_HEIGHT_SHARE,
              backgroundColor: colors.raised,
              borderColor: colors.border,
              opacity: fade,
              transform: [
                { translateY: grow.interpolate({ inputRange: [0, 1], outputRange: [window.height * 0.01, 0] }) },
                { scale: grow.interpolate({ inputRange: [0, 1], outputRange: [0.96, 1] }) },
              ],
            },
          ]}
        >
          <View style={styles.head}>
            <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
              {title}
            </Text>
            {subtitle ? <Text style={[styles.subtitle, { color: colors.textMuted }]}>{subtitle}</Text> : null}
            <Pressable
              onPress={onClose}
              accessibilityRole="button"
              accessibilityLabel="Close"
              style={({ pressed }) => [styles.close, pressed ? { backgroundColor: colors.surfaceMuted } : null]}
            >
              <X size={20} color={colors.textMuted} />
            </Pressable>
          </View>
          <MakeRoomContext.Provider value={makeRoom}>
            <ScrollView
              ref={body}
              onScroll={trackScroll}
              scrollEventThrottle={16}
              contentContainerStyle={styles.body}
              keyboardShouldPersistTaps="handled"
            >
              {hasRequired ? (
                <Text style={[styles.required, { color: colors.textMuted }]}>
                  <Text style={{ color: colors.danger }}>* </Text>
                  Required information
                </Text>
              ) : null}
              {children}
            </ScrollView>
          </MakeRoomContext.Provider>
          {footer ? <View style={[styles.footer, { borderTopColor: colors.raisedBorder }]}>{footer}</View> : null}
          {overlay}
        </Animated.View>
      </KeyboardAvoidingView>
      </DropdownLayer>
    </Modal>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  card: { borderWidth: 1, borderRadius: 16, overflow: 'hidden', boxShadow: CARD_SHADOW },
  head: { minHeight: 66, justifyContent: 'center', paddingTop: 12, paddingBottom: 12, paddingLeft: 18, paddingRight: 52 },
  title: { fontFamily: fonts.bold, fontSize: 15, lineHeight: 21 },
  subtitle: { fontFamily: fonts.medium, fontSize: 13, marginTop: 2 },
  close: {
    position: 'absolute',
    top: 15,
    right: 15,
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: { paddingHorizontal: 18, paddingTop: 4, paddingBottom: 16, gap: 16 },
  required: { fontFamily: fonts.medium, fontSize: 13, textAlign: 'right' },
  footer: { flexDirection: 'row', justifyContent: 'flex-end', gap: 10, paddingHorizontal: 18, paddingVertical: 10, borderTopWidth: 1 },
});
