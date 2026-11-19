/**
 * The Edify Enterprise Design System's parts for the native app
 * (docs/migration/180), the counterparts of the web's components/eds, drawn
 * only from the shared tokens (./tokens, built from platform/design/
 * tokens.json). Text wraps; nothing truncates (owner, 2026-10-02).
 */
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { fonts, useTheme } from '../theme';
import { tokens } from './tokens';
import type { Tone } from './todayView';

type Palette = { readonly [K in keyof typeof tokens.color.light]: string };

/** The design system's colours for the phone's light or dark theme. */
export function useDs(): Palette {
  const { isDark } = useTheme();
  return isDark ? tokens.color.dark : tokens.color.light;
}

const { text, space, radius, size } = tokens;

function toneInk(c: Palette, tone: Tone): { fg: string; soft: string } {
  switch (tone) {
    case 'success':
      return { fg: c.success, soft: c['success-soft'] };
    case 'warning':
      return { fg: c.warning, soft: c['warning-soft'] };
    case 'danger':
      return { fg: c.danger, soft: c['danger-soft'] };
    case 'info':
      return { fg: c.info, soft: c['info-soft'] };
    default:
      return { fg: c['text-muted'], soft: c['surface-sunken'] };
  }
}

export function Surface({ children }: { readonly children: ReactNode }) {
  const c = useDs();
  return <View style={[s.surface, { backgroundColor: c.surface, borderColor: c.border }]}>{children}</View>;
}

export function StatusBadge({ tone, children }: { readonly tone: Tone; readonly children: string }) {
  const c = useDs();
  const ink = toneInk(c, tone);
  return (
    <View style={[s.badge, { backgroundColor: ink.soft }]}>
      <Text style={[s.badgeText, { color: ink.fg }]}>{children}</Text>
    </View>
  );
}

interface ButtonProps {
  readonly label: string;
  readonly onPress: () => void;
  readonly kind?: 'primary' | 'secondary';
}

export function Button({ label, onPress, kind = 'primary' }: ButtonProps) {
  const c = useDs();
  const primary = kind === 'primary';
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => [
        s.button,
        primary
          ? { backgroundColor: pressed ? c['primary-hover'] : c.primary, borderColor: 'transparent' }
          : { backgroundColor: pressed ? c['surface-sunken'] : c.surface, borderColor: c['border-strong'] },
      ]}
    >
      <Text style={[s.buttonText, { color: primary ? c['primary-ink'] : c.text }]}>{label}</Text>
    </Pressable>
  );
}

interface SectionHeaderProps {
  readonly title: string;
  readonly linkLabel?: string;
  readonly onLink?: () => void;
}

