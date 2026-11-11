/**
 * The partner Team screen's drawers: add a person, give them a login, reset
 * its password, split the organisation's schools, remove them. Each calls
 * the gateway's PartnerTeamService; a refusal is shown in its own words.
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Check } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { GetPartnerTeamResponse, PartnerMemberInfo } from '../../gen/edify/identity/v1/teams_pb';
import { PartnerTeamService } from '../../gen/edify/identity/v1/teams_pb';
import { fonts, radius, useTheme } from '../../theme';
import { Drawer } from '../../ui/Drawer';
import { DrawerButton, DrawerInput, DrawerNote, DrawerText, FieldShell } from '../../ui/drawerParts';
import { ChoiceRow } from '../cluster/opsParts';

interface Base {
  readonly team: GetPartnerTeamResponse;
  readonly onClose: () => void;
  readonly onSaved: (message: string) => void;
}

interface MemberBase extends Base {
  readonly member: PartnerMemberInfo;
}

/** One drawer's frame: the gateway call, its busy state and its refusal. */
function useSubmit(onSaved: (message: string) => void) {
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const [topKey, setTopKey] = useState(0);
  async function run(work: () => Promise<string>) {
    setIsBusy(true);
    setError('');
    try {
      onSaved(await work());
    } catch (cause) {
      setError(describe(cause));
      setTopKey((key) => key + 1);
      setIsBusy(false);
    }
  }
  return { isBusy, error, setError, topKey, run };
}

function Frame({ title, subtitle, label, isBusy, error, topKey, onClose, onSubmit, children }: {
  readonly title: string;
  readonly subtitle?: string;
  readonly label: string;
  readonly isBusy: boolean;
  readonly error: string;
  readonly topKey: number;
  readonly onClose: () => void;
  readonly onSubmit: () => void;
  readonly children: ReactNode;
}) {
  return (
    <Drawer
      title={title}
      subtitle={subtitle}
      onClose={onClose}
      topKey={topKey}
      footer={
        <View style={styles.footer}>
          <DrawerButton label="Cancel" onPress={onClose} />
          <DrawerButton label={label} onPress={onSubmit} isPrimary isBusy={isBusy} />
        </View>
      }
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      {children}
    </Drawer>
  );
}

/** Add a person to the roster: staff or volunteer. */
export function AddMemberDrawer({ team, onClose, onSaved }: Base) {
  const { api } = useSession();
  const [name, setName] = useState('');
  const [role, setRole] = useState('staff');
  const [title, setTitle] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const submit = useSubmit(onSaved);
  return (
    <Frame
      title="Add team member"
      subtitle={team.partnerName}
      label="Add member"
      {...submit}
      onClose={onClose}
      onSubmit={() =>
        void submit.run(async () => {
          if (!name.trim()) {
            throw new Error('A name is required.');
          }
          await api.call(PartnerTeamService.method.addMember, { partnerId: team.partnerId, name, role, title, phone, email });
          return `${name.trim()} was added to the team.`;
        })
      }
    >
      <FieldShell label="Full name" isRequired>
        <DrawerInput value={name} onChangeText={setName} accessibilityLabel="Full name" autoCapitalize="words" />
      </FieldShell>
      <ChoiceRow label="Role" value={role} choices={[{ value: 'staff', label: 'Staff' }, { value: 'volunteer', label: 'Volunteer' }]} onChange={setRole} />
      <FieldShell label="Title" isOptional>
        <DrawerInput value={title} onChangeText={setTitle} accessibilityLabel="Title" />
      </FieldShell>
      <FieldShell label="Phone" isOptional>
        <DrawerInput value={phone} onChangeText={setPhone} accessibilityLabel="Phone" keyboardType="phone-pad" />
      </FieldShell>
      <FieldShell label="Email address" isOptional help="Needed later if they get a login of their own.">
        <DrawerInput value={email} onChangeText={setEmail} accessibilityLabel="Email address" keyboardType="email-address" autoCapitalize="none" autoCorrect={false} />
      </FieldShell>
    </Frame>
  );
}

/** Give a member a login: an emailed invitation, or a first password. */
export function MemberLoginDrawer({ team, member, onClose, onSaved }: MemberBase) {
  const { api } = useSession();
  const [email, setEmail] = useState(member.email);
  const [password, setPassword] = useState('');
  const submit = useSubmit(onSaved);
  return (
    <Frame
      title="Give a login"
      subtitle={member.name}
      label="Give login"
      {...submit}
      onClose={onClose}
      onSubmit={() =>
        void submit.run(async () => {
          const answer = await api.call(PartnerTeamService.method.createMemberLogin, {
            partnerId: team.partnerId, memberId: member.memberId, email, password,
          });
          if (answer.invitationLink) {
            return `No email could be sent: hand ${member.name} this link: ${answer.invitationLink}`;
          }
          return answer.invited
            ? `An invitation was emailed to ${email.trim().toLowerCase()}.`
            : `${member.name} signs in with the password you chose and must change it.`;
        })
      }
    >
      <DrawerText text={`${member.name} signs in as ${team.partnerName}, a Partner Field Officer. They see the organisation's work but do not run the team.`} />
      <FieldShell label="Email address" isRequired>
        <DrawerInput value={email} onChangeText={setEmail} accessibilityLabel="Email address" keyboardType="email-address" autoCapitalize="none" autoCorrect={false} />
      </FieldShell>
      <FieldShell label="First password" isOptional help="Leave empty to email an invitation. A password you choose must be changed at the first sign-in.">
        <DrawerInput value={password} onChangeText={setPassword} accessibilityLabel="First password" secureTextEntry autoCapitalize="none" />
      </FieldShell>
    </Frame>
  );
}

