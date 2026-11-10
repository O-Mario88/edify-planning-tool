/**
 * A card of rows as the web draws it on a phone (partials/todos/row.html and
 * its kin): each record's coloured icon square, its bold title and the lines
 * under it, its pills and its button. A titled list ("Do next  45 open")
 * carries its heading above the card, as the phone home sections do.
 */
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ChevronDown, ChevronRight, Zap } from 'lucide-react-native';

import type { PageList, PageListItem } from '../../gen/edify/screens/v1/page_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { isShownFor } from './pageLinks';
import { cardStyles, useChips, usePageLink } from './shared';

export function PageListView({ list }: { readonly list: PageList }) {
  const { colors } = useTheme();
  const { chosen } = useChips();
  const items = list.items.filter((item) => isShownFor(item.keys, chosen));
  return (
    <View style={styles.section}>
      {list.title ? (
        <View style={styles.head}>
          <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
            {list.title}
          </Text>
          {list.count ? <Text style={[styles.count, { color: colors.link }]}>{list.count}</Text> : null}
        </View>
      ) : null}
      <View style={[cardStyles.card, styles.card, { backgroundColor: colors.raised, borderColor: colors.border }]}>
        {items.map((item, index) =>
          item.children.length > 0 ? (
            <Group key={`${item.title}-${index}`} item={item} isFirst={index === 0} />
          ) : (
            <Row key={`${item.title}-${index}`} item={item} isFirst={index === 0} />
          ),
        )}
      </View>
    </View>
  );
}

function Row({ item, isFirst }: { readonly item: PageListItem; readonly isFirst: boolean }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const tone = toneColors(colors, item.tone || 'brand');
  const body = (
    <>
      <View style={[styles.icon, { backgroundColor: tone.soft }]}>
        <Zap size={15} color={tone.fg} />
      </View>
      <View style={styles.text}>
        <Text style={[styles.itemTitle, { color: colors.text }]}>{item.title}</Text>
        {item.lines.map((line) => (
          <Text key={line} style={[styles.line, { color: colors.textSubtle }]}>
            {line}
          </Text>
        ))}
        {item.badges.length > 0 || item.actions.length > 0 ? (
          <View style={styles.extras}>
            {item.badges.map((badge) => {
              const badgeTone = badge.tone === 'plain' ? undefined : toneColors(colors, badge.tone);
              return (
                <View key={badge.text} style={[styles.badge, { backgroundColor: badgeTone?.soft ?? colors.surfaceMuted }]}>
                  <Text style={[styles.badgeText, { color: badgeTone?.fg ?? colors.textMuted }]}>{badge.text}</Text>
                </View>
              );
            })}
            {item.actions.map((action) => (
              <Pressable
                key={action.href + action.label}
                onPress={() => openLink(action.href)}
                disabled={!action.enabled}
                accessibilityRole="button"
                accessibilityLabel={`${action.label}: ${item.title}`}
                style={[styles.action, { borderColor: colors.outlineBorder, backgroundColor: colors.primarySoft }]}
              >
                <Text style={[styles.actionText, { color: colors.link }]}>{action.label}</Text>
              </Pressable>
            ))}
          </View>
        ) : null}
      </View>
    </>
  );
  const rowStyle = [styles.row, !isFirst && { borderTopWidth: 1, borderTopColor: colors.raisedBorder }];
  return item.href ? (
    <Pressable onPress={() => openLink(item.href)} accessibilityRole="link" style={rowStyle}>
      {body}
    </Pressable>
  ) : (
    <View style={rowStyle}>{body}</View>
  );
}

/** An entry that opens onto its records, as the web's <details> group. */
function Group({ item, isFirst }: { readonly item: PageListItem; readonly isFirst: boolean }) {
  const { colors } = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  return (
    <View style={!isFirst ? { borderTopWidth: 1, borderTopColor: colors.raisedBorder } : null}>
      <Pressable
        onPress={() => setIsOpen(!isOpen)}
        accessibilityRole="button"
        accessibilityState={{ expanded: isOpen }}
        accessibilityLabel={`${item.title}, ${item.count}`}
        style={styles.row}
      >
        <View style={styles.chevron}>
          {isOpen ? <ChevronDown size={16} color={colors.textSubtle} /> : <ChevronRight size={16} color={colors.textSubtle} />}
        </View>
        <View style={styles.text}>
          <Text style={[styles.itemTitle, { color: colors.text }]}>{item.title}</Text>
          {item.lines.map((line) => (
            <Text key={line} style={[styles.line, { color: colors.textSubtle }]} numberOfLines={isOpen ? undefined : 2}>
              {line}
            </Text>
          ))}
        </View>
        <View style={[styles.groupCount, { backgroundColor: colors.surfaceMuted }]}>
          <Text style={[styles.badgeText, { color: colors.text }]}>{item.count}</Text>
        </View>
      </Pressable>
      {isOpen ? (
        <View style={styles.children}>
          {item.children.map((child, index) => (
            <Row key={`${child.title}-${index}`} item={child} isFirst={false} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  chevron: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  groupCount: { borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 2, alignSelf: 'center' },
  children: { paddingLeft: 12 },
  section: { gap: 10 },
  head: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  title: { fontFamily: fonts.bold, fontSize: 15 },
  count: { fontFamily: fonts.semibold, fontSize: 12 },
  card: { paddingHorizontal: 12 },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingVertical: 14 },
  icon: { width: 32, height: 32, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1, gap: 2 },
  itemTitle: { fontFamily: fonts.bold, fontSize: 13, lineHeight: 18 },
  line: { fontFamily: fonts.semibold, fontSize: 12, lineHeight: 17 },
  extras: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginTop: 6 },
  badge: { borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 2 },
  badgeText: { fontFamily: fonts.semibold, fontSize: 11 },
  action: { height: 28, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center' },
  actionText: { fontFamily: fonts.bold, fontSize: 12 },
});
