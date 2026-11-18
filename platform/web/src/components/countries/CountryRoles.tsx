'use client';

/*
 * Role and scope per country (docs/migration/80, §12): the roles an account
 * holds in each country whose roles come from the registry, with the scope
 * each has there, an assignment opened under its membership, and a
 * revocation that asks why in place. Uganda's roles are the existing
 * profile's and are not changed here. The gateway decides: only an Admin,
 * never on their own account.
 */
import { useState } from 'react';

import type { AssignableRole, CountryRole, Membership, Region } from '@/gen/edify/countries/v1/countries_pb';
import { MAX_REASON, stampText } from '@/lib/countryAdmin';
import { postCountryAdmin } from '@/lib/countryAdminClient';
import { ROLES_FROM_REGISTRY, SCOPE_REGIONS, assignRoleRequest, regionsOf, revokeRoleRequest, scopeText } from '@/lib/countryRoles';

import { Badge } from '../blocks/Badge';
import { BUTTON_OUTLINE, BUTTON_PRIMARY } from '../blocks/buttons';
import { Card } from '../blocks/Card';
import { RowActions } from '../blocks/RowActions';
import { CELL, DESTRUCTIVE, FIELD, HINT, LABEL, NoticeLine } from './fields';

interface AssignProps {
  readonly membership: Membership;
  readonly choices: readonly AssignableRole[];
  readonly regions: readonly Region[];
  readonly onClose: () => void;
  readonly onAssigned: (label: string) => Promise<void>;
}

/** Assign a role under one membership, opened in place below its row. */
export function AssignRoleForm({ membership, choices, regions, onClose, onAssigned }: AssignProps) {
  const [role, setRole] = useState('');
  const [regionIds, setRegionIds] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);
  const held = new Set(membership.roles.filter((r) => !r.revokedAt).map((r) => r.role));
  const offered = choices.filter((c) => !held.has(c.role));
  const chosen = choices.find((c) => c.role === role);
  const regional = chosen?.scopeType === SCOPE_REGIONS;
  const countryRegions = regionsOf(regions, membership.countryCode);

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    const request = assignRoleRequest({ membershipId: membership.id, role, regionIds, reason }, choices);
    if (typeof request === 'string') {
      setProblem(request);
      return;
    }
    setBusy(true);
    setProblem('');
    try {
      await postCountryAdmin('assignRole', request);
      await onAssigned(chosen?.label || role);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'The role could not be assigned.');
      setBusy(false);
    }
  };

  return (
    <form onSubmit={send} className="grid gap-4 sm:grid-cols-2" noValidate aria-label={`Assign a role in ${membership.countryName}`}>
      <label className={LABEL}>
        Role in {membership.countryName}
        <select className={FIELD} name="role" value={role} onChange={(e) => setRole(e.target.value)} autoFocus>
          <option value="">Choose a role</option>
          {offered.map((c) => (
            <option key={c.role} value={c.role}>
              {c.label || c.role} · {scopeText(c.scopeType)}
            </option>
          ))}
        </select>
        <span className={HINT}>
          The account works in {membership.countryName} only in the roles assigned here, while this membership is in force.
        </span>
      </label>
      {regional ? (
        <fieldset className={LABEL}>
          <legend>Regions</legend>
          {countryRegions.length ? (
            <span className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              {countryRegions.map((r) => (
                <label key={r.id} className="flex items-center gap-2 font-medium">
                  <input
                    type="checkbox"
                    name="regionIds"
                    value={r.id}
                    checked={regionIds.includes(r.id)}
                    onChange={(e) => setRegionIds((ids) => (e.target.checked ? [...ids, r.id] : ids.filter((id) => id !== r.id)))}
                  />
                  {r.name}
                </label>
              ))}
            </span>
          ) : (
            <span className={HINT}>{membership.countryName} has no regions recorded yet. A role that covers regions waits for them.</span>
          )}
        </fieldset>
      ) : null}
      <label className={`${LABEL} sm:col-span-2`}>
        Reason
        <textarea
          className={FIELD}
          name="roleReason"
          rows={2}
          maxLength={MAX_REASON}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={`Why this account holds this role in ${membership.countryName}`}
        />
      </label>
      <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
        <button type="submit" className={`${BUTTON_PRIMARY} disabled:opacity-60`} disabled={busy}>
          {busy ? 'Assigning…' : 'Assign Role'}
        </button>
        <button type="button" className={BUTTON_OUTLINE} onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <NoticeLine problem={problem} notice="" />
      </div>
    </form>
  );
}

interface RolesProps {
  readonly memberships: readonly Membership[];
  readonly who: (id: string) => string;
  readonly actionable: boolean;
  readonly onRevoked: (role: CountryRole, countryName: string) => Promise<void>;
}

