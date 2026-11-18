/*
 * Edify Global's Admin pages (docs/migration/80-multi-country-phase-0.md,
 * §11): the words, tables and form checks the Countries, country settings
 * and Memberships pages share. The gateway (CountryService, Go) checks every
 * request again and is the only thing that writes; these checks only spare
 * the Admin a round trip and say what is wrong in plain words.
 */
import { create } from '@bufbuild/protobuf';
import type { JsonObject, MessageInitShape } from '@bufbuild/protobuf';

import type { Country, CountryConfig, Membership } from '@/gen/edify/countries/v1/countries_pb';
import type { ManagedAccount } from '@/gen/edify/identity/v1/accounts_pb';
import { PageLinkTabsSchema, PageTableSchema } from '@/gen/edify/screens/v1/page_pb';
import type { PageLinkTabs, PageRowSchema, PageTable } from '@/gen/edify/screens/v1/page_pb';

type RowInit = MessageInitShape<typeof PageRowSchema>;

export const COUNTRIES_PATH = '/countries';
export const MEMBERSHIPS_PATH = '/countries/memberships';
export const ADMIN_ROLE = 'Admin';

/** At most this many characters in a reason, as the gateway allows. */
export const MAX_REASON = 500;

export function countryPath(code: string): string {
  return `${COUNTRIES_PATH}/${encodeURIComponent(code)}`;
}

export function membershipsPath(userId: string, search = ''): string {
  const query = new URLSearchParams();
  if (search) query.set('q', search);
  if (userId) query.set('user', userId);
  const text = query.toString();
  return text ? `${MEMBERSHIPS_PATH}?${text}` : MEMBERSHIPS_PATH;
}

const STATES: Readonly<Record<string, { label: string; tone: string }>> = {
  draft: { label: 'Draft', tone: 'neutral' },
  validated: { label: 'Validated', tone: 'info' },
  ready_for_pilot: { label: 'Ready for pilot', tone: 'info' },
  active: { label: 'Active', tone: 'success' },
  suspended: { label: 'Suspended', tone: 'warning' },
  archived: { label: 'Archived', tone: 'neutral' },
};

/** A lifecycle state's words and badge tone. */
export function stateOf(state: string): { label: string; tone: string } {
  return STATES[state] ?? { label: state || 'Unknown', tone: 'neutral' };
}

/**
 * Settings are recorded only for a country that is not yet Active (an
 * Active country's change needs an approved change, which is not built), and
 * never for a suspended or archived one.
 */
export function canRecordSettings(state: string): boolean {
  return state === 'draft' || state === 'validated' || state === 'ready_for_pilot';
}

/** Why the settings form is not offered, in words. */
export function recordRefusal(country: Pick<Country, 'name' | 'state'>): string {
  if (country.state === 'active') {
    return `${country.name} is Active: its settings change only through an approved change, which is not built yet. Nothing here changes how ${country.name} works today.`;
  }
  return `${country.name} is ${stateOf(country.state).label.toLowerCase()}: no new settings are recorded for it.`;
}

