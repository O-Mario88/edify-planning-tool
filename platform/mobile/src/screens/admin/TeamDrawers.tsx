/**
 * Who a person reports to, and who a manager manages, from the Admin's Users
 * screen — the existing Role Configuration's two team settings, served by the
 * gateway's StaffTeamService. A CCEO reports to a Program Lead and a Program
 * Lead to a Country Director; a Country Director's team is the country.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { Check } from 'lucide-react-native';

import { describe, useSession } from '../../auth/SessionContext';
import type { ManagedAccount } from '../../gen/edify/identity/v1/accounts_pb';
import type { GetManagedTeamResponse, GetSupervisorResponse } from '../../gen/edify/identity/v1/teams_pb';
import { StaffTeamService } from '../../gen/edify/identity/v1/teams_pb';
import { fonts, radius, useTheme } from '../../theme';
import { Drawer } from '../../ui/Drawer';
import { DrawerButton, DrawerNote, DrawerText, FieldShell } from '../../ui/drawerParts';
import { Select } from '../../ui/Select';
import { roleLabel } from './accountsData';

interface TeamDrawerProps {
  readonly account: ManagedAccount;
  readonly onClose: () => void;
  readonly onSaved: (message: string) => void;
}

function Footer({ label, isBusy, isDisabled, onCancel, onSubmit }: {
  readonly label: string;
  readonly isBusy: boolean;
  readonly isDisabled?: boolean;
  readonly onCancel: () => void;
  readonly onSubmit: () => void;
}) {
  return (
    <View style={styles.footer}>
      <DrawerButton label="Cancel" onPress={onCancel} />
      <DrawerButton label={label} onPress={onSubmit} isPrimary isBusy={isBusy} isDisabled={isDisabled} />
    </View>
  );
}

/** Supervisor: the person's reporting line, chosen from those of the right role. */
export function SupervisorDrawer({ account, onClose, onSaved }: TeamDrawerProps) {
  const { api } = useSession();
  const [found, setFound] = useState<GetSupervisorResponse | null>(null);
  const [choice, setChoice] = useState('');
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let isLive = true;
    api
      .call(StaffTeamService.method.getSupervisor, { userId: account.userId })
      .then((answer) => {
        if (isLive) {
          setFound(answer);
          setChoice(answer.staff?.supervisorStaffId ?? '');
        }
      })
      .catch((cause: unknown) => {
        if (isLive) {
          setError(describe(cause));
        }
      });
    return () => {
      isLive = false;
    };
  }, [api, account.userId]);

  async function submit() {
    if (!choice) {
      setError('Choose who supervises this person.');
      return;
    }
    setIsBusy(true);
    setError('');
    try {
      const answer = await api.call(StaffTeamService.method.assignSupervisor, { userId: account.userId, supervisorStaffId: choice });
      onSaved(`${account.name} now reports to ${answer.newSupervisorName}.`);
    } catch (cause) {
      setError(describe(cause));
      setIsBusy(false);
    }
  }

  const current = found?.staff?.supervisorName;
  return (
    <Drawer
      title="Supervisor"
      subtitle={account.name}
      onClose={onClose}
      footer={<Footer label="Save supervisor" isBusy={isBusy} isDisabled={!found} onCancel={onClose} onSubmit={() => void submit()} />}
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      {found ? (
        <>
          <DrawerText text={current ? `Reports to ${current} now.` : 'Reports to nobody yet.'} />
          <FieldShell
            label="Supervisor"
            isRequired
            help={found.expectedRole ? `A ${roleLabel(account.activeRole)} reports to a ${roleLabel(found.expectedRole)}.` : undefined}
          >
            <Select
              label="Supervisor"
              value={choice}
              placeholder="Choose a supervisor"
              variant="form"
              choices={found.choices.map((person) => ({ value: person.staffId, label: `${person.name} · ${roleLabel(person.role)}` }))}
              onChange={setChoice}
            />
          </FieldShell>
        </>
      ) : error ? null : (
        <ActivityIndicator />
      )}
    </Drawer>
  );
}

