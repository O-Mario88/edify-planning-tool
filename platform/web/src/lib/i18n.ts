/**
 * Multi-country localization, currency formatting, and dual-calendar (Gregorian
 * + Ethiopian) utilities for Edify Global (UG, KE, RW, ET).
 */

export type LocaleCode = 'en' | 'sw' | 'rw' | 'fr' | 'am' | 'om';
export type CountryCode = 'UG' | 'KE' | 'RW' | 'ET';

export interface CountryProfile {
  readonly code: CountryCode;
  readonly name: string;
  readonly currency: 'UGX' | 'KES' | 'RWF' | 'ETB';
  readonly currencyMinorUnits: number;
  readonly defaultLocale: LocaleCode;
  readonly locales: readonly LocaleCode[];
  readonly calendar: 'gregorian' | 'ethiopian';
  readonly geographyLevels: readonly string[];
}

export const COUNTRY_PROFILES: Readonly<Record<CountryCode, CountryProfile>> = {
  UG: {
    code: 'UG',
    name: 'Uganda',
    currency: 'UGX',
    currencyMinorUnits: 0,
    defaultLocale: 'en',
    locales: ['en'],
    calendar: 'gregorian',
    geographyLevels: ['Region', 'District', 'Sub-county', 'Parish', 'Village'],
  },
  KE: {
    code: 'KE',
    name: 'Kenya',
    currency: 'KES',
    currencyMinorUnits: 2,
    defaultLocale: 'en',
    locales: ['en', 'sw'],
    calendar: 'gregorian',
    geographyLevels: ['County', 'Sub-county', 'Ward'],
  },
  RW: {
    code: 'RW',
    name: 'Rwanda',
    currency: 'RWF',
    currencyMinorUnits: 0,
    defaultLocale: 'en',
    locales: ['en', 'rw', 'fr'],
    calendar: 'gregorian',
    geographyLevels: ['Province', 'District', 'Sector', 'Cell', 'Village'],
  },
  ET: {
    code: 'ET',
    name: 'Ethiopia',
    currency: 'ETB',
    currencyMinorUnits: 2,
    defaultLocale: 'am',
    locales: ['am', 'om', 'en'],
    calendar: 'ethiopian',
    geographyLevels: ['Regional State', 'Zone', 'Woreda', 'Kebele'],
  },
};

const DICTIONARY = {
  en: {
    dashboard: 'Dashboard',
    planning: 'Planning',
    schoolDirectory: 'School Directory',
    clusters: 'Clusters',
    coreSchools: 'Core Schools',
    escalations: 'Escalations',
    fieldDebrief: 'Field Debrief',
    personalTimeOff: 'Personal Time Off',
    decisionLog: 'Decision Log',
    exportReport: 'Export Report',
    requestLeave: 'Request Leave',
    noRecords: 'No records match these filters.',
  },
  sw: {
    dashboard: 'Dashibodi',
    planning: 'Mipango',
    schoolDirectory: 'Orodha ya Shule',
    clusters: 'Vikundi vya Shule',
    coreSchools: 'Shule Kuu',
    escalations: 'Masuala ya Juu',
    fieldDebrief: 'Ripoti ya Uwandani',
    personalTimeOff: 'Likizo ya Binafsi',
    decisionLog: 'Kumbukumbu ya Maamuzi',
    exportReport: 'Pakua Ripoti',
    requestLeave: 'Omba Likizo',
    noRecords: 'Hakuna rekodi zinazolingana na vichujio hivi.',
  },
  rw: {
    dashboard: 'Imbonerahamwe',
    planning: 'Igenamigambi',
    schoolDirectory: 'Urutonde rw’Amashuri',
    clusters: 'Amatsinda y’Amashuri',
    coreSchools: 'Amashuri y’Ibanze',
    escalations: 'Ibibazo byo ku Rwego rwo Hejuru',
    fieldDebrief: 'Raporo y’Ibikorwa',
    personalTimeOff: 'Ikiruhuko',
    decisionLog: 'Igitabo cy’Ibyemezo',
    exportReport: 'Kura Raporo',
    requestLeave: 'Saba Ikiruhuko',
    noRecords: 'Nta makuru ahuye n’ibyo washatse.',
  },
  fr: {
    dashboard: 'Tableau de bord',
    planning: 'Planification',
    schoolDirectory: 'Répertoire des écoles',
    clusters: 'Groupes d’écoles',
    coreSchools: 'Écoles principales',
    escalations: 'Escalades',
    fieldDebrief: 'Compte rendu terrain',
    personalTimeOff: 'Congés personnels',
    decisionLog: 'Journal des décisions',
    exportReport: 'Exporter le rapport',
    requestLeave: 'Demander un congé',
    noRecords: 'Aucun enregistrement ne correspond à ces filtres.',
  },
  am: {
    dashboard: 'ዳሽቦርድ',
    planning: 'እቅድ',
    schoolDirectory: 'የትምህርት ቤቶች ዝርዝር',
    clusters: 'ክላስተሮች',
    coreSchools: 'ዋና ትምህርት ቤቶች',
    escalations: 'ወደ ላይ የተላኩ ጉዳዮች',
    fieldDebrief: 'የመስክ ሪፖርት',
    personalTimeOff: 'የግል ፈቃድ',
    decisionLog: 'የውሳኔ መዝገብ',
    exportReport: 'ሪፖርት አውርድ',
    requestLeave: 'ፈቃድ ጠይቅ',
    noRecords: 'ከእነዚህ ማጣሪያዎች ጋር የሚዛመድ መረጃ የለም።',
  },
  om: {
    dashboard: 'Daashboordii',
    planning: 'Karoora',
    schoolDirectory: 'Tarree Manneen Barnootaa',
    clusters: 'Kilaastaroota',
    coreSchools: 'Manneen Barnootaa Ijoo',
    escalations: 'Dhimmoota Ol-ergaman',
    fieldDebrief: 'Gabaasa Dirree',
    personalTimeOff: 'Boqonnaa Dhuunfaa',
    decisionLog: 'Galmee Murtee',
    exportReport: 'Gabaasa Buusi',
    requestLeave: 'Boqonnaa Gaafadhu',
    noRecords: 'Galmeen calaltuu kanaan walsimu hin jiru.',
  },
} as const;

