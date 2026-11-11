/**
 * Users, the Admin's alone (owner, 2026-10-09: "Admin should have set up and
 * configure every account"): every sign-in account, searchable and filtered
 * by status, each row with one Actions menu (Configure, Reset password,
 * Activate or Deactivate, and the invitation and lock actions when they
 * apply), and Add user in the page header. Served by the gateway's
 * AccountAdminService.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { ChevronDown, ChevronUp, Lock, Search, UserPlus } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ManagedAccount } from '../../gen/edify/identity/v1/accounts_pb';
import { AccountAdminService } from '../../gen/edify/identity/v1/accounts_pb';
import { fonts, radius, toneColors, useTheme } from '../../theme';
import { Dropdown, DropdownLayer, MenuList, menuHeight, useDropdown } from '../../ui/Dropdown';
import { Notice } from '../cluster/opsParts';
import { AccountFormDrawer, RemoveAccountDrawer, ResetPasswordDrawer } from './AccountDrawers';
import { ManagedTeamDrawer, SupervisorDrawer } from './TeamDrawers';
import { ACTION_LABELS, STATUS_FILTERS, actionsFor, lastSignIn, roleLabel, statusOf } from './accountsData';
import type { AccountAction } from './accountsData';

const PAGE_SIZE = 50;
const SEARCH_PAUSE_MS = 300;

type Open =
  | { readonly kind: 'add' }
  | { readonly kind: 'configure' | 'reset' | 'remove' | 'supervisor' | 'team'; readonly account: ManagedAccount }
  | null;

export function UsersScreen() {
  const { api, state } = useSession();
  const { colors } = useTheme();
  const selfId = state.status === 'signedIn' ? state.session.userId : '';
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [accounts, setAccounts] = useState<ManagedAccount[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [notice, setNotice] = useState<{ readonly text: string; readonly isError: boolean } | null>(null);
  const [open, setOpen] = useState<Open>(null);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), SEARCH_PAUSE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(
    async (pageNumber: number) => {
      setIsLoading(true);
      try {
        const answer = await api.call(AccountAdminService.method.listAccounts, {
          search: query,
          status,
          page: { page: pageNumber, pageSize: PAGE_SIZE },
        });
        setAccounts((current) => (pageNumber === 1 ? answer.accounts : [...current, ...answer.accounts]));
        setTotal(Number(answer.page?.total ?? 0));
        setPage(pageNumber);
      } catch (cause) {
        setNotice({ text: describe(cause), isError: true });
      } finally {
        setIsLoading(false);
      }
    },
    [api, query, status],
  );

  useEffect(() => {
    void load(1);
  }, [load]);

  const saved = useCallback(
    (text: string) => {
      setOpen(null);
      setNotice({ text, isError: false });
      void load(1);
    },
    [load],
  );

  async function act(account: ManagedAccount, action: AccountAction) {
    if (action === 'configure' || action === 'reset' || action === 'remove' || action === 'supervisor' || action === 'team') {
      setOpen({ kind: action, account });
      return;
    }
    setNotice(null);
    try {
      const userId = account.userId;
      if (action === 'resend') {
        const answer = await api.call(AccountAdminService.method.resendInvitation, { userId });
        saved(answer.invitationLink ? `No email could be sent: hand them this link: ${answer.invitationLink}` : `A new invitation was emailed to ${account.email}.`);
      } else if (action === 'revoke') {
        await api.call(AccountAdminService.method.revokeInvitation, { userId });
        saved(`${account.name}'s invitation was revoked.`);
      } else if (action === 'unlock') {
        await api.call(AccountAdminService.method.unlockAccount, { userId });
        saved(`${account.name} can sign in again.`);
      } else {
        const next = action === 'activate' ? 'active' : 'suspended';
        await api.call(AccountAdminService.method.setAccountStatus, { userId, status: next });
        saved(action === 'activate' ? `${account.name} was activated.` : `${account.name} was deactivated; their sessions have ended.`);
      }
    } catch (cause) {
      setNotice({ text: describe(cause), isError: true });
    }
  }

  return (
    <DropdownLayer>
      <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
        <View style={styles.head}>
          <View style={styles.headText}>
            <Text style={[styles.title, { color: colors.text }]} accessibilityRole="header">
              Users
            </Text>
            <Text style={[styles.subtitle, { color: colors.textMuted }]}>
              Every sign-in account: set up, reset and switch on or off.
            </Text>
          </View>
          <Pressable
            onPress={() => setOpen({ kind: 'add' })}
            accessibilityRole="button"
            accessibilityLabel="Add user"
            style={[styles.add, { backgroundColor: colors.primary }]}
          >
            <UserPlus size={16} color={colors.primaryInk} />
            <Text style={[styles.addText, { color: colors.primaryInk }]}>Add user</Text>
          </Pressable>
        </View>

        <View style={[styles.search, { borderColor: colors.fieldBorder, backgroundColor: colors.surface }]}>
          <Search size={16} color={colors.textSubtle} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="Search name or email"
            placeholderTextColor={colors.textSubtle}
            accessibilityLabel="Search users"
            autoCapitalize="none"
            autoCorrect={false}
            style={[styles.searchInput, { color: colors.text }]}
          />
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filters} accessibilityRole="tablist">
          {STATUS_FILTERS.map((filter) => {
            const isOn = filter.value === status;
            return (
              <Pressable
                key={filter.value || 'all'}
                onPress={() => setStatus(filter.value)}
                accessibilityRole="tab"
                accessibilityLabel={filter.label}
                accessibilityState={{ selected: isOn }}
                style={[styles.filter, { backgroundColor: isOn ? colors.primary : colors.raised, borderColor: isOn ? colors.primary : colors.border }]}
              >
                <Text style={[styles.filterText, { color: isOn ? colors.primaryInk : colors.text }]}>{filter.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>

        {notice ? <Notice text={notice.text} isError={notice.isError} /> : null}

        <Text style={[styles.count, { color: colors.textMuted }]}>
          {isLoading && accounts.length === 0 ? 'Loading accounts…' : `${total} ${total === 1 ? 'account' : 'accounts'}`}
        </Text>
        {accounts.map((account) => (
          <AccountRow key={account.userId} account={account} selfId={selfId} onAct={(action) => void act(account, action)} />
        ))}
        {accounts.length < total ? (
          <Pressable
            onPress={() => void load(page + 1)}
            disabled={isLoading}
            accessibilityRole="button"
            style={[styles.more, { borderColor: colors.outlineBorder, backgroundColor: colors.raised }]}
          >
            {isLoading ? <ActivityIndicator color={colors.primary} /> : <Text style={[styles.moreText, { color: colors.link }]}>Show more</Text>}
          </Pressable>
        ) : null}
      </ScrollView>

      {open?.kind === 'add' ? <AccountFormDrawer onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {open?.kind === 'configure' ? <AccountFormDrawer account={open.account} onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {open?.kind === 'reset' ? <ResetPasswordDrawer account={open.account} onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {open?.kind === 'remove' ? <RemoveAccountDrawer account={open.account} onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {open?.kind === 'supervisor' ? <SupervisorDrawer account={open.account} onClose={() => setOpen(null)} onSaved={saved} /> : null}
      {open?.kind === 'team' ? <ManagedTeamDrawer account={open.account} onClose={() => setOpen(null)} onSaved={saved} /> : null}
    </DropdownLayer>
  );
}

function AccountRow({ account, selfId, onAct }: {
  readonly account: ManagedAccount;
  readonly selfId: string;
  readonly onAct: (action: AccountAction) => void;
}) {
  const { colors } = useTheme();
  const actions = actionsFor(account, selfId);
  const menu = useDropdown(menuHeight(actions.length));
  const badge = statusOf(account);
  const tone = toneColors(colors, badge.tone);
  const roles = [account.activeRole, ...account.roles.filter((role) => role !== account.activeRole)].map(roleLabel);
  return (
    <View style={[styles.card, { backgroundColor: colors.raised, borderColor: colors.raisedBorder }]}>
      <View style={styles.cardTop}>
        <View style={styles.grow}>
          <Text style={[styles.name, { color: colors.text }]} numberOfLines={1}>
            {account.name}
          </Text>
          <Text style={[styles.meta, { color: colors.textMuted }]} numberOfLines={1}>
            {account.email}
          </Text>
        </View>
        <Pressable
          ref={menu.triggerRef}
          onPress={menu.toggle}
          accessibilityRole="button"
          accessibilityLabel={`Actions for ${account.name}`}
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
      </View>
      <Text style={[styles.roles, { color: colors.text }]} numberOfLines={2}>
        {roles.join(' · ')}
      </Text>
      <View style={styles.badges}>
        <View style={[styles.badge, { backgroundColor: tone.soft }]}>
          <Text style={[styles.badgeText, { color: tone.fg }]}>{badge.label}</Text>
        </View>
        {account.locked ? (
          <View style={[styles.badge, styles.lockBadge, { backgroundColor: toneColors(colors, 'alert').soft }]}>
            <Lock size={11} color={colors.danger} />
            <Text style={[styles.badgeText, { color: colors.danger }]}>{account.lockedUntilAdmin ? 'Locked until unlocked' : 'Locked'}</Text>
          </View>
        ) : null}
        <Text style={[styles.meta, { color: colors.textSubtle }]}>
          {account.status === 'pending_invited' ? `Invitation ${account.invitationStatus || 'not sent'}` : lastSignIn(account.lastSignInAt)}
        </Text>
      </View>
      <Dropdown anchor={menu.anchor} onClose={menu.close} align="end" minWidth={188} contentStyle={styles.menu} accessibilityLabel={`Actions for ${account.name}`}>
        <MenuList
          onClose={menu.close}
          items={actions.map((action) => ({
            key: action,
            label: ACTION_LABELS[action],
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
  search: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 12 },
  searchInput: { flex: 1, fontFamily: fonts.medium, fontSize: 16, paddingVertical: 8 },
  filters: { gap: 8 },
  filter: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 14, minHeight: 36, justifyContent: 'center' },
  filterText: { fontFamily: fonts.semibold, fontSize: 13 },
  count: { fontFamily: fonts.medium, fontSize: 12 },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: 14, gap: 8 },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  grow: { flex: 1, gap: 2 },
  name: { fontFamily: fonts.semibold, fontSize: 15 },
  meta: { fontFamily: fonts.medium, fontSize: 12 },
  roles: { fontFamily: fonts.medium, fontSize: 13 },
  badges: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  badge: { borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 3 },
  lockBadge: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  badgeText: { fontFamily: fonts.semibold, fontSize: 11 },
  trigger: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 32, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: 10 },
  triggerText: { fontFamily: fonts.semibold, fontSize: 12 },
  menu: { padding: 4 },
  more: { minHeight: 44, borderWidth: 1, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  moreText: { fontFamily: fonts.semibold, fontSize: 14 },
});
