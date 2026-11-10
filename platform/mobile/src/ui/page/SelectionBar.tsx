/**
 * The bar a page shows once rows are ticked (partials/activities/
 * selection_bar.html): the count in its pill, what the ticks are, the
 * drawers it opens with them (Reschedule, Cancel, Assign to partner) and
 * Clear. Dark and floating above the page, as on the web.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { PageSelection, PageSelectionAction } from '../../gen/edify/screens/v1/page_pb';
import { fonts, radius, useTheme } from '../../theme';

/** The web's bar: slate-900 at 95%, white words, slate-800 buttons. */
const BAR = { fill: 'rgba(15, 23, 42, 0.95)', button: '#1e293b', border: 'rgba(30, 41, 59, 0.8)', ink: '#ffffff', muted: '#cbd5e1' } as const;

interface SelectionBarProps {
  readonly selection: PageSelection;
  readonly count: number;
  readonly onAction: (action: PageSelectionAction) => void;
  readonly onClear: () => void;
}

export function SelectionBar({ selection, count, onAction, onClear }: SelectionBarProps) {
  const { colors } = useTheme();
  return (
    <View style={styles.bar} accessibilityRole="toolbar" accessibilityLabel={`${count} ${selection.noun}`}>
      <View style={styles.count} accessibilityLiveRegion="polite">
        <View style={[styles.pill, { backgroundColor: colors.primary }]}>
          <Text style={styles.pillText}>{count}</Text>
        </View>
        <Text style={styles.noun} numberOfLines={1}>
          {selection.noun}
        </Text>
      </View>
      <View style={styles.actions}>
        {selection.actions.map((action) => (
          <BarButton key={action.href} label={action.label} onPress={() => onAction(action)} />
        ))}
        <BarButton label="Clear" onPress={onClear} />
      </View>
    </View>
  );
}

function BarButton({ label, onPress }: { readonly label: string; readonly onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={({ pressed }) => [styles.button, pressed && styles.pressed]}
      hitSlop={4}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  bar: {
    position: 'absolute',
    left: 12,
    right: 12,
    bottom: 12,
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingHorizontal: 8,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: BAR.border,
    backgroundColor: BAR.fill,
    boxShadow: '0px 10px 15px -3px rgba(0, 0, 0, 0.25)',
  },
  count: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  pill: { minWidth: 24, height: 24, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6 },
  pillText: { fontFamily: fonts.semibold, fontSize: 11, color: BAR.ink },
  noun: { fontFamily: fonts.semibold, fontSize: 12, color: BAR.muted },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  button: { height: 32, paddingHorizontal: 12, borderRadius: radius.sm, backgroundColor: BAR.button, alignItems: 'center', justifyContent: 'center' },
  pressed: { opacity: 0.8 },
  buttonText: { fontFamily: fonts.bold, fontSize: 12, color: BAR.ink },
});