export type TranslationKey = keyof typeof DICTIONARY.en;

export function t(locale: string, key: TranslationKey): string {
  const norm = (locale.split('-')[0]?.toLowerCase() ?? 'en') as LocaleCode;
  const table = DICTIONARY[norm] ?? DICTIONARY.en;
  return table[key] ?? DICTIONARY.en[key];
}

export function formatCurrency(amount: number, country: CountryCode = 'UG'): string {
  const profile = COUNTRY_PROFILES[country] ?? COUNTRY_PROFILES.UG;
  const formatted = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: profile.currencyMinorUnits,
    maximumFractionDigits: profile.currencyMinorUnits,
  }).format(amount);
  return `${profile.currency} ${formatted}`;
}

const ETH_MONTHS_EN = [
  'Meskerem', 'Tikimt', 'Hidar', 'Tahsas', 'Tir', 'Yekatit',
  'Megabit', 'Miazia', 'Ginbot', 'Sene', 'Hamle', 'Nehase', 'Pagume',
] as const;

const ETH_MONTHS_AM = [
  'መስከረም', 'ጥቅምት', 'ኅዳር', 'ታኅሣሥ', 'ጥር', 'የካቲት',
  'መጋቢት', 'ሚያዝያ', 'ግንቦት', 'ሰኔ', 'ሐምሌ', 'ነሐሴ', 'ጳጉሜ',
] as const;

const ETHIOPIC_EPOCH_JDN = 1723856;

function gregorianToJdn(y: number, m: number, d: number): number {
  const a = Math.floor((14 - m) / 12);
  const yy = y + 4800 - a;
  const mm = m + 12 * a - 3;
  return d + Math.floor((153 * mm + 2) / 5) + 365 * yy + Math.floor(yy / 4) - Math.floor(yy / 100) + Math.floor(yy / 400) - 32045;
}

export function toEthiopianDate(date: Date): { year: number; month: number; day: number } {
  const jdn = gregorianToJdn(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
  const delta = jdn - ETHIOPIC_EPOCH_JDN;
  let r = delta % 1461;
  if (r < 0) r += 1461;
  const n = (r % 365) + 365 * Math.floor(r / 1460);
  const cycles = (delta - r) / 1461;
  const year = 4 * cycles + Math.floor(r / 365) - Math.floor(r / 1460);
  return { year, month: Math.floor(n / 30) + 1, day: (n % 30) + 1 };
}

export function formatDateForCountry(date: Date, country: CountryCode = 'UG', locale: LocaleCode = 'en'): string {
  const profile = COUNTRY_PROFILES[country] ?? COUNTRY_PROFILES.UG;
  if (profile.calendar === 'ethiopian') {
    const et = toEthiopianDate(date);
    if (locale === 'am') {
      return `${ETH_MONTHS_AM[et.month - 1]} ${et.day}, ${et.year} ዓ.ም`;
    }
    return `${ETH_MONTHS_EN[et.month - 1]} ${et.day}, ${et.year} EC`;
  }
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(date);
}
