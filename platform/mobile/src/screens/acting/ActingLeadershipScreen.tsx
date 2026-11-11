/**
 * Acting Leadership (the web's /acting-leadership, apps.acting): a Program
 * Lead appoints one of their CCEOs Acting Program Lead, a Country Director
 * one of their Program Leads Acting Country Director, for one calendar
 * month. Current, upcoming and history, each appointment naming the
 * person's permanent role beside the acting one; one Actions menu per row;
 * Appoint in the page header for whoever may appoint. Served by the
 * gateway's ActingLeadershipService.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ChevronDown, ChevronUp, UserPlus } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ActingAppointment, GetActingBoardResponse } from '../../gen/edify/identity/v1/acting_pb';
import { ActingLeadershipService } from '../../gen/edify/identity/v1/acting_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { Dropdown, DropdownLayer, MenuList, menuHeight, useDropdown } from '../../ui/Dropdown';
import { Notice } from '../cluster/opsParts';
import { AppointDrawer, CancelAppointmentDrawer, ChangeMonthDrawer } from './ActingDrawers';
import { APPOINTMENT_ACTION_LABELS, appointmentActions, stateTone } from './actingData';
import type { AppointmentAction } from './actingData';

type Open =
  | { readonly kind: 'appoint' }
  | { readonly kind: AppointmentAction; readonly appointment: ActingAppointment }
  | null;

/** The three tables, in the web's words. */
const SECTIONS = [
  {
    key: 'current',
    title: 'Current',
    count: (n: number) => `${n} active`,
    caption: 'Acting appointments in effect today: the person and their permanent role, the acting role, the period, the scope and the status.',
  },
  {
    key: 'upcoming',
    title: 'Upcoming',
    count: (n: number) => `${n} scheduled`,
    caption: 'Acting appointments made for a month that has not begun. Each starts by itself on the first day of its month.',
  },
  {
    key: 'history',
    title: 'History',
    count: (n: number) => `${n} ended or cancelled`,
    caption: 'Acting appointments that have ended or were cancelled. The record is kept.',
  },
] as const;

