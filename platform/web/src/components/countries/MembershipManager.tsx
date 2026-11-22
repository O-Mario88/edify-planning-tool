'use client';

/*
 * One account's country memberships: every one ever recorded (revoked ones
 * keep their record and reason), a grant, and a revocation that asks why in
 * place. The gateway decides: only an Admin, never on their own account,
 * and never a first grant that would take away the country the account
 * works in through its profile. A change reads the list again in place.
 * Where a country's roles come from the registry, its memberships carry the
 * roles the account holds there (CountryRoles.tsx).
 */
import { fromJson } from '@bufbuild/protobuf';
import { useState } from 'react';
import { EdifyDatePicker } from '@/components/ui/EdifyDatePicker';

import { GrantMembershipResponseSchema, ListMembershipsResponseSchema } from '@/gen/edify/countries/v1/countries_pb';
import type { AssignableRole, Membership, Region } from '@/gen/edify/countries/v1/countries_pb';
import { postCountryAdmin } from '@/lib/countryAdminClient';
import { MAX_REASON, dayText, grantRequest, membershipStatus, revokeRequest, stampText } from '@/lib/countryAdmin';
import { ROLES_FROM_REGISTRY, assignRefusal, rolesCellText } from '@/lib/countryRoles';

import { Badge } from '../blocks/Badge';
import { BUTTON_OUTLINE, BUTTON_PRIMARY } from '../blocks/buttons';
import { Card } from '../blocks/Card';
import { RowActions } from '../blocks/RowActions';
import { AssignRoleForm, CountryRolesCard } from './CountryRoles';
import { CELL, DESTRUCTIVE, FIELD, HINT, LABEL, NoticeLine } from './fields';

export interface ManagedPerson {
  readonly userId: string;
  readonly name: string;
  readonly email: string;
  readonly activeRole: string;
}

export interface GrantChoice {
  readonly code: string;
  readonly name: string;
  readonly state: string;
}

interface ManagerProps {
  readonly account: ManagedPerson;
  readonly memberships: readonly Membership[];
  readonly assignableRoles: readonly AssignableRole[];
  readonly regions: readonly Region[];
  readonly countries: readonly GrantChoice[];
  readonly names: Readonly<Record<string, string>>;
  readonly reader: { readonly userId: string; readonly name: string };
  readonly today: string;
}


type Opened = { readonly id: string; readonly kind: 'revoke' | 'assign' };
const CLOSED: Opened = { id: '', kind: 'revoke' };

