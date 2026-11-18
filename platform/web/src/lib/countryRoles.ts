/*
 * Role and scope per country (docs/migration/80, §12) as the Memberships
 * page shows and asks for them: which memberships can carry roles, the
 * words for a role's scope, and the assign and revoke requests checked
 * before they are sent. The gateway checks everything again.
 */
import type { JsonObject } from '@bufbuild/protobuf';

import type { AssignableRole, CountryRole, Membership, Region } from '@/gen/edify/countries/v1/countries_pb';

import { reasonProblem } from './countryAdmin';

export const ROLES_FROM_REGISTRY = 'registry';
export const SCOPE_REGIONS = 'regions';

const SCOPE_WORDS: Readonly<Record<string, string>> = {
  country: 'Whole country',
  regions: 'Regions',
  portfolio: 'Own portfolio',
};

/** The scope in words: "Whole country", "Own portfolio" or "Regions: A, B". */
export function scopeText(scopeType: string, regionNames: readonly string[] = []): string {
  const words = SCOPE_WORDS[scopeType] ?? scopeType;
  return scopeType === SCOPE_REGIONS && regionNames.length ? `${words}: ${regionNames.join(', ')}` : words;
}

/** The roles a membership carries today (not revoked), oldest first. */
export function heldRoles(m: Pick<Membership, 'roles'>): CountryRole[] {
  return m.roles.filter((r) => !r.revokedAt).reverse();
}

/** The Memberships table's Roles cell. */
export function rolesCellText(m: Pick<Membership, 'rolesSource' | 'roles'>): string {
  if (m.rolesSource !== ROLES_FROM_REGISTRY) return 'From the existing profile';
  const held = heldRoles(m);
  return held.length ? held.map((r) => r.roleLabel || r.role).join(', ') : 'None yet';
}

/** Why a role cannot be assigned under this membership; empty when it can. */
export function assignRefusal(m: Pick<Membership, 'rolesSource' | 'revokedAt' | 'effectiveUntil' | 'countryName'>, today: string): string {
  if (m.rolesSource !== ROLES_FROM_REGISTRY) return `${m.countryName}'s roles come from the existing profile`;
  if (m.revokedAt) return 'Revoked';
  if (m.effectiveUntil && m.effectiveUntil <= today) return 'Ended';
  return '';
}

/** The regions a role may cover in one country. */
export function regionsOf(regions: readonly Region[], countryCode: string): Region[] {
  return regions.filter((r) => r.countryCode === countryCode);
}

export interface RoleForm {
  readonly membershipId: string;
  readonly role: string;
  readonly regionIds: readonly string[];
  readonly reason: string;
}

export function assignRoleRequest(form: RoleForm, choices: readonly AssignableRole[]): JsonObject | string {
  if (!form.membershipId) return 'Choose the membership first.';
  const choice = choices.find((c) => c.role === form.role);
  if (!choice) return 'Choose the role.';
  const regional = choice.scopeType === SCOPE_REGIONS;
  if (regional && !form.regionIds.length) return `${choice.label || choice.role} covers regions: choose at least one.`;
  const problem = reasonProblem(form.reason);
  if (problem) return problem;
  return { membershipId: form.membershipId, role: form.role, regionIds: regional ? [...form.regionIds] : [], reason: form.reason.trim() };
}

export function revokeRoleRequest(roleId: string, reason: string): JsonObject | string {
  const problem = reasonProblem(reason);
  if (problem) return problem;
  return { roleId, reason: reason.trim() };
}
