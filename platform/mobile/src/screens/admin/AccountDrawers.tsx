/**
 * The Users screen's drawers (owner, 2026-10-09: "Add User is a platform
 * drawer"): add or configure an account, reset its password, and confirm a
 * removal. Each calls the gateway's AccountAdminService; a refusal is shown
 * in the gateway's own words at the top of the drawer.
 */
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ManagedAccount } from '../../gen/edify/identity/v1/accounts_pb';
import { AccountAdminService } from '../../gen/edify/identity/v1/accounts_pb';
import { fonts, radius, useTheme } from '../../theme';
import { Drawer } from '../../ui/Drawer';
import { DrawerButton, DrawerInput, DrawerNote, DrawerText, FieldShell } from '../../ui/drawerParts';
import { Select } from '../../ui/Select';
import { ROLES } from './accountsData';

function Footer({ label, isBusy, onCancel, onSubmit }: {
  readonly label: string;
  readonly isBusy: boolean;
  readonly onCancel: () => void;
  readonly onSubmit: () => void;
}) {
  return (
    <View style={styles.footer}>
      <DrawerButton label="Cancel" onPress={onCancel} />
      <DrawerButton label={label} onPress={onSubmit} isPrimary isBusy={isBusy} />
    </View>
  );
}

/** Other roles the account also holds, as tick boxes beside the opening role. */
function OtherRoles({ role, value, onChange }: {
  readonly role: string;
  readonly value: readonly string[];
  readonly onChange: (roles: string[]) => void;
}) {
  const { colors } = useTheme();
  return (
    <View style={styles.chips} accessibilityRole="list">
      {ROLES.filter((choice) => choice.value !== role).map((choice) => {
        const isOn = value.includes(choice.value);
        return (
          <Pressable
            key={choice.value}
            onPress={() => onChange(isOn ? value.filter((held) => held !== choice.value) : [...value, choice.value])}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: isOn }}
            style={[styles.chip, { backgroundColor: isOn ? colors.primary : colors.surface, borderColor: isOn ? colors.primary : colors.border }]}
          >
            <Text style={[styles.chipText, { color: isOn ? colors.primaryInk : colors.text }]}>{choice.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

interface AccountFormProps {
  /** The account to configure; absent to add one. */
  readonly account?: ManagedAccount;
  readonly onClose: () => void;
  readonly onSaved: (message: string) => void;
}

/** Add User, and Configure: name, email, phone and roles; a first password when adding. */
export function AccountFormDrawer({ account, onClose, onSaved }: AccountFormProps) {
  const { api } = useSession();
  const [name, setName] = useState(account?.name ?? '');
  const [email, setEmail] = useState(account?.email ?? '');
  const [phone, setPhone] = useState(account?.phone ?? '');
  const [role, setRole] = useState(account?.activeRole ?? '');
  const [others, setOthers] = useState<string[]>(account ? account.roles.filter((held) => held !== account.activeRole) : []);
  const [password, setPassword] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const [topKey, setTopKey] = useState(0);

  async function submit() {
    if (!name.trim() || !email.trim() || !role) {
      setError('Enter a name, an email address and a role.');
      setTopKey((key) => key + 1);
      return;
    }
    setIsBusy(true);
    setError('');
    try {
      if (account) {
        await api.call(AccountAdminService.method.updateAccount, {
          userId: account.userId, name, email, phone, role, additionalRoles: others,
        });
        onSaved(`${name.trim()}'s account was updated.`);
      } else {
        const answer = await api.call(AccountAdminService.method.createAccount, {
          name, email, phone, role, additionalRoles: others, password,
        });
        onSaved(
          answer.invitationLink
            ? `Account added. No email could be sent: hand ${name.trim()} this link: ${answer.invitationLink}`
            : password
              ? `Account added. ${name.trim()} signs in with the password you chose and must change it.`
              : `Account added. An invitation was emailed to ${email.trim().toLowerCase()}.`,
        );
      }
    } catch (cause) {
      setError(describe(cause));
      setTopKey((key) => key + 1);
      setIsBusy(false);
    }
  }

  return (
    <Drawer
      title={account ? 'Configure account' : 'Add user'}
      subtitle={account?.email}
      onClose={onClose}
      hasRequired
      topKey={topKey}
      footer={<Footer label={account ? 'Save changes' : 'Add user'} isBusy={isBusy} onCancel={onClose} onSubmit={() => void submit()} />}
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      <FieldShell label="Full name" isRequired>
        <DrawerInput value={name} onChangeText={setName} accessibilityLabel="Full name" autoCapitalize="words" />
      </FieldShell>
      <FieldShell label="Email address" isRequired>
        <DrawerInput value={email} onChangeText={setEmail} accessibilityLabel="Email address" keyboardType="email-address"
          autoCapitalize="none" autoCorrect={false} />
      </FieldShell>
      <FieldShell label="Phone" isOptional>
        <DrawerInput value={phone} onChangeText={setPhone} accessibilityLabel="Phone" keyboardType="phone-pad" />
      </FieldShell>
      <FieldShell label="Role" isRequired help="The role the account opens in.">
        <Select label="Role" value={role} choices={ROLES} placeholder="Choose a role" variant="form"
          onChange={(next) => { setRole(next); setOthers((held) => held.filter((r) => r !== next)); }} />
      </FieldShell>
      {role ? (
        <FieldShell label="Also holds" isOptional help="Roles the person can switch to.">
          <OtherRoles role={role} value={others} onChange={setOthers} />
        </FieldShell>
      ) : null}
      {account ? null : (
        <FieldShell label="First password" isOptional
          help="Leave empty to email an invitation. A password you choose must be changed at the first sign-in.">
          <DrawerInput value={password} onChangeText={setPassword} accessibilityLabel="First password" secureTextEntry
            autoCapitalize="none" textContentType="newPassword" />
        </FieldShell>
      )}
    </Drawer>
  );
}

interface AccountDrawerProps {
  readonly account: ManagedAccount;
  readonly onClose: () => void;
  readonly onSaved: (message: string) => void;
}

/** Reset password: email the person a link, or choose a password they must change. */
export function ResetPasswordDrawer({ account, onClose, onSaved }: AccountDrawerProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [mode, setMode] = useState<'link' | 'password'>('link');
  const [password, setPassword] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit() {
    setIsBusy(true);
    setError('');
    try {
      if (mode === 'link') {
        await api.call(AccountAdminService.method.sendPasswordReset, { userId: account.userId });
        onSaved(`A reset link was emailed to ${account.email}. Their sessions have ended.`);
      } else {
        await api.call(AccountAdminService.method.setTemporaryPassword, { userId: account.userId, password });
        onSaved(`${account.name}'s password was set. They must change it when they sign in.`);
      }
    } catch (cause) {
      setError(describe(cause));
      setIsBusy(false);
    }
  }

  return (
    <Drawer
      title="Reset password"
      subtitle={account.email}
      onClose={onClose}
      footer={<Footer label={mode === 'link' ? 'Email reset link' : 'Set password'} isBusy={isBusy} onCancel={onClose} onSubmit={() => void submit()} />}
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      <View style={styles.toggle} accessibilityRole="radiogroup">
        {([['link', 'Email a reset link'], ['password', 'Set a password']] as const).map(([value, label]) => {
          const isOn = mode === value;
          return (
            <Pressable key={value} onPress={() => setMode(value)} accessibilityRole="radio" accessibilityState={{ selected: isOn }}
              style={[styles.toggleOption, { backgroundColor: isOn ? colors.primary : colors.surface, borderColor: isOn ? colors.primary : colors.border }]}>
              <Text style={[styles.chipText, { color: isOn ? colors.primaryInk : colors.text }]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
      {mode === 'link' ? (
        <DrawerText text="A single-use link valid for 45 minutes is emailed to the person, and every session they have open ends now." />
      ) : (
        <FieldShell label="New password" isRequired help="They must change it at their next sign-in. Any lock on the account is lifted.">
          <DrawerInput value={password} onChangeText={setPassword} accessibilityLabel="New password" secureTextEntry autoCapitalize="none" />
        </FieldShell>
      )}
    </Drawer>
  );
}

/** Remove account: confirmed, because it cannot be undone from here. */
export function RemoveAccountDrawer({ account, onClose, onSaved }: AccountDrawerProps) {
  const { api } = useSession();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit() {
    setIsBusy(true);
    setError('');
    try {
      await api.call(AccountAdminService.method.deleteAccount, { userId: account.userId });
      onSaved(`${account.name}'s account was removed.`);
    } catch (cause) {
      setError(describe(cause));
      setIsBusy(false);
    }
  }

  return (
    <Drawer
      title="Remove account"
      subtitle={account.email}
      onClose={onClose}
      footer={<Footer label="Remove account" isBusy={isBusy} onCancel={onClose} onSubmit={() => void submit()} />}
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      <DrawerText
        tone="danger"
        text={`${account.name} will no longer be able to sign in, and ${account.email} is freed for a new account. Their records and history stay.`}
      />
    </Drawer>
  );
}

const styles = StyleSheet.create({
  footer: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 7 },
  chipText: { fontFamily: fonts.semibold, fontSize: 13 },
  toggle: { flexDirection: 'row', gap: 8 },
  toggleOption: { flex: 1, borderWidth: 1, borderRadius: radius.sm, paddingVertical: 10, alignItems: 'center' },
});
