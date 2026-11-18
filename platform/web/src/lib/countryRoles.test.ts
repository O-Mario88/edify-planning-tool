import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { AssignableRoleSchema, CountryRoleSchema, MembershipSchema, RegionSchema } from '@/gen/edify/countries/v1/countries_pb';

import { assignRefusal, assignRoleRequest, heldRoles, regionsOf, revokeRoleRequest, rolesCellText, scopeText } from './countryRoles';

const TODAY = '2026-11-18';
const officer = create(CountryRoleSchema, { id: 'r1', role: 'CCEO', roleLabel: 'CCEO', scopeType: 'portfolio', grantedAt: '2026-11-18T08:00:00Z' });
const lead = create(CountryRoleSchema, {
  id: 'r2',
  role: 'RegionalProgramLead',
  roleLabel: 'Regional Programme Lead',
  scopeType: 'regions',
  regionNames: ['Nairobi'],
  grantedAt: '2026-11-18T09:00:00Z',
});
const kenya = create(MembershipSchema, { id: 'm1', countryCode: 'KE', countryName: 'Kenya', rolesSource: 'registry', roles: [lead, officer] });
const uganda = create(MembershipSchema, { id: 'm0', countryCode: 'UG', countryName: 'Uganda', rolesSource: 'existing_profile' });
const choices = [
  create(AssignableRoleSchema, { role: 'CCEO', scopeType: 'portfolio', label: 'CCEO' }),
  create(AssignableRoleSchema, { role: 'RegionalProgramLead', scopeType: 'regions', label: 'Regional Programme Lead' }),
];

describe('country roles', () => {
  it('says what a role covers', () => {
    expect(scopeText('country')).toBe('Whole country');
    expect(scopeText('portfolio')).toBe('Own portfolio');
    expect(scopeText('regions', ['Nairobi', 'Coast'])).toBe('Regions: Nairobi, Coast');
  });

  it('lists the roles held, oldest first, and says where Uganda’s come from', () => {
    expect(heldRoles(kenya).map((r) => r.id)).toEqual(['r1', 'r2']);
    expect(rolesCellText(kenya)).toBe('CCEO, Regional Programme Lead');
    expect(rolesCellText({ ...kenya, roles: [{ ...officer, revokedAt: '2026-11-18T10:00:00Z' }] })).toBe('None yet');
    expect(rolesCellText(uganda)).toBe('From the existing profile');
  });

  it('offers assignment only on a live membership of a registry country', () => {
    expect(assignRefusal(kenya, TODAY)).toBe('');
    expect(assignRefusal(uganda, TODAY)).toMatch(/Uganda's roles come from the existing profile/);
    expect(assignRefusal({ ...kenya, revokedAt: '2026-11-18T10:00:00Z' }, TODAY)).toBe('Revoked');
    expect(assignRefusal({ ...kenya, effectiveUntil: TODAY }, TODAY)).toBe('Ended');
  });

  it('builds an assignment only when it can be accepted', () => {
    const form = { membershipId: 'm1', role: 'CCEO', regionIds: ['g1'], reason: ' Pilot officer ' };
    expect(assignRoleRequest(form, choices)).toEqual({ membershipId: 'm1', role: 'CCEO', regionIds: [], reason: 'Pilot officer' });
    expect(assignRoleRequest({ ...form, membershipId: '' }, choices)).toMatch(/membership/);
    expect(assignRoleRequest({ ...form, role: 'Admin' }, choices)).toBe('Choose the role.');
    expect(assignRoleRequest({ ...form, role: 'RegionalProgramLead', regionIds: [] }, choices)).toMatch(/covers regions/);
    expect(assignRoleRequest({ ...form, role: 'RegionalProgramLead' }, choices)).toMatchObject({ regionIds: ['g1'] });
    expect(assignRoleRequest({ ...form, reason: '' }, choices)).toMatch(/reason is required/);
    expect(revokeRoleRequest('r1', ' Moved on ')).toEqual({ roleId: 'r1', reason: 'Moved on' });
    expect(revokeRoleRequest('r1', ' ')).toMatch(/reason is required/);
  });

  it('keeps one country’s regions', () => {
    const regions = [create(RegionSchema, { id: 'g1', countryCode: 'KE' }), create(RegionSchema, { id: 'g2', countryCode: 'RW' })];
    expect(regionsOf(regions, 'KE').map((r) => r.id)).toEqual(['g1']);
  });
});
