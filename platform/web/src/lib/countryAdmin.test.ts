import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { CountryConfigSchema, CountrySchema } from '@/gen/edify/countries/v1/countries_pb';

import {
  accountsTable,
  canRecordSettings,
  countriesTable,
  dateExample,
  dayText,
  grantRequest,
  grantableCountries,
  kampalaToday,
  languageList,
  membershipStatus,
  membershipsPath,
  recordRefusal,
  revokeRequest,
  settingsForm,
  settingsRequest,
  versionsTable,
} from './countryAdmin';

const TODAY = '2026-11-18';

const uganda = create(CountrySchema, {
  code: 'UG',
  name: 'Uganda',
  state: 'active',
  activatedOn: '2026-11-17',
  config: create(CountryConfigSchema, {
    version: 1,
    defaultLanguage: 'en',
    languages: ['en'],
    currencyCode: 'UGX',
    currencyMinorUnits: 0,
    timeZone: 'Africa/Kampala',
    dateFormat: 'j M Y',
    calendars: ['gregorian'],
    fyStartMonth: 7,
    effectiveFrom: '2026-11-17',
    changedBy: 'u-admin',
    changeReason: 'Uganda as it works today',
  }),
});
const kenya = create(CountrySchema, { code: 'KE', name: 'Kenya', state: 'draft' });