export function ActingLeadershipScreen() {
  const { api } = useSession();
  const { colors } = useTheme();
  const [board, setBoard] = useState<GetActingBoardResponse | null>(null);
  const [notice, setNotice] = useState<{ readonly text: string; readonly isError: boolean } | null>(null);
  const [open, setOpen] = useState<Open>(null);

  const load = useCallback(async () => {
    try {
      setBoard(await api.call(ActingLeadershipService.method.getActingBoard, {}));
    } catch (cause) {
      setNotice({ text: describe(cause), isError: true });
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const saved = useCallback(
    (text: string) => {
      setOpen(null);
      setNotice({ text, isError: false });
      void load();
    },
    [load],
  );

  return (
    <DropdownLayer>
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.head}>
          <View style={styles.headText}>
            <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
              Acting Leadership
            </Text>
            <Text style={[styles.subtitle, { color: colors.textMuted }]}>
              Acting appointments for one calendar month. An appointment never changes who somebody is.
            </Text>
          </View>
          {board?.canAppointLabel ? (
            <Pressable
              onPress={() => setOpen({ kind: 'appoint' })}
              accessibilityRole="button"
              accessibilityLabel={`Appoint ${board.canAppointLabel}`}
              style={[styles.add, { backgroundColor: colors.primary }]}
            >
              <UserPlus size={16} color={colors.primaryInk} />
              <Text style={[styles.addText, { color: colors.primaryInk }]}>Appoint {board.canAppointLabel}</Text>
            </Pressable>
          ) : null}
        </View>

        {notice ? <Notice text={notice.text} isError={notice.isError} /> : null}
        {!board
          ? notice?.isError
            ? null
            : <ActivityIndicator color={colors.primary} />
          : SECTIONS.map((section) => {
              const rows = board[section.key];
              return (
                <View key={section.key} style={styles.section}>
                  <View style={styles.sectionHead}>
                    <Text style={[styles.sectionTitle, { color: colors.text }]} accessibilityRole="header">
                      {section.title}
                    </Text>
                    <Text style={[styles.count, { color: colors.textMuted }]}>{section.count(rows.length)}</Text>
                  </View>
                  <Text style={[styles.caption, { color: colors.textSubtle }]}>{section.caption}</Text>
                  {rows.map((appointment) => (
                    <AppointmentRow
                      key={appointment.id}
                      appointment={appointment}
                      showsAppointer={section.key === 'history'}
                      onAct={(action) => setOpen({ kind: action, appointment })}
                    />
                  ))}
                  {rows.length === 0 ? (
                    <Text style={[styles.empty, { color: colors.textMuted }]}>None.</Text>
                  ) : null}
                </View>
              );
            })}
      </ScrollView>

      {open?.kind === 'appoint' && board ? (
        <AppointDrawer shortLabel={board.canAppointLabel} onClose={() => setOpen(null)} onSaved={saved} />
      ) : null}
      {open?.kind === 'change' ? <ChangeMonthDrawer appointment={open.appointment} onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {open?.kind === 'cancel' ? (
        <CancelAppointmentDrawer appointment={open.appointment} onClose={() => setOpen(null)} onSaved={saved} />
      ) : null}
    </DropdownLayer>
  );
}

function AppointmentRow({ appointment, showsAppointer, onAct }: {
  readonly appointment: ActingAppointment;
  readonly showsAppointer: boolean;
  readonly onAct: (action: AppointmentAction) => void;
}) {
  const { colors } = useTheme();
  const actions = appointmentActions(appointment);
  const menu = useDropdown(menuHeight(actions.length));
  const tone = toneColors(colors, stateTone(appointment.state));
  const where = showsAppointer ? `Appointed by ${appointment.appointedByName}` : appointment.scopeLabel;
  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <View style={styles.cardTop}>
        <View style={styles.grow}>
          <Text style={[styles.name, { color: colors.text }]} numberOfLines={1}>
            {appointment.appointeeName}
          </Text>
          <Text style={[styles.meta, { color: colors.textMuted }]} numberOfLines={1}>
            {appointment.appointeeRole} · {appointment.label}
          </Text>
        </View>
        {actions.length > 0 ? (
          <Pressable
            ref={menu.triggerRef}
            onPress={menu.toggle}
            accessibilityRole="button"
            accessibilityLabel={`Actions for ${appointment.appointeeName}`}
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
      </View>
      <Text style={[styles.meta, { color: colors.text }]}>
        {appointment.monthLabel} · {appointment.effectiveLabel}
      </Text>
      <View style={styles.badges}>
        <View style={[styles.badge, { backgroundColor: tone.soft }]}>
          <Text style={[styles.badgeText, { color: tone.fg }]}>{appointment.stateLabel}</Text>
        </View>
        <Text style={[styles.meta, { color: colors.textSubtle }]} numberOfLines={1}>
          {where}
        </Text>
      </View>
      {appointment.cancelReason ? (
        <Text style={[styles.meta, { color: colors.textMuted }]}>
          Cancelled by {appointment.cancelledByName}: {appointment.cancelReason}
        </Text>
      ) : null}
      <Dropdown
        anchor={menu.anchor}
        onClose={menu.close}
        align="end"
        minWidth={200}
        contentStyle={styles.menu}
        accessibilityLabel={`Actions for ${appointment.appointeeName}`}
      >
        <MenuList
          onClose={menu.close}
          items={actions.map((action) => ({
            key: action,
            label: APPOINTMENT_ACTION_LABELS[action],
            isDanger: action === 'cancel',
            onPress: () => onAct(action),
          }))}
        />
      </Dropdown>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { padding: 12, gap: 12, paddingBottom: 48 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, marginTop: 4 },
  headText: { flex: 1, gap: 4 },
  title: { fontFamily: fonts.bold, fontSize: 22, letterSpacing: -0.2 },
  subtitle: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  add: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, borderRadius: radius.sm, paddingHorizontal: 14 },
  addText: { fontFamily: fonts.semibold, fontSize: 14 },
  section: { gap: 8 },
  sectionHead: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  sectionTitle: { fontFamily: fonts.bold, fontSize: 16 },
  count: { fontFamily: fonts.medium, fontSize: 12 },
  caption: { fontFamily: fonts.medium, fontSize: 12, lineHeight: 17 },
  empty: { fontFamily: fonts.medium, fontSize: 13 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 6 },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  grow: { flex: 1, gap: 2 },
  name: { fontFamily: fonts.semibold, fontSize: 15 },
  meta: { fontFamily: fonts.medium, fontSize: 12 },
  badges: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  badge: { borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 3 },
  badgeText: { fontFamily: fonts.semibold, fontSize: 11 },
  trigger: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 32, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 10 },
  triggerText: { fontFamily: fonts.semibold, fontSize: 12 },
  menu: { padding: 4 },
});
