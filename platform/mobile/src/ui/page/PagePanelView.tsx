/**
 * A titled card of record details (a profile's Details tab, SSA history):
 * its title, the line under it and its badges, then its parts in the page's
 * order — sub-headings, paragraphs, fields (label over value, one to a line
 * on a phone), data rows, linked lists and a meter.
 */
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { PageFact, PagePanel, PagePanelItem } from '../../gen/edify/screens/v1/page_pb';
import { fonts, useTheme } from '../../theme';
import { cardStyles, toneColor, usePageLink } from './shared';

export function PagePanelView({ panel }: { readonly panel: PagePanel }) {
  const { colors } = useTheme();
  const hasHead = panel.title !== '' || panel.badges.length > 0;
  return (
    <View style={[cardStyles.card, styles.clip, { backgroundColor: colors.raised, borderColor: colors.border }]}>
      {hasHead ? (
        <View style={[styles.head, { borderBottomColor: colors.raisedBorder }]}>
          <View style={styles.titleLine}>
            <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
              {panel.title}
            </Text>
            {panel.badges.map((badge) => (
              <View key={badge.text} style={[styles.badge, { backgroundColor: colors.primarySoft, borderColor: colors.outlineBorder }]}>
                <Text style={[styles.badgeText, { color: colors.link }]}>{badge.text}</Text>
              </View>
            ))}
          </View>
          {panel.subtitle ? <Text style={[styles.subtitle, { color: colors.textMuted }]}>{panel.subtitle}</Text> : null}
        </View>
      ) : null}
      <View style={styles.body}>
        {panel.items.map((item, index) => (
          <Item key={index} item={item} />
        ))}
      </View>
    </View>
  );
}

function Item({ item }: { readonly item: PagePanelItem }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const kind = item.kind;
  switch (kind.case) {
    case 'heading':
      return (
        <Text style={[styles.heading, { color: colors.text }]} accessibilityRole="header">
          {kind.value}
        </Text>
      );
    case 'text':
      return (
        <Text style={[styles.text, { color: toneColor(colors, item.tone) ?? colors.textMuted }]}>{kind.value}</Text>
      );
    case 'fields':
      return (
        <View>
          {kind.value.facts.map((field, index) => (
            <Field key={`${field.label}-${index}`} field={field} isFirst={index === 0} />
          ))}
        </View>
      );
    case 'rows':
      return (
        <View>
          {kind.value.rows.map((row, index) => (
            <View
              key={index}
              style={[styles.dataRow, { borderBottomColor: colors.raisedBorder }]}
            >
              <View style={styles.dataLine}>
                <Text style={[styles.dataLabel, { color: colors.text }]}>{row.label}</Text>
                <Text style={[styles.dataValue, { color: toneColor(colors, row.tone) ?? colors.text }]}>{row.value}</Text>
              </View>
              {row.meta ? <Text style={[styles.dataMeta, { color: colors.textMuted }]}>{row.meta}</Text> : null}
            </View>
          ))}
        </View>
      );
    case 'links':
      return (
        <View style={styles.links}>
          {kind.value.links.map((link) => (
            <Pressable
              key={`${link.text}-${link.caption}`}
              onPress={link.href ? () => openLink(link.href, link.drawer) : undefined}
              disabled={!link.href}
              accessibilityRole={link.href ? 'link' : 'text'}
            >
              <Text style={[styles.linkText, { color: colors.text }]}>{link.text}</Text>
              {link.caption ? <Text style={[styles.caption, { color: colors.textMuted }]}>{link.caption}</Text> : null}
            </Pressable>
          ))}
        </View>
      );
    case 'meter':
      return (
        <View style={styles.meter}>
          <Text style={[styles.figure, { color: colors.text }]}>
            {kind.value.value} <Text style={[styles.caption, { color: colors.textMuted }]}>{kind.value.label}</Text>
          </Text>
          <View style={[styles.track, { backgroundColor: colors.border }]}>
            <View style={[styles.fill, { width: `${Math.min(100, kind.value.fraction * 100)}%`, backgroundColor: colors.primary }]} />
          </View>
        </View>
      );
    default:
      return null;
  }
}

function Field({ field, isFirst }: { readonly field: PageFact; readonly isFirst: boolean }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  return (
    <View style={[styles.field, !isFirst && { borderTopWidth: 1, borderTopColor: colors.raisedBorder }]}>
      <Text style={[styles.fieldLabel, { color: colors.text }]}>{field.label}</Text>
      <Text
        onPress={field.href ? () => openLink(field.href) : undefined}
        accessibilityRole={field.href ? 'link' : 'text'}
        style={[styles.fieldValue, { color: colors.link }]}
      >
        {field.value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  clip: { overflow: 'hidden' },
  head: { padding: 16, paddingBottom: 12, borderBottomWidth: 1, gap: 4 },
  titleLine: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, justifyContent: 'space-between' },
  title: { flexShrink: 1, fontFamily: fonts.bold, fontSize: 15 },
  subtitle: { fontFamily: fonts.semibold, fontSize: 13, lineHeight: 16 },
  badge: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  badgeText: { fontFamily: fonts.semibold, fontSize: 12 },
  body: { padding: 16, gap: 8 },
  heading: { fontFamily: fonts.bold, fontSize: 15, marginTop: 4 },
  text: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  field: { paddingVertical: 9.6, gap: 2 },
  fieldLabel: { fontFamily: fonts.semibold, fontSize: 13 },
  fieldValue: { fontFamily: fonts.bold, fontSize: 13 },
  dataRow: { paddingVertical: 12, borderBottomWidth: 1, gap: 4 },
  dataLine: { flexDirection: 'row', alignItems: 'baseline', gap: 12 },
  dataLabel: { fontFamily: fonts.semibold, fontSize: 13 },
  dataValue: { fontFamily: fonts.semibold, fontSize: 12 },
  dataMeta: { fontFamily: fonts.semibold, fontSize: 13 },
  links: { gap: 8 },
  linkText: { fontFamily: fonts.semibold, fontSize: 15 },
  caption: { fontFamily: fonts.semibold, fontSize: 12 },
  meter: { gap: 8 },
  figure: { fontFamily: fonts.medium, fontSize: 20 },
  track: { height: 6, borderRadius: 999, overflow: 'hidden' },
  fill: { height: 6 },
});
