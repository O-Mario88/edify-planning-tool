/**
 * A record card that opens in place, as the web draws it
 * (partials/clusters/cluster_card.html and its kin): the record's name with
 * its status pills and its Actions menu, then its facts as "Label: value"
 * pairs that wrap — a quiet label, a strong value in the fact's colour. Its
 * name opens it, and the open card shows its details and the list it loads
 * once opened (a cluster's schools).
 */
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { ChevronDown, ChevronUp } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { PageBlock, PageRecord } from '../../gen/edify/screens/v1/page_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { PageBlockView } from './PageBlocksView';
import { TickBox } from './PageTableView';
import { RowActions } from './RowActions';
import { cardStyles, toneColor, usePageLink, usePicks } from './shared';

export function PageRecordView({ record }: { readonly record: PageRecord }) {
  const { colors } = useTheme();
  const openLink = usePageLink();
  const pick = usePicks();
  const [isOpen, setIsOpen] = useState(false);
  const opened = useOpenedPart(record.detailsPath, isOpen);
  const canOpen = record.details.length > 0 || record.detailsPath !== '';
  const canTick = pick.isOn && record.pickId !== '';
  const isTicked = canTick && pick.picked.includes(record.pickId);
  return (
    <View
      style={[
        cardStyles.card,
        styles.card,
        { backgroundColor: colors.raised, borderColor: isTicked ? colors.primary : colors.border },
      ]}
    >
      <View style={styles.head}>
        {canTick ? (
          <Pressable
            onPress={() => pick.set([record.pickId], !isTicked)}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: isTicked }}
            accessibilityLabel={record.pickLabel || `Select ${record.title}`}
            hitSlop={10}
            style={styles.tick}
          >
            <TickBox isOn={isTicked} />
          </Pressable>
        ) : null}
        <View style={styles.titleRow}>
          <Text
            onPress={() => (canOpen ? setIsOpen(!isOpen) : record.href ? openLink(record.href) : undefined)}
            accessibilityRole="button"
            accessibilityState={canOpen ? { expanded: isOpen } : undefined}
            accessibilityLabel={canOpen ? `${isOpen ? 'Hide' : 'Show'} details for ${record.title}` : record.title}
            style={[styles.title, { color: colors.text }]}
          >
            {record.title}
          </Text>
          {record.badges.map((badge) => {
            const tone = toneColors(colors, badge.tone);
            return (
              <View key={badge.text} style={[styles.badge, { backgroundColor: tone.soft }]}>
                <Text style={[styles.badgeText, { color: tone.fg }]}>{badge.text}</Text>
              </View>
            );
          })}
        </View>
        {record.actions.length > 0 ? <RowActions actions={record.actions} label={record.title} /> : null}
      </View>
      {record.subtitle ? <Text style={[styles.subtitle, { color: colors.textMuted }]}>{record.subtitle}</Text> : null}
      {record.facts.length > 0 ? (
        <View style={styles.facts}>
          {record.facts.map((fact) => (
            <Text key={fact.label} style={[styles.factLabel, { color: colors.textMuted }]}>
              {fact.label}:{' '}
              <Text
                onPress={fact.href ? () => openLink(fact.href) : undefined}
                accessibilityRole={fact.href ? 'link' : undefined}
                style={[styles.factValue, { color: toneColor(colors, fact.tone) ?? (fact.href ? colors.link : colors.text) }]}
              >
                {fact.value}
              </Text>
            </Text>
          ))}
        </View>
      ) : null}
      {canOpen ? (
        <Pressable
          onPress={() => setIsOpen(!isOpen)}
          accessibilityRole="button"
          accessibilityState={{ expanded: isOpen }}
          hitSlop={6}
          style={styles.toggle}
        >
          <Text style={[styles.toggleText, { color: colors.link }]}>{isOpen ? 'Hide details' : 'Show details'}</Text>
          {isOpen ? <ChevronUp size={14} color={colors.link} /> : <ChevronDown size={14} color={colors.link} />}
        </Pressable>
      ) : null}
      {isOpen ? (
        <View style={[styles.details, { borderTopColor: colors.raisedBorder }]}>
          {record.href ? (
            <Text onPress={() => openLink(record.href)} accessibilityRole="link" style={[styles.profile, { color: colors.link }]}>
              Open {record.title} profile
            </Text>
          ) : null}
          {record.details.map((block, index) => (
            <PageBlockView key={index} block={block} />
          ))}
          <OpenedPart part={opened} />
        </View>
      ) : null}
    </View>
  );
}

type Opened = { readonly blocks: readonly PageBlock[]; readonly error: string; readonly isLoading: boolean };

const NOT_OPENED: Opened = { blocks: [], error: '', isLoading: false };

/** The list the card loads once opened: fetched the first time it opens and
 * kept while the card closes and opens again. */
function useOpenedPart(path: string, isOpen: boolean): Opened {
  const { api } = useSession();
  const [opened, setOpened] = useState<Opened>(NOT_OPENED);
  const asked = useRef('');
  useEffect(() => {
    if (!isOpen || !path || asked.current === path) {
      return undefined;
    }
    asked.current = path;
    let isLive = true;
    let isDone = false;
    setOpened({ ...NOT_OPENED, isLoading: true });
    api
      .getPage(path, {})
      .then((answer) => isLive && setOpened({ blocks: answer.blocks, error: answer.error, isLoading: false }))
      .catch((cause: unknown) => isLive && setOpened({ blocks: [], error: describe(cause), isLoading: false }))
      .finally(() => {
        isDone = true;
      });
    return () => {
      isLive = false;
      if (!isDone) {
        // Closed before the answer came: ask again when it opens again.
        asked.current = '';
      }
    };
  }, [api, isOpen, path]);
  return opened;
}

function OpenedPart({ part }: { readonly part: Opened }) {
  const { colors } = useTheme();
  if (part.isLoading) {
    return <ActivityIndicator color={colors.primary} accessibilityLabel="Loading" />;
  }
  if (part.error) {
    return (
      <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>
        {part.error}
      </Text>
    );
  }
  return (
    <>
      {part.blocks.map((block, index) => (
        <PageBlockView key={index} block={block} />
      ))}
    </>
  );
}

const styles = StyleSheet.create({
  card: { padding: 16, gap: 10 },
  head: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  titleRow: { flex: 1, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  tick: { paddingTop: 2 },
  title: { fontFamily: fonts.bold, fontSize: 15, lineHeight: 20 },
  badge: { borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 2 },
  badgeText: { fontFamily: fonts.semibold, fontSize: 11 },
  subtitle: { fontFamily: fonts.medium, fontSize: 12 },
  facts: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 18, rowGap: 6 },
  factLabel: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 17 },
  factValue: { fontFamily: fonts.bold, fontSize: 12 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' },
  toggleText: { fontFamily: fonts.semibold, fontSize: 12 },
  details: { borderTopWidth: 1, paddingTop: 12, gap: 12 },
  profile: { fontFamily: fonts.semibold, fontSize: 12 },
  error: { fontFamily: fonts.medium, fontSize: 12 },
});