export function MembershipManager({ account, memberships, assignableRoles, regions, countries, names, reader, today }: ManagerProps) {
  const [list, setList] = useState(memberships);
  const [choices, setChoices] = useState(assignableRoles);
  const [regionList, setRegionList] = useState(regions);
  const [notice, setNotice] = useState('');
  const [opened, setOpened] = useState<Opened>(CLOSED);
  const isSelf = account.userId === reader.userId;
  const who = (id: string) => (id === reader.userId ? reader.name : (names[id] ?? id));

  const reload = async () => {
    const answer = await postCountryAdmin('memberships', { userId: account.userId });
    const read = fromJson(ListMembershipsResponseSchema, answer);
    setList(read.memberships);
    setChoices(read.assignableRoles);
    setRegionList(read.regions);
  };
  const hasRegistryCountry = list.some((m) => m.rolesSource === ROLES_FROM_REGISTRY);

  return (
    <>
      <Card flush label="Memberships">
        <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--edify-border)] bg-[var(--edify-surface-muted)] px-4 py-2.5">
          <h2 className="text-[length:var(--edify-text-title-size)] font-bold">Memberships</h2>
          <span className="ml-auto text-[length:var(--edify-text-label-size)] font-semibold" data-count>
            {list.length}
          </span>
        </header>
        {notice ? (
          <p role="status" className="border-b border-[var(--edify-border)] px-4 py-2 text-[13px] font-semibold text-[#047857] dark:text-[var(--edify-success)]">
            {notice}
          </p>
        ) : null}
        {list.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[60rem] border-collapse text-left text-[13.7px]">
              <thead>
                <tr className="border-b border-[var(--edify-border)] text-[length:var(--edify-text-label-size)]">
                  {['Country', 'Status', 'From', 'Until', 'Default', 'Roles', 'Granted', 'Revoked'].map((label) => (
                    <th key={label} scope="col" className={`${CELL} font-bold`}>
                      {label}
                    </th>
                  ))}
                  {isSelf ? null : (
                    <th scope="col" className={`${CELL} w-px`}>
                      <span className="sr-only">Actions</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {list.map((m) => (
                  <MembershipRow
                    key={m.id}
                    membership={m}
                    today={today}
                    who={who}
                    actionable={!isSelf}
                    opened={opened.id === m.id ? opened.kind : ''}
                    onOpen={(kind) => setOpened({ id: m.id, kind })}
                    onClose={() => setOpened(CLOSED)}
                    onRevoked={async () => {
                      setOpened(CLOSED);
                      setNotice(`${m.countryName} membership revoked. Its record and reason are kept.`);
                      await reload();
                    }}
                    assignForm={
                      <AssignRoleForm
                        membership={m}
                        choices={choices}
                        regions={regionList}
                        onClose={() => setOpened(CLOSED)}
                        onAssigned={async (label) => {
                          setOpened(CLOSED);
                          setNotice(`${label} assigned in ${m.countryName}.`);
                          await reload();
                        }}
                      />
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="px-4 py-4 text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
            {account.name} has no country membership yet. Until the first one, the account works in the country its staff profile names. Grant
            that country first: a first membership of another country would take it away, and the platform refuses that.
          </p>
        )}
      </Card>
      {hasRegistryCountry ? (
        <CountryRolesCard
          memberships={list}
          who={who}
          actionable={!isSelf}
          onRevoked={async (role, countryName) => {
            setNotice(`${role.roleLabel || role.role} in ${countryName} revoked. Its record and reason are kept.`);
            await reload();
          }}
        />
      ) : null}
      {isSelf ? (
        <Card>
          <p className="text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
            These are your own memberships. Another Admin grants or revokes your countries.
          </p>
        </Card>
      ) : (
        <GrantForm
          account={account}
          countries={countries}
          today={today}
          onGranted={async (granted) => {
            setNotice(`${granted.countryName} granted from ${dayText(granted.effectiveFrom)}.`);
            await reload();
          }}
        />
      )}
    </>
  );
}

interface RowProps {
  readonly membership: Membership;
  readonly today: string;
  readonly who: (id: string) => string;
  readonly actionable: boolean;
  /** Which form is open below the row, if any. */
  readonly opened: '' | 'revoke' | 'assign';
  readonly onOpen: (kind: 'revoke' | 'assign') => void;
  readonly onClose: () => void;
  readonly onRevoked: () => Promise<void>;
  readonly assignForm: React.ReactNode;
}

function MembershipRow({ membership: m, today, who, actionable, opened, onOpen, onClose, onRevoked, assignForm }: RowProps) {
  const status = membershipStatus(m, today);
  const span = actionable ? 9 : 8;
  const cannotAssign = assignRefusal(m, today);
  return (
    <>
      <tr className="border-b border-[var(--edify-table-divider)]" data-membership={m.countryCode}>
        <td className={`${CELL} font-bold`}>
          {m.countryName} <span className="font-medium text-[var(--edify-text-muted)]">{m.countryCode}</span>
        </td>
        <td className={CELL}>
          <Badge tone={status.tone}>{status.label}</Badge>
        </td>
        <td className={CELL}>{dayText(m.effectiveFrom)}</td>
        <td className={CELL}>{dayText(m.effectiveUntil, 'No end')}</td>
        <td className={CELL}>{m.isDefault ? 'Yes' : 'No'}</td>
        <td className={`${CELL} whitespace-normal`}>{rolesCellText(m)}</td>
        <td className={`${CELL} whitespace-normal`}>
          <span className="font-semibold">{who(m.grantedBy)}</span> · {stampText(m.grantedAt)}
          <span className="block max-w-[22rem] text-[var(--edify-text-muted)]">{m.grantReason}</span>
        </td>
        <td className={`${CELL} whitespace-normal`}>
          {m.revokedAt ? (
            <>
              <span className="font-semibold">{who(m.revokedBy)}</span> · {stampText(m.revokedAt)}
              <span className="block max-w-[22rem] text-[var(--edify-text-muted)]">{m.revokeReason}</span>
            </>
          ) : (
            '—'
          )}
        </td>
        {actionable ? (
          <td className={`${CELL} w-px`}>
            <RowActions
              subject={`${m.countryName} membership`}
              actions={[
                {
                  key: 'assign-role',
                  label: 'Assign role',
                  enabled: !cannotAssign,
                  reason: cannotAssign,
                  href: '',
                  onSelect: () => onOpen('assign'),
                },
                {
                  key: 'revoke',
                  label: 'Revoke membership',
                  enabled: !m.revokedAt,
                  reason: m.revokedAt ? 'Already revoked' : '',
                  href: '',
                  onSelect: () => onOpen('revoke'),
                },
              ]}
            />
          </td>
        ) : null}
      </tr>
      {opened ? (
        <tr className="border-b border-[var(--edify-table-divider)] bg-[var(--edify-surface-muted)]">
          <td colSpan={span} className="px-4 py-3">
            {opened === 'assign' ? assignForm : <RevokeForm membership={m} onClose={onClose} onRevoked={onRevoked} />}
          </td>
        </tr>
      ) : null}
    </>
  );
}

function RevokeForm({ membership, onClose, onRevoked }: { membership: Membership; onClose: () => void; onRevoked: () => Promise<void> }) {
  const [reason, setReason] = useState('');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);
  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    const request = revokeRequest(membership.id, reason);
    if (typeof request === 'string') {
      setProblem(request);
      return;
    }
    setBusy(true);
    setProblem('');
    try {
      await postCountryAdmin('revoke', request);
      await onRevoked();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'The membership could not be revoked.');
      setBusy(false);
    }
  };
  return (
    <form onSubmit={send} className="flex flex-col gap-3" noValidate aria-label={`Revoke ${membership.countryName} membership`}>
      <label className={LABEL}>
        Why is the {membership.countryName} membership revoked?
        <input className={FIELD} name="revokeReason" maxLength={MAX_REASON} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
        <span className={HINT}>The membership stays on record with this reason. A new grant of {membership.countryName} must start on another day.</span>
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className={DESTRUCTIVE} disabled={busy}>
          {busy ? 'Revoking…' : 'Revoke Membership'}
        </button>
        <button type="button" className={BUTTON_OUTLINE} onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <NoticeLine problem={problem} notice="" />
      </div>
    </form>
  );
}

