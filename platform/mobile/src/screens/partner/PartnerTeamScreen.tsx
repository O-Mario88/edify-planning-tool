/**
 * Team, the partner organisation's own (the web's /partner/users, owner
 * 2026-11-06: "Add the button for add new member of the partner portal under
 * users"): its staff and volunteers, each one's own login and how many of
 * the organisation's schools they look after, one Actions menu per person,
 * and Add member in the page header. Served by the gateway's
 * PartnerTeamService; a member's own Field Officer login does not reach it.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ChevronDown, ChevronUp, UserPlus } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetPartnerTeamResponse, PartnerMemberInfo } from '../../gen/edify/identity/v1/teams_pb';
import { PartnerTeamService } from '../../gen/edify/identity/v1/teams_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { Dropdown, DropdownLayer, MenuList, menuHeight, useDropdown } from '../../ui/Dropdown';
import { Notice } from '../cluster/opsParts';
import {
  AddMemberDrawer,
  MemberLoginDrawer,
  MemberPasswordDrawer,
  MemberSchoolsDrawer,
  RemoveMemberDrawer,
} from './PartnerTeamDrawers';
import { MEMBER_ACTION_LABELS, loginOf, memberActions, schoolsLabel } from './partnerTeamData';
import type { MemberAction } from './partnerTeamData';

type Open =
  | { readonly kind: 'add' }
  | { readonly kind: 'login' | 'reset' | 'schools' | 'remove'; readonly member: PartnerMemberInfo }
  | null;

export function PartnerTeamScreen() {
  const { api, state } = useSession();
  const { colors } = useTheme();
  const selfId = state.status === 'signedIn' ? state.session.userId : '';
  const [team, setTeam] = useState<GetPartnerTeamResponse | null>(null);
  const [notice, setNotice] = useState<{ readonly text: string; readonly isError: boolean } | null>(null);
  const [open, setOpen] = useState<Open>(null);

  const load = useCallback(async () => {
    try {
      setTeam(await api.call(PartnerTeamService.method.getPartnerTeam, {}));
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

  async function act(member: PartnerMemberInfo, action: MemberAction) {
    if (!team) {
      return;
    }
    if (action === 'deactivate' || action === 'activate') {
      setNotice(null);
      try {
        await api.call(PartnerTeamService.method.setMemberLoginActive, {
          partnerId: team.partnerId, memberId: member.memberId, active: action === 'activate',
        });
        saved(action === 'activate' ? `${member.name} can sign in again.` : `${member.name}'s login is off.`);
      } catch (cause) {
        setNotice({ text: describe(cause), isError: true });
      }
      return;
    }
    setOpen({ kind: action, member });
  }

  const unassigned = team ? team.schools.filter((school) => !school.memberId).length : 0;
  return (
    <DropdownLayer>
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.head}>
          <View style={styles.headText}>
            <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
              Team
            </Text>
            <Text style={[styles.subtitle, { color: colors.textMuted }]}>
              {team ? `${team.partnerName}: who is on the team, their logins and their schools.` : 'Your organisation’s team.'}
            </Text>
          </View>
          {team?.managesRoster ? (
            <Pressable
              onPress={() => setOpen({ kind: 'add' })}
              accessibilityRole="button"
              accessibilityLabel="Add member"
              style={[styles.add, { backgroundColor: colors.primary }]}
            >
              <UserPlus size={16} color={colors.primaryInk} />
              <Text style={[styles.addText, { color: colors.primaryInk }]}>Add member</Text>
            </Pressable>
          ) : null}
        </View>

        {notice ? <Notice text={notice.text} isError={notice.isError} /> : null}
        {!team ? (
          notice?.isError ? null : <ActivityIndicator color={colors.primary} />
        ) : (
          <>
            <Text style={[styles.count, { color: colors.textMuted }]}>
              {team.members.length} {team.members.length === 1 ? 'person' : 'people'} · {team.schools.length} schools held
              {unassigned ? ` · ${unassigned} with nobody yet` : ''}
            </Text>
            {team.members.map((member) => (
              <MemberRow
                key={member.memberId}
                member={member}
                actions={memberActions(member, { leadsTeam: team.leadsTeam, managesRoster: team.managesRoster }, selfId)}
                onAct={(action) => void act(member, action)}
              />
            ))}
            {team.members.length === 0 ? (
              <Text style={[styles.subtitle, { color: colors.textMuted }]}>Nobody is on the team yet. Add the people who deliver for you.</Text>
            ) : null}
          </>
        )}
      </ScrollView>

      {team && open?.kind === 'add' ? <AddMemberDrawer team={team} onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {team && open?.kind === 'login' ? <MemberLoginDrawer team={team} member={open.member} onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {team && open?.kind === 'reset' ? <MemberPasswordDrawer team={team} member={open.member} onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {team && open?.kind === 'schools' ? <MemberSchoolsDrawer team={team} member={open.member} onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {team && open?.kind === 'remove' ? <RemoveMemberDrawer team={team} member={open.member} onClose={() => setOpen(null)} onSaved={saved} /> : null}
    </DropdownLayer>
  );
}

function MemberRow({ member, actions, onAct }: {
  readonly member: PartnerMemberInfo;
  readonly actions: readonly MemberAction[];
  readonly onAct: (action: MemberAction) => void;
}) {
  const { colors } = useTheme();
  const menu = useDropdown(menuHeight(actions.length));
  const login = loginOf(member);
  const tone = toneColors(colors, login.tone);
  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <View style={styles.cardTop}>
        <View style={styles.grow}>
          <Text style={[styles.name, { color: colors.text }]} numberOfLines={1}>
            {member.name}
          </Text>
          <Text style={[styles.meta, { color: colors.textMuted }]} numberOfLines={1}>
            {[member.role === 'volunteer' ? 'Volunteer' : 'Staff', member.title, member.email].filter(Boolean).join(' · ')}
          </Text>
        </View>
        {actions.length > 0 ? (
          <Pressable
            ref={menu.triggerRef}
            onPress={menu.toggle}
            accessibilityRole="button"
            accessibilityLabel={`Actions for ${member.name}`}
            accessibilityState={{ expanded: menu.isOpen }}
            hitSlop={6}
            style={[
              styles.trigger,
              menu.isOpen ? { borderColor: colors.primary, backgroundColor: colors.primarySoft } : { borderColor: colors.outlineBorder, backgroundColor: colors.raised },
            ]}
          >
            <Text style={[styles.triggerText, { color: colors.link }]}>Actions</Text>
            {menu.isOpen ? <ChevronUp size={14} color={colors.link} /> : <ChevronDown size={14} color={colors.link} />}
          </Pressable>
        ) : null}
      </View>
      <View style={styles.badges}>
        <View style={[styles.badge, { backgroundColor: tone.soft }]}>
          <Text style={[styles.badgeText, { color: tone.fg }]}>{login.label}</Text>
        </View>
        <Text style={[styles.meta, { color: colors.textSubtle }]}>{schoolsLabel(member.schoolCount)}</Text>
      </View>
      <Dropdown anchor={menu.anchor} onClose={menu.close} align="end" minWidth={188} contentStyle={styles.menu} accessibilityLabel={`Actions for ${member.name}`}>
        <MenuList
          onClose={menu.close}
          items={actions.map((action) => ({
            key: action,
            label: MEMBER_ACTION_LABELS[action],
            isDanger: action === 'remove' || action === 'deactivate',
            onPress: () => onAct(action),
          }))}
        />
      </Dropdown>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { padding: 12, gap: 10, paddingBottom: 48 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, marginTop: 4 },
  headText: { flex: 1, gap: 4 },
  title: { fontFamily: fonts.bold, fontSize: 22, letterSpacing: -0.2 },
  subtitle: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 19 },
  add: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, borderRadius: radius.sm, paddingHorizontal: 14 },
  addText: { fontFamily: fonts.semibold, fontSize: 14 },
  count: { fontFamily: fonts.medium, fontSize: 12 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 8 },
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