/** Reset a member's password: one they must change. */
export function MemberPasswordDrawer({ team, member, onClose, onSaved }: MemberBase) {
  const { api } = useSession();
  const [password, setPassword] = useState('');
  const submit = useSubmit(onSaved);
  return (
    <Frame
      title="Reset password"
      subtitle={member.name}
      label="Set password"
      {...submit}
      onClose={onClose}
      onSubmit={() =>
        void submit.run(async () => {
          await api.call(PartnerTeamService.method.resetMemberPassword, { partnerId: team.partnerId, memberId: member.memberId, password });
          return `${member.name}'s password was set. They must change it when they sign in.`;
        })
      }
    >
      <FieldShell label="New password" isRequired help="Their sessions end, and they must change it at the next sign-in.">
        <DrawerInput value={password} onChangeText={setPassword} accessibilityLabel="New password" secureTextEntry autoCapitalize="none" />
      </FieldShell>
    </Frame>
  );
}

/** The schools this member looks after, from those the organisation holds. */
export function MemberSchoolsDrawer({ team, member, onClose, onSaved }: MemberBase) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [chosen, setChosen] = useState<readonly string[]>(
    team.schools.filter((school) => school.memberId === member.memberId).map((school) => school.schoolId),
  );
  const submit = useSubmit(onSaved);
  const names = new Map(team.members.map((m) => [m.memberId, m.name]));
  const toggle = (id: string) =>
    setChosen((current) => (current.includes(id) ? current.filter((held) => held !== id) : [...current, id]));
  return (
    <Frame
      title="Schools"
      subtitle={member.name}
      label="Save schools"
      {...submit}
      onClose={onClose}
      onSubmit={() =>
        void submit.run(async () => {
          const answer = await api.call(PartnerTeamService.method.setMemberSchools, {
            partnerId: team.partnerId, memberId: member.memberId, schoolIds: [...chosen],
          });
          const named = answer.activitiesNamed ? ` ${answer.activitiesNamed} open ${answer.activitiesNamed === 1 ? 'activity now names' : 'activities now name'} them.` : '';
          return `${member.name} looks after ${chosen.length} ${chosen.length === 1 ? 'school' : 'schools'}.${named}`;
        })
      }
    >
      <DrawerText text="A school another member has moves to this one, with its unfinished work. Unticking a school leaves it with nobody." />
      <View style={[styles.list, { borderColor: colors.border }]} accessibilityRole="list">
        {team.schools.map((school, index) => {
          const isOn = chosen.includes(school.schoolId);
          const other = school.memberId && school.memberId !== member.memberId ? names.get(school.memberId) : '';
          return (
            <Pressable
              key={school.schoolId}
              onPress={() => toggle(school.schoolId)}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: isOn }}
              accessibilityLabel={school.name}
              style={[styles.row, index > 0 && { borderTopWidth: 1, borderTopColor: colors.border }]}
            >
              <View style={[styles.box, { borderColor: isOn ? colors.primary : colors.fieldBorder, backgroundColor: isOn ? colors.primary : colors.surface }]}>
                {isOn ? <Check size={14} color={colors.primaryInk} /> : null}
              </View>
              <View style={styles.grow}>
                <Text style={[styles.name, { color: colors.text }]}>{school.name}</Text>
                <Text style={[styles.meta, { color: colors.textMuted }]}>
                  {[school.district, other && !isOn ? `with ${other}` : ''].filter(Boolean).join(' · ')}
                </Text>
              </View>
            </Pressable>
          );
        })}
        {team.schools.length === 0 ? <DrawerText text="The organisation holds no schools yet." /> : null}
      </View>
    </Frame>
  );
}

/** Remove a member: their own login stops signing in; their schools go back to nobody. */
export function RemoveMemberDrawer({ team, member, onClose, onSaved }: MemberBase) {
  const { api } = useSession();
  const submit = useSubmit(onSaved);
  return (
    <Frame
      title="Remove from team"
      subtitle={member.name}
      label="Remove"
      {...submit}
      onClose={onClose}
      onSubmit={() =>
        void submit.run(async () => {
          await api.call(PartnerTeamService.method.removeMember, { partnerId: team.partnerId, memberId: member.memberId });
          return `${member.name} was removed from the team.`;
        })
      }
    >
      <DrawerText
        tone="danger"
        text={`${member.name} leaves ${team.partnerName}'s team.${member.login ? ' Their own login stops signing in.' : ''} Schools they looked after go back to nobody; work already delivered keeps their name.`}
      />
    </Frame>
  );
}

const styles = StyleSheet.create({
  footer: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
  list: { borderWidth: 1, borderRadius: radius.sm, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 52, paddingHorizontal: 12, paddingVertical: 8 },
  box: { width: 22, height: 22, borderWidth: 1.5, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  grow: { flex: 1, gap: 2 },
  name: { fontFamily: fonts.semibold, fontSize: 14 },
  meta: { fontFamily: fonts.medium, fontSize: 12 },
});
