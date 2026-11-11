/**
 * The four figures under the web sign-in (owner, 2026-09-07: schools reached,
 * visited, trained and SSA completed, each out of the whole portfolio, from
 * the database). Four across in the desktop photo panel; two by two, centred,
 * under the card everywhere else, as the web draws them on a phone.
 */
import { StyleSheet, Text, View } from 'react-native';

import { fonts } from '../../theme';
import { gradients, panel, shadows } from './signInLook';

export interface Figures {
  readonly portfolio: string;
  readonly schoolsReached: string;
  readonly schoolsVisited: string;
  readonly schoolsTrained: string;
  readonly ssaCompleted: string;
}

interface SignInFiguresProps {
  readonly figures: Figures;
  readonly layout: 'row' | 'grid';
  readonly micro: number;
}

export function SignInFigures({ figures, layout, micro }: SignInFiguresProps) {
  const facts = [
    { label: 'Schools reached', value: figures.schoolsReached, note: 'Operating schools', isNote: true },
    { label: 'Schools visited', value: figures.schoolsVisited, note: `of ${figures.portfolio}`, isNote: false },
    { label: 'Schools trained', value: figures.schoolsTrained, note: `of ${figures.portfolio}`, isNote: false },
    { label: 'SSA completed', value: figures.ssaCompleted, note: `of ${figures.portfolio}`, isNote: false },
  ];
  const isGrid = layout === 'grid';
  const small = { fontSize: micro, lineHeight: micro * 1.35 };
  return (
    <View style={styles.strip} accessibilityLabel="Performance overview">
      <View style={styles.rows}>
        {facts.map((fact, index) => {
          const isRightColumn = isGrid ? index % 2 === 1 : index > 0;
          const isSecondRow = isGrid && index >= 2;
          return (
            <View
              key={fact.label}
              accessible
              accessibilityLabel={`${fact.label}: ${fact.value}, ${fact.note}`}
              style={[styles.fact, isGrid ? styles.factGrid : styles.factRow, isSecondRow && styles.secondRow]}
            >
              {isRightColumn ? <View style={styles.divider} /> : null}
              <Text style={[styles.label, small, isGrid && styles.centred]} numberOfLines={1}>
                {fact.label}
              </Text>
              <Text style={[styles.value, isGrid && styles.centred]}>{fact.value}</Text>
              <Text style={[fact.isNote ? styles.note : [styles.helper, small], isGrid && styles.centred]}>{fact.note}</Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  strip: {
    borderWidth: 1,
    borderColor: panel.border,
    borderRadius: 10,
    overflow: 'hidden',
    backgroundImage: gradients.panel,
    boxShadow: shadows.figures,
  },
  rows: { flexDirection: 'row', flexWrap: 'wrap' },
  fact: { paddingVertical: 10, paddingHorizontal: 16, gap: 3 },
  factRow: { flex: 1, minWidth: 0 },
  factGrid: { width: '50%' },
  secondRow: { borderTopWidth: 1, borderTopColor: panel.divider },
  divider: { position: 'absolute', left: 0, top: 10, bottom: 10, width: 1, backgroundColor: panel.divider },
  label: { fontFamily: fonts.semibold, color: panel.label },
  value: { fontFamily: fonts.semibold, fontSize: 20, lineHeight: 23, color: '#ffffff' },
  helper: { fontFamily: fonts.medium, color: panel.label },
  note: { fontFamily: fonts.medium, fontSize: 16, lineHeight: 24, color: '#ffffff' },
  centred: { textAlign: 'center' },
});