/** Every role held under a membership of a registry country, newest first. */
export function CountryRolesCard({ memberships, who, actionable, onRevoked }: RolesProps) {
  const [revoking, setRevoking] = useState('');
  const rows = memberships
    .filter((m) => m.rolesSource === ROLES_FROM_REGISTRY)
    .flatMap((m) => m.roles.map((role) => ({ role, membership: m })))
    .sort((a, b) => (a.role.grantedAt < b.role.grantedAt ? 1 : -1));
  const columns = ['Country', 'Role', 'Scope', 'Status', 'Assigned', 'Revoked'];
  const span = columns.length + (actionable ? 1 : 0);

  return (
    <Card flush label="Country roles">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--edify-border)] bg-[var(--edify-surface-muted)] px-4 py-2.5">
        <h2 className="text-[length:var(--edify-text-title-size)] font-bold">Country Roles</h2>
        <span className="ml-auto text-[length:var(--edify-text-label-size)] font-semibold" data-count>
          {rows.length}
        </span>
      </header>
      {rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[60rem] border-collapse text-left text-[13.7px]">
            <thead>
              <tr className="border-b border-[var(--edify-border)] text-[length:var(--edify-text-label-size)]">
                {columns.map((label) => (
                  <th key={label} scope="col" className={`${CELL} font-bold`}>
                    {label}
                  </th>
                ))}
                {actionable ? (
                  <th scope="col" className={`${CELL} w-px`}>
                    <span className="sr-only">Actions</span>
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {rows.map(({ role, membership }) => (
                <RoleRow
                  key={role.id}
                  role={role}
                  membership={membership}
                  who={who}
                  actionable={actionable}
                  span={span}
                  open={revoking === role.id}
                  onOpen={() => setRevoking(role.id)}
                  onClose={() => setRevoking('')}
                  onRevoked={async () => {
                    setRevoking('');
                    await onRevoked(role, membership.countryName);
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-4 py-4 text-[length:var(--edify-text-label-size)] text-[var(--edify-text-muted)]">
          No role is assigned in a country whose roles come from the registry. Choose Assign role on a membership to add one; until then the
          account works there in no role.
        </p>
      )}
    </Card>
  );
}

interface RoleRowProps {
  readonly role: CountryRole;
  readonly membership: Membership;
  readonly who: (id: string) => string;
  readonly actionable: boolean;
  readonly span: number;
  readonly open: boolean;
  readonly onOpen: () => void;
  readonly onClose: () => void;
  readonly onRevoked: () => Promise<void>;
}

function roleStatus(role: CountryRole, membership: Membership): { label: string; tone: string } {
  if (role.revokedAt) return { label: 'Revoked', tone: 'danger' };
  if (!membership.inForce) return { label: 'Held, membership not in force', tone: 'warning' };
  return { label: 'Held', tone: 'success' };
}

function RoleRow({ role, membership, who, actionable, span, open, onOpen, onClose, onRevoked }: RoleRowProps) {
  const status = roleStatus(role, membership);
  return (
    <>
      <tr className="border-b border-[var(--edify-table-divider)]" data-country-role={role.role}>
        <td className={`${CELL} font-bold`}>
          {membership.countryName} <span className="font-medium text-[var(--edify-text-muted)]">{membership.countryCode}</span>
        </td>
        <td className={`${CELL} font-semibold`}>{role.roleLabel || role.role}</td>
        <td className={`${CELL} whitespace-normal`}>{scopeText(role.scopeType, role.regionNames)}</td>
        <td className={CELL}>
          <Badge tone={status.tone}>{status.label}</Badge>
        </td>
        <td className={`${CELL} whitespace-normal`}>
          <span className="font-semibold">{who(role.grantedBy)}</span> · {stampText(role.grantedAt)}
          <span className="block max-w-[22rem] text-[var(--edify-text-muted)]">{role.grantReason}</span>
        </td>
        <td className={`${CELL} whitespace-normal`}>
          {role.revokedAt ? (
            <>
              <span className="font-semibold">{who(role.revokedBy)}</span> · {stampText(role.revokedAt)}
              <span className="block max-w-[22rem] text-[var(--edify-text-muted)]">{role.revokeReason}</span>
            </>
          ) : (
            '—'
          )}
        </td>
        {actionable ? (
          <td className={`${CELL} w-px`}>
            <RowActions
              subject={`${role.roleLabel || role.role} in ${membership.countryName}`}
              actions={[
                {
                  key: 'revoke-role',
                  label: 'Revoke role',
                  enabled: !role.revokedAt,
                  reason: role.revokedAt ? 'Already revoked' : '',
                  href: '',
                  onSelect: onOpen,
                },
              ]}
            />
          </td>
        ) : null}
      </tr>
      {open ? (
        <tr className="border-b border-[var(--edify-table-divider)] bg-[var(--edify-surface-muted)]">
          <td colSpan={span} className="px-4 py-3">
            <RevokeRoleForm role={role} countryName={membership.countryName} onClose={onClose} onRevoked={onRevoked} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

interface RevokeRoleProps {
  readonly role: CountryRole;
  readonly countryName: string;
  readonly onClose: () => void;
  readonly onRevoked: () => Promise<void>;
}

function RevokeRoleForm({ role, countryName, onClose, onRevoked }: RevokeRoleProps) {
  const [reason, setReason] = useState('');
  const [problem, setProblem] = useState('');
  const [busy, setBusy] = useState(false);
  const label = role.roleLabel || role.role;
  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    const request = revokeRoleRequest(role.id, reason);
    if (typeof request === 'string') {
      setProblem(request);
      return;
    }
    setBusy(true);
    setProblem('');
    try {
      await postCountryAdmin('revokeRole', request);
      await onRevoked();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'The role could not be revoked.');
      setBusy(false);
    }
  };
  return (
    <form onSubmit={send} className="flex flex-col gap-3" noValidate aria-label={`Revoke ${label} in ${countryName}`}>
      <label className={LABEL}>
        Why is {label} in {countryName} revoked?
        <input className={FIELD} name="roleRevokeReason" maxLength={MAX_REASON} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
        <span className={HINT}>The role stays on record with this reason. With no role left in {countryName}, the account cannot work there.</span>
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className={DESTRUCTIVE} disabled={busy}>
          {busy ? 'Revoking…' : 'Revoke Role'}
        </button>
        <button type="button" className={BUTTON_OUTLINE} onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <NoticeLine problem={problem} notice="" />
      </div>
    </form>
  );
}