/** Team: the people a Program Lead, Impact Assessment or RVP manages. */
export function ManagedTeamDrawer({ account, onClose, onSaved }: TeamDrawerProps) {
  const { api } = useSession();
  const { colors } = useTheme();
  const [team, setTeam] = useState<GetManagedTeamResponse | null>(null);
  const [chosen, setChosen] = useState<readonly string[]>([]);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let isLive = true;
    api
      .call(StaffTeamService.method.getManagedTeam, { userId: account.userId })
      .then((answer) => {
        if (isLive) {
          setTeam(answer);
          setChosen(answer.people.filter((person) => person.assigned).map((person) => person.staffId));
        }
      })
      .catch((cause: unknown) => {
        if (isLive) {
          setError(describe(cause));
        }
      });
    return () => {
      isLive = false;
    };
  }, [api, account.userId]);

  async function submit() {
    setIsBusy(true);
    setError('');
    try {
      const answer = await api.call(StaffTeamService.method.configureManagedTeam, { userId: account.userId, staffIds: [...chosen] });
      onSaved(`${account.name} manages ${answer.assignedCount} ${answer.assignedCount === 1 ? 'person' : 'people'}.`);
    } catch (cause) {
      setError(describe(cause));
      setIsBusy(false);
    }
  }

  const toggle = (id: string) =>
    setChosen((current) => (current.includes(id) ? current.filter((held) => held !== id) : [...current, id]));
  const isAutomatic = team?.automatic ?? false;
  return (
    <Drawer
      title="Team"
      subtitle={team?.role ? `${account.name} · ${roleLabel(team.role)}` : account.name}
      onClose={onClose}
      footer={
        isAutomatic ? (
          <View style={styles.footer}>
            <DrawerButton label="Close" onPress={onClose} isPrimary />
          </View>
        ) : (
          <Footer label="Save team" isBusy={isBusy} isDisabled={!team?.role} onCancel={onClose} onSubmit={() => void submit()} />
        )
      }
    >
      {error ? <DrawerNote tone="danger" text={error} /> : null}
      {!team ? (
        error ? null : <ActivityIndicator />
      ) : !team.role ? (
        <DrawerText text={`${account.name} does not work in a role that manages people.`} />
      ) : (
        <>
          <DrawerText
            text={
              isAutomatic
                ? `A Country Director manages every Program Lead, Impact Assessment, Accountant and CCEO in ${team.country} automatically.`
                : team.role === 'Program Lead'
                  ? `CCEOs in ${team.country}. A CCEO has one Program Lead: choosing one from another team moves them here.`
                  : `Edify staff in ${team.country}.`
            }
          />
          <View style={[styles.list, { borderColor: colors.border }]} accessibilityRole="list">
            {team.people.map((person, index) => {
              const isOn = isAutomatic || chosen.includes(person.staffId);
              return (
                <Pressable
                  key={person.staffId}
                  onPress={() => toggle(person.staffId)}
                  disabled={isAutomatic}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: isOn, disabled: isAutomatic }}
                  accessibilityLabel={`${person.name}, ${roleLabel(person.role)}`}
                  style={[styles.person, index > 0 && { borderTopWidth: 1, borderTopColor: colors.border }]}
                >
                  <View style={[styles.box, { borderColor: isOn ? colors.primary : colors.fieldBorder, backgroundColor: isOn ? colors.primary : colors.surface }]}>
                    {isOn ? <Check size={14} color={colors.primaryInk} /> : null}
                  </View>
                  <View style={styles.grow}>
                    <Text style={[styles.name, { color: colors.text }]}>{person.name}</Text>
                    <Text style={[styles.meta, { color: colors.textMuted }]}>
                      {roleLabel(person.role)}
                      {person.otherManager && !chosen.includes(person.staffId) ? ` · with ${person.otherManager}` : ''}
                    </Text>
                  </View>
                </Pressable>
              );
            })}
            {team.people.length === 0 ? <DrawerText text="Nobody in the country can be added." /> : null}
          </View>
        </>
      )}
    </Drawer>
  );
}

const styles = StyleSheet.create({
  footer: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
  list: { borderWidth: 1, borderRadius: radius.sm, overflow: 'hidden' },
  person: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 52, paddingHorizontal: 12, paddingVertical: 8 },
  box: { width: 22, height: 22, borderWidth: 1.5, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  grow: { flex: 1, gap: 2 },
  name: { fontFamily: fonts.semibold, fontSize: 14 },
  meta: { fontFamily: fonts.medium, fontSize: 12 },
});