/** A grant is offered for any country that is not archived. */
export function grantableCountries(countries: readonly Country[]): Country[] {
  return countries.filter((c) => c.state !== 'archived');
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

export function monthName(month: number): string {
  return MONTHS[month - 1] ?? '—';
}

export const MONTH_CHOICES = MONTHS.map((label, index) => ({ value: String(index + 1), label }));

const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "2027-01-01" as "1 Jan 2027"; an empty day as the given words. */
export function dayText(day: string, empty = '—'): string {
  const m = ISO_DAY.exec(day);
  if (!m) return day || empty;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]?.slice(0, 3)} ${m[1]}`;
}

const STAMP = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'Africa/Kampala',
});

/** An RFC 3339 time as "18 Nov 2026, 14:05" (Kampala time, as the platform). */
export function stampText(stamp: string): string {
  if (!stamp) return '—';
  const when = new Date(stamp);
  return Number.isNaN(when.getTime()) ? stamp : STAMP.format(when);
}

/** The platform's date notations (Django's), as the gateway allows them. */
export const DATE_FORMATS = ['j M Y', 'd M Y', 'j F Y', 'd/m/Y', 'm/d/Y', 'd.m.Y', 'Y-m-d'] as const;

/** A day drawn in one of the notations: dateExample('j M Y') is "5 Jul 2027". */
export function dateExample(format: string, day = { year: 2027, month: 7, date: 5 }): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  const month = MONTHS[day.month - 1] ?? '';
  const parts: Readonly<Record<string, string>> = {
    j: String(day.date),
    d: pad(day.date),
    M: month.slice(0, 3),
    F: month,
    m: pad(day.month),
    Y: String(day.year),
  };
  return [...format].map((ch) => parts[ch] ?? ch).join('');
}

/** The four countries' own zones, offered first; any IANA zone is accepted. */
export const TIME_ZONES = ['Africa/Kampala', 'Africa/Nairobi', 'Africa/Kigali', 'Africa/Addis_Ababa'] as const;

const LANGUAGE_NAMES: Readonly<Record<string, string>> = { en: 'English', sw: 'Swahili', rw: 'Kinyarwanda', am: 'Amharic', fr: 'French', lg: 'Luganda' };

export function languageName(code: string): string {
  return LANGUAGE_NAMES[code] ? `${LANGUAGE_NAMES[code]} (${code})` : code;
}

function calendarsText(calendars: readonly string[]): string {
  return calendars.map((c) => (c === 'ethiopian' ? 'Ethiopian beside Gregorian' : c === 'gregorian' ? 'Gregorian' : c)).join(', ') || '—';
}

function currencyText(config: Pick<CountryConfig, 'currencyCode' | 'currencyMinorUnits'>): string {
  const units = config.currencyMinorUnits;
  return `${config.currencyCode} · ${units === 0 ? 'whole amounts' : `${units} decimal place${units === 1 ? '' : 's'}`}`;
}

/** The two link tabs every country page carries. */
export function countryTabs(active: 'countries' | 'memberships'): PageLinkTabs {
  return create(PageLinkTabsSchema, {
    label: 'Country administration',
    tabs: [
      { label: 'Countries', href: COUNTRIES_PATH, active: active === 'countries' },
      { label: 'Memberships', href: MEMBERSHIPS_PATH, active: active === 'memberships' },
    ],
  });
}

/** Every registered country with the settings in force today. */
export function countriesTable(countries: readonly Country[]): PageTable {
  const rows = countries.map((c): RowInit => {
    const config = c.config;
    const state = stateOf(c.state);
    return {
      cells: [
        { text: c.code, strong: true },
        { text: c.name, href: countryPath(c.code), strong: true },
        { text: state.label, badge: true, tone: state.tone },
        { text: dayText(c.activatedOn, 'Not yet') },
        { text: config ? languageName(config.defaultLanguage) : '—' },
        { text: config ? currencyText(config) : '—' },
        { text: config?.timeZone || '—' },
        { text: config ? monthName(config.fyStartMonth) : '—' },
        { text: config ? `Version ${config.version} from ${dayText(config.effectiveFrom)}` : 'None in force' },
      ],
    };
  });
  return create(PageTableSchema, {
    title: 'Countries',
    count: String(countries.length),
    columns: [
      { label: 'Code' },
      { label: 'Country' },
      { label: 'State' },
      { label: 'Active Since' },
      { label: 'Language' },
      { label: 'Currency' },
      { label: 'Time Zone' },
      { label: 'Financial Year Starts' },
      { label: 'Settings in Force' },
    ],
    rows,
    emptyMessage: 'No countries are registered.',
  });
}

/** Every settings version of one country, newest first, with who recorded it. */
export function versionsTable(versions: readonly CountryConfig[], names: ReadonlyMap<string, string>): PageTable {
  const rows = versions.map((v): RowInit => ({
    cells: [
      { text: String(v.version), strong: true },
      { text: dayText(v.effectiveFrom) },
      { text: dayText(v.effectiveUntil, 'No end') },
      { text: v.languages.map(languageName).join(', ') + (v.languages.length > 1 ? ` · default ${v.defaultLanguage}` : '') },
      { text: currencyText(v) },
      { text: v.timeZone },
      { text: `${v.dateFormat} (${dateExample(v.dateFormat)})` },
      { text: calendarsText(v.calendars) },
      { text: monthName(v.fyStartMonth) },
      { text: `${names.get(v.changedBy) ?? v.changedBy} · ${stampText(v.createdAt)}` },
      { text: v.changeReason },
    ],
  }));
  return create(PageTableSchema, {
    title: 'Settings Versions',
    subtitle: 'A new version starts on its date and the one before it ends that day. Nothing recorded is rewritten.',
    count: String(versions.length),
    columns: [
      { label: 'Version', numeric: true },
      { label: 'From' },
      { label: 'Until' },
      { label: 'Languages' },
      { label: 'Currency' },
      { label: 'Time Zone' },
      { label: 'Date Format' },
      { label: 'Calendars' },
      { label: 'Financial Year Starts' },
      { label: 'Recorded By' },
      { label: 'Reason' },
    ],
    rows,
    emptyMessage: 'No settings are recorded for this country yet.',
  });
}

const ACCOUNT_STATUS: Readonly<Record<string, { label: string; tone: string }>> = {
  active: { label: 'Active', tone: 'success' },
  pending_invited: { label: 'Invited', tone: 'info' },
  suspended: { label: 'Suspended', tone: 'warning' },
  disabled: { label: 'Disabled', tone: 'neutral' },
};

/** The accounts a search found; each name opens its memberships. */
export function accountsTable(
  accounts: readonly Pick<ManagedAccount, 'userId' | 'name' | 'email' | 'activeRole' | 'status'>[],
  search: string,
  selected: string,
  total: number,
): PageTable {
  return create(PageTableSchema, {
    title: 'Accounts',
    subtitle: total > accounts.length ? `The first ${accounts.length} of ${total}: search more narrowly to find others.` : '',
    count: String(total),
    columns: [{ label: 'Name' }, { label: 'Email' }, { label: 'Role' }, { label: 'Status' }],
    rows: accounts.map((a): RowInit => {
      const status = ACCOUNT_STATUS[a.status] ?? { label: a.status || '—', tone: 'neutral' };
      return {
        tone: a.userId === selected ? 'selected' : '',
        cells: [
          { text: a.name || a.email, href: membershipsPath(a.userId, search), strong: true },
          { text: a.email },
          { text: a.activeRole || '—' },
          { text: status.label, badge: true, tone: status.tone },
        ],
      };
    }),
    emptyMessage: `No account matches "${search}".`,
  });
}

/** What a membership means today, in words and a badge tone. */
export function membershipStatus(
  m: Pick<Membership, 'revokedAt' | 'inForce' | 'effectiveFrom' | 'effectiveUntil' | 'countryState'>,
  today: string,
): { label: string; tone: string } {
  if (m.revokedAt) return { label: 'Revoked', tone: 'danger' };
  if (m.effectiveUntil && m.effectiveUntil <= today) return { label: 'Ended', tone: 'neutral' };
  if (m.effectiveFrom > today) return { label: `Starts ${dayText(m.effectiveFrom)}`, tone: 'info' };
  if (m.inForce) return { label: 'In force', tone: 'success' };
  return { label: `Not in force: ${stateOf(m.countryState).label} country`, tone: 'warning' };
}

function reasonProblem(reason: string): string {
  const text = reason.trim();
  if (!text) return 'Say why: a reason is required.';
  if ([...text].length > MAX_REASON) return `Keep the reason to ${MAX_REASON} characters.`;
  return '';
}

export interface GrantForm {
  readonly userId: string;
  readonly countryCode: string;
  readonly from: string;
  readonly until: string;
  readonly reason: string;
}

/** A grant's request, or what to correct first. Days are YYYY-MM-DD from a date field. */
export function grantRequest(form: GrantForm, today: string): JsonObject | string {
  if (!form.userId) return 'Choose the account first.';
  if (!/^[A-Z]{2}$/.test(form.countryCode)) return 'Choose the country.';
  const from = form.from.trim();
  const until = form.until.trim();
  if (from && !ISO_DAY.test(from)) return 'Give the start as a date.';
  if (until && !ISO_DAY.test(until)) return 'Give the end as a date.';
  if (from && from < today) return 'A membership cannot start in the past.';
  if (until && until <= (from || today)) return 'The end must come after the start.';
  const problem = reasonProblem(form.reason);
  if (problem) return problem;
  return { userId: form.userId, countryCode: form.countryCode, effectiveFrom: from, effectiveUntil: until, reason: form.reason.trim() };
}

/** A revocation's request, or what to correct first. */
export function revokeRequest(membershipId: string, reason: string): JsonObject | string {
  const problem = reasonProblem(reason);
  if (problem) return problem;
  return { membershipId, reason: reason.trim() };
}

export interface SettingsForm {
  readonly languages: string;
  readonly defaultLanguage: string;
  readonly currencyCode: string;
  readonly currencyMinorUnits: string;
  readonly timeZone: string;
  readonly dateFormat: string;
  readonly ethiopian: boolean;
  readonly fyStartMonth: string;
  readonly from: string;
  readonly reason: string;
}

/** The form opens on the settings in force, or on English, whole amounts and a July year when none are. */
export function settingsForm(config: CountryConfig | undefined): SettingsForm {
  return {
    languages: config?.languages.join(', ') ?? 'en',
    defaultLanguage: config?.defaultLanguage ?? 'en',
    currencyCode: config?.currencyCode ?? '',
    currencyMinorUnits: String(config?.currencyMinorUnits ?? 0),
    timeZone: config?.timeZone ?? '',
    dateFormat: config?.dateFormat ?? 'j M Y',
    ethiopian: config?.calendars.includes('ethiopian') ?? false,
    fyStartMonth: String(config?.fyStartMonth ?? 7),
    from: '',
    reason: '',
  };
}

/** "en, sw" as ["en", "sw"], in the order typed, without blanks. */
export function languageList(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((code) => code.trim())
    .filter(Boolean);
}

/**
 * A settings request, or what to correct first. latestFrom is the start of
 * the newest version already recorded: a new one must start after it.
 */
export function settingsRequest(countryCode: string, form: SettingsForm, today: string, latestFrom = ''): JsonObject | string {
  const languages = languageList(form.languages);
  if (!languages.length) return 'Give at least one language code, such as en.';
  if (languages.length > 10) return 'Give at most 10 languages.';
  const bad = languages.find((code) => !/^[a-z]{2,3}(-[A-Z]{2})?$/.test(code));
  if (bad) return `"${bad}" is not a language code. Use codes such as en, sw, rw or am.`;
  if (new Set(languages).size !== languages.length) return 'A language is listed twice.';
  if (!languages.includes(form.defaultLanguage)) return 'The default language must be one of the languages.';
  const currency = form.currencyCode.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(currency)) return 'Give the currency as a three-letter code, such as KES.';
  const units = Number(form.currencyMinorUnits);
  if (!Number.isInteger(units) || units < 0 || units > 3) return 'Decimal places must be 0 to 3.';
  if (!form.timeZone.trim()) return 'Give the time zone, such as Africa/Nairobi.';
  if (!(DATE_FORMATS as readonly string[]).includes(form.dateFormat)) return 'Choose a date format.';
  const month = Number(form.fyStartMonth);
  if (!Number.isInteger(month) || month < 1 || month > 12) return 'Choose the month the financial year starts.';
  const from = form.from.trim();
  if (from && !ISO_DAY.test(from)) return 'Give the start as a date.';
  if (from && from < today) return 'New settings cannot start in the past.';
  if (latestFrom && (from || today) <= latestFrom) {
    return `Start these settings after ${dayText(latestFrom)}, the day the latest version starts. Choose a later start date.`;
  }
  const problem = reasonProblem(form.reason);
  if (problem) return problem;
  return {
    countryCode,
    defaultLanguage: form.defaultLanguage,
    languages,
    currencyCode: currency,
    currencyMinorUnits: units,
    timeZone: form.timeZone.trim(),
    dateFormat: form.dateFormat,
    calendars: form.ethiopian ? ['gregorian', 'ethiopian'] : ['gregorian'],
    fyStartMonth: month,
    effectiveFrom: from,
    changeReason: form.reason.trim(),
  };
}

/** Today in Kampala as YYYY-MM-DD (the platform's local day). */
export function kampalaToday(now = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Kampala', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
}