interface GrantProps {
  readonly account: ManagedPerson;
  readonly countries: readonly GrantChoice[];
  readonly today: string;
  readonly onGranted: (granted: Membership) => Promise<void>;
}

function GrantForm({ account, countries, today, onGranted }: GrantProps) {
  const [countryCode, setCountryCode] = useState('');
  const [from, setFrom] = useState('');
  const [until, setUntil] = useState('');
  const [reason, setReason] = useState('');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);
  const chosen = countries.find((c) => c.code === countryCode);

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    const request = grantRequest({ userId: account.userId, countryCode, from, until, reason }, today);
    if (typeof request === 'string') {
      setProblem(request);
      return;
    }
    setBusy(true);
    setProblem('');
    try {
      const answer = await postCountryAdmin('grant', request);
      const granted = fromJson(GrantMembershipResponseSchema, answer).granted;
      setCountryCode('');
      setFrom('');
      setUntil('');
      setReason('');
      if (granted) await onGranted(granted);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'The membership could not be granted.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card label="Grant a country">
      <h2 className="text-[length:var(--edify-text-title-size)] font-bold">Grant a Country</h2>
      <p className={HINT}>
        A membership lets {account.name} work in a country; their role, scope and portfolio still decide which records they see. In Uganda the
        role is the existing profile&apos;s; in any other country, assign the roles they hold there from the membership&apos;s Actions. A country
        that is not Active gives no access until it is activated.
      </p>
      <form onSubmit={send} className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" noValidate>
        <label className={LABEL}>
          Country
          <select className={FIELD} name="countryCode" value={countryCode} onChange={(e) => setCountryCode(e.target.value)}>
            <option value="">Choose a country</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name} ({c.code}){c.state === 'active' ? '' : ` · ${c.state.replaceAll('_', ' ')}`}
              </option>
            ))}
          </select>
          {chosen && chosen.state !== 'active' ? <span className={HINT}>{chosen.name} is not Active: this grant gives no access yet.</span> : null}
        </label>
        <div className={LABEL}>
          Starts
          <EdifyDatePicker name="effectiveFrom" label="Starts" min={today} value={from} onChange={setFrom} size="sm" policy={{ mode: 'free' }} />
          <span className={HINT}>Leave empty for today.</span>
        </div>
        <div className={LABEL}>
          Ends
          <EdifyDatePicker name="effectiveUntil" label="Ends" min={from || today} value={until} onChange={setUntil} size="sm" policy={{ mode: 'free' }} />
          <span className={HINT}>The first day it no longer applies. Leave empty for no end.</span>
        </div>
        <label className={`${LABEL} sm:col-span-2 lg:col-span-4`}>
          Reason
          <textarea className={FIELD} name="reason" rows={2} maxLength={MAX_REASON} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why this account works in this country" />
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2 lg:col-span-4">
          <button type="submit" className={`${BUTTON_PRIMARY} disabled:opacity-60`} disabled={busy}>
            {busy ? 'Granting…' : 'Grant Country'}
          </button>
          <NoticeLine problem={problem} notice="" />
        </div>
      </form>
    </Card>
  );
}