export function SectionHeader({ title, linkLabel, onLink }: SectionHeaderProps) {
  const c = useDs();
  return (
    <View style={s.section}>
      <Text style={[s.sectionTitle, { color: c.text }]} accessibilityRole="header">
        {title}
      </Text>
      {linkLabel && onLink ? (
        <Pressable onPress={onLink} accessibilityRole="link" accessibilityLabel={linkLabel} hitSlop={12}>
          <Text style={[s.sectionLink, { color: c.primary }]}>{linkLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

interface TaskRowProps {
  readonly title: string;
  readonly context?: string;
  readonly status?: string;
  readonly tone: Tone;
  readonly action: string;
  readonly onPress: () => void;
  readonly last?: boolean;
}

/** One thing to do: what, where, its state and the one action, a whole row to tap. */
export function TaskRow({ title, context, status, tone, action, onPress, last }: TaskRowProps) {
  const c = useDs();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="link"
      accessibilityLabel={[title, context, status, action].filter(Boolean).join('. ')}
      style={({ pressed }) => [
        s.task,
        { borderBottomColor: c.border, borderBottomWidth: last ? 0 : StyleSheet.hairlineWidth },
        pressed ? { backgroundColor: c['surface-sunken'] } : null,
      ]}
    >
      <View style={s.taskBody}>
        <Text style={[s.taskTitle, { color: c.text }]}>{title}</Text>
        {context ? <Text style={[s.caption, { color: c['text-subtle'] }]}>{context}</Text> : null}
        {status ? (
          <View style={s.taskStatus}>
            <StatusBadge tone={tone}>{status}</StatusBadge>
          </View>
        ) : null}
      </View>
      <Text style={[s.taskAction, { color: c.primary }]}>{action}</Text>
    </Pressable>
  );
}

export function TaskList({ children }: { readonly children: ReactNode }) {
  const c = useDs();
  return <View style={[s.list, { backgroundColor: c.surface, borderColor: c.border }]}>{children}</View>;
}

export function KpiStat({ label, value }: { readonly label: string; readonly value: string }) {
  const c = useDs();
  return (
    <View style={s.kpi} accessible accessibilityLabel={`${label}: ${value}`}>
      <Text style={[s.kpiValue, { color: c.text }]}>{value}</Text>
      <Text style={[s.caption, { color: c['text-muted'] }]}>{label}</Text>
    </View>
  );
}

interface EmptyStateProps {
  readonly title: string;
  readonly body: string;
  readonly action?: { readonly label: string; readonly onPress: () => void };
}

export function EmptyState({ title, body, action }: EmptyStateProps) {
  const c = useDs();
  return (
    <View style={[s.empty, { backgroundColor: c.surface, borderColor: c.border }]}>
      <Text style={[s.emptyTitle, { color: c.text }]}>{title}</Text>
      <Text style={[s.body, { color: c['text-muted'] }]}>{body}</Text>
      {action ? (
        <View style={s.emptyAction}>
          <Button label={action.label} onPress={action.onPress} />
        </View>
      ) : null}
    </View>
  );
}

export function Skeleton({ label }: { readonly label: string }) {
  const c = useDs();
  return (
    <View style={[s.list, { backgroundColor: c.surface, borderColor: c.border }]} accessibilityLabel={label}>
      {[0, 1].map((row) => (
        <View key={row} style={s.task}>
          <View style={[s.skeletonLine, { backgroundColor: c['surface-sunken'] }]} />
        </View>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  surface: { borderWidth: 1, borderRadius: radius.lg, padding: space[4] },
  badge: { alignSelf: 'flex-start', borderRadius: radius.pill, paddingHorizontal: space[2], paddingVertical: 2 },
  badgeText: { fontFamily: fonts.semibold, fontSize: text.caption.size, lineHeight: text.caption.line },
  button: {
    minHeight: size.target,
    borderRadius: radius.md,
    borderWidth: 1,
    paddingHorizontal: space[4],
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonText: { fontFamily: fonts.semibold, fontSize: text.control.size, lineHeight: text.control.line, textAlign: 'center' },
  section: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    gap: space[3],
    marginTop: space[2],
  },
  sectionTitle: { fontFamily: fonts.bold, fontSize: text.lead.size, lineHeight: text.lead.line, flexShrink: 1 },
  sectionLink: { fontFamily: fonts.semibold, fontSize: text.body.size, lineHeight: text.body.line },
  list: { borderWidth: 1, borderRadius: radius.lg, overflow: 'hidden' },
  task: {
    minHeight: size.target + space[4],
    flexDirection: 'row',
    alignItems: 'center',
    gap: space[3],
    paddingHorizontal: space[4],
    paddingVertical: space[3],
  },
  taskBody: { flex: 1, gap: 2 },
  taskTitle: { fontFamily: fonts.semibold, fontSize: text.body.size, lineHeight: text.body.line },
  taskStatus: { marginTop: space[1] },
  taskAction: { fontFamily: fonts.semibold, fontSize: text.body.size, lineHeight: text.body.line },
  caption: { fontFamily: fonts.medium, fontSize: text.caption.size, lineHeight: text.caption.line },
  body: { fontFamily: fonts.regular, fontSize: text.body.size, lineHeight: text.body.line },
  kpi: { width: '50%', paddingVertical: space[2], gap: 2 },
  kpiValue: { fontFamily: fonts.bold, fontSize: text.figure.size, lineHeight: text.figure.line, fontVariant: ['tabular-nums'] },
  empty: { borderWidth: 1, borderRadius: radius.lg, padding: space[5], gap: space[1] },
  emptyTitle: { fontFamily: fonts.semibold, fontSize: text.lead.size, lineHeight: text.lead.line },
  emptyAction: { marginTop: space[3], alignSelf: 'flex-start' },
  skeletonLine: { flex: 1, height: 14, borderRadius: radius.sm },
});