describe('country administration', () => {
  it('records settings only before a country is Active', () => {
    expect(canRecordSettings('draft')).toBe(true);
    expect(canRecordSettings('ready_for_pilot')).toBe(true);
    expect(canRecordSettings('active')).toBe(false);
    expect(canRecordSettings('suspended')).toBe(false);
    expect(canRecordSettings('archived')).toBe(false);
    expect(recordRefusal(uganda)).toMatch(/approved change, which is not built yet/);
  });

  it('draws days, stamps and date notations in words', () => {
    expect(dayText('2027-01-01')).toBe('1 Jan 2027');
    expect(dayText('', 'No end')).toBe('No end');
    expect(dateExample('j M Y')).toBe('5 Jul 2027');
    expect(dateExample('d/m/Y')).toBe('05/07/2027');
    expect(dateExample('j F Y')).toBe('5 July 2027');
    expect(kampalaToday(new Date('2026-11-17T22:30:00Z'))).toBe('2026-11-18');
  });

  it('lists every country with the settings in force and links each to its page', () => {
    const table = countriesTable([kenya, uganda]);
    expect(table.count).toBe('2');
    expect(table.rows[0]?.cells.map((c) => c.text)).toEqual(['KE', 'Kenya', 'Draft', 'Not yet', '—', '—', '—', '—', 'None in force']);
    expect(table.rows[1]?.cells[1]?.href).toBe('/countries/UG');
    expect(table.rows[1]?.cells[5]?.text).toBe('UGX · whole amounts');
    expect(table.rows[1]?.cells[7]?.text).toBe('July');
  });

  it('names who recorded each settings version', () => {
    const table = versionsTable([uganda.config!], new Map([['u-admin', 'Grace Admin']]));
    expect(table.rows[0]?.cells[9]?.text).toMatch(/^Grace Admin · /);
    expect(table.rows[0]?.cells[2]?.text).toBe('No end');
  });

  it('offers grants for every country but an archived one', () => {
    const archived = create(CountrySchema, { code: 'ET', state: 'archived' });
    expect(grantableCountries([uganda, kenya, archived]).map((c) => c.code)).toEqual(['UG', 'KE']);
  });

  it('says what a membership means today', () => {
    const base = { revokedAt: '', inForce: true, effectiveFrom: '2026-11-17', effectiveUntil: '', countryState: 'active' };
    expect(membershipStatus(base, TODAY)).toEqual({ label: 'In force', tone: 'success' });
    expect(membershipStatus({ ...base, revokedAt: '2026-11-18T10:00:00Z' }, TODAY).label).toBe('Revoked');
    expect(membershipStatus({ ...base, effectiveUntil: TODAY, inForce: false }, TODAY).label).toBe('Ended');
    expect(membershipStatus({ ...base, effectiveFrom: '2027-01-01', inForce: false }, TODAY).label).toBe('Starts 1 Jan 2027');
    expect(membershipStatus({ ...base, inForce: false, countryState: 'draft' }, TODAY)).toEqual({
      label: 'Not in force: Draft country',
      tone: 'warning',
    });
  });

  it('builds a grant only when it can be accepted', () => {
    const form = { userId: 'u1', countryCode: 'KE', from: '', until: '2027-01-01', reason: ' Kenya pilot ' };
    expect(grantRequest(form, TODAY)).toEqual({ userId: 'u1', countryCode: 'KE', effectiveFrom: '', effectiveUntil: '2027-01-01', reason: 'Kenya pilot' });
    expect(grantRequest({ ...form, userId: '' }, TODAY)).toBe('Choose the account first.');
    expect(grantRequest({ ...form, countryCode: '' }, TODAY)).toBe('Choose the country.');
    expect(grantRequest({ ...form, from: '2026-11-01' }, TODAY)).toMatch(/past/);
    expect(grantRequest({ ...form, until: TODAY }, TODAY)).toMatch(/after the start/);
    expect(grantRequest({ ...form, from: '2027-02-01', until: '2027-01-01' }, TODAY)).toMatch(/after the start/);
    expect(grantRequest({ ...form, reason: '  ' }, TODAY)).toMatch(/reason is required/);
    expect(grantRequest({ ...form, reason: 'x'.repeat(501) }, TODAY)).toMatch(/500 characters/);
  });

  it('asks why before a revocation', () => {
    expect(revokeRequest('m1', ' Left Edify Kenya ')).toEqual({ membershipId: 'm1', reason: 'Left Edify Kenya' });
    expect(revokeRequest('m1', '')).toMatch(/reason is required/);
  });

  it('opens the settings form on the settings in force and checks it before sending', () => {
    const form = settingsForm(uganda.config);
    expect(form.languages).toBe('en');
    expect(settingsRequest('UG', { ...form, reason: 'Test' }, TODAY)).toMatchObject({ currencyCode: 'UGX', calendars: ['gregorian'], fyStartMonth: 7 });

    const ethiopia = {
      ...settingsForm(undefined),
      languages: 'am, en',
      defaultLanguage: 'am',
      currencyCode: 'etb',
      currencyMinorUnits: '2',
      timeZone: 'Africa/Addis_Ababa',
      ethiopian: true,
      reason: 'Ethiopia draft',
    };
    expect(settingsRequest('ET', ethiopia, TODAY)).toMatchObject({ languages: ['am', 'en'], currencyCode: 'ETB', currencyMinorUnits: 2, calendars: ['gregorian', 'ethiopian'] });
    expect(settingsRequest('ET', { ...ethiopia, languages: 'Amharic' }, TODAY)).toMatch(/not a language code/);
    expect(settingsRequest('ET', { ...ethiopia, languages: 'am, am' }, TODAY)).toMatch(/twice/);
    expect(settingsRequest('ET', { ...ethiopia, defaultLanguage: 'sw' }, TODAY)).toMatch(/one of the languages/);
    expect(settingsRequest('ET', { ...ethiopia, currencyCode: 'BIRR' }, TODAY)).toMatch(/three-letter/);
    expect(settingsRequest('ET', { ...ethiopia, currencyMinorUnits: '4' }, TODAY)).toMatch(/0 to 3/);
    expect(settingsRequest('ET', { ...ethiopia, timeZone: ' ' }, TODAY)).toMatch(/time zone/);
    expect(settingsRequest('ET', { ...ethiopia, from: '2026-01-01' }, TODAY)).toMatch(/past/);
    expect(settingsRequest('ET', { ...ethiopia, reason: '' }, TODAY)).toMatch(/reason is required/);
    expect(settingsRequest('ET', ethiopia, TODAY, TODAY)).toMatch(/after 18 Nov 2026/);
    expect(settingsRequest('ET', { ...ethiopia, from: '2026-11-19' }, TODAY, TODAY)).toMatchObject({ effectiveFrom: '2026-11-19' });
  });

  it('lists the accounts a search found, each opening its memberships', () => {
    const found = [
      { userId: 'u1', name: 'Ann Okello', email: 'ann@edify.org', activeRole: 'CCEO', status: 'active' },
      { userId: 'u2', name: '', email: 'bo@edify.org', activeRole: '', status: 'pending_invited' },
    ];
    const table = accountsTable(found, 'o', 'u2', 45);
    expect(table.count).toBe('45');
    expect(table.subtitle).toMatch(/first 2 of 45/);
    expect(table.rows[0]?.cells[0]).toMatchObject({ text: 'Ann Okello', href: '/countries/memberships?q=o&user=u1' });
    expect(table.rows[1]?.cells.map((c) => c.text)).toEqual(['bo@edify.org', 'bo@edify.org', '—', 'Invited']);
    expect(table.rows[1]?.tone).toBe('selected');
    expect(accountsTable([], 'zz', '', 0).subtitle).toBe('');
  });

  it('reads a typed language list and builds the memberships link', () => {
    expect(languageList(' sw,en  rw ')).toEqual(['sw', 'en', 'rw']);
    expect(membershipsPath('u 1', 'ann')).toBe('/countries/memberships?q=ann&user=u+1');
    expect(membershipsPath('')).toBe('/countries/memberships');
  });
});
