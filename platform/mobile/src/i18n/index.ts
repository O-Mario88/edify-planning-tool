/**
 * Multi-country localization and Ethiopian calendar utilities for the Expo
 * mobile app (Uganda, Kenya, Rwanda, Ethiopia).
 */

export type MobileLocale = 'en' | 'sw' | 'rw' | 'fr' | 'am' | 'om';

const STRINGS = {
  en: {
    home: 'Home',
    meetings: 'Meetings',
    schools: 'Schools',
    more: 'More',
    planMeeting: 'Plan Meeting',
    mySchools: 'My Schools',
    actionFollowUp: 'Action & Follow-up',
    mobilizeSchools: 'Mobilize Schools',
    needsAttention: 'Needs Your Attention',
    progressReports: 'Progress & Reports',
    offlineQueue: 'Offline Sync Queue',
  },
  sw: {
    home: 'Nyumbani',
    meetings: 'Mikutano',
    schools: 'Shule',
    more: 'Zaidi',
    planMeeting: 'Panga Mkutano',
    mySchools: 'Shule Zangu',
    actionFollowUp: 'Hatua na Ufuatiliaji',
    mobilizeSchools: 'Hamasisha Shule',
    needsAttention: 'Inahitaji Umakini Wako',
    progressReports: 'Maendeleo na Ripoti',
    offlineQueue: 'Foleni ya Usawazishaji',
  },
  rw: {
    home: 'Ahabanza',
    meetings: 'Inama',
    schools: 'Amashuri',
    more: 'Ibindi',
    planMeeting: 'Tegura Inama',
    mySchools: 'Amashuri Yanjye',
    actionFollowUp: 'Ibikorwa n’Ikurikirana',
    mobilizeSchools: 'Shishikariza Amashuri',
    needsAttention: 'Bikeneye Ubufasha Bwawe',
    progressReports: 'Iterambere na Raporo',
    offlineQueue: 'Ibitegereje Koherezwa',
  },
  fr: {
    home: 'Accueil',
    meetings: 'Réunions',
    schools: 'Écoles',
    more: 'Plus',
    planMeeting: 'Planifier une réunion',
    mySchools: 'Mes écoles',
    actionFollowUp: 'Actions et suivi',
    mobilizeSchools: 'Mobiliser les écoles',
    needsAttention: 'Nécessite votre attention',
    progressReports: 'Progrès et rapports',
    offlineQueue: 'File hors ligne',
  },
  am: {
    home: 'መነሻ',
    meetings: 'ስብሰባዎች',
    schools: 'ትምህርት ቤቶች',
    more: 'ተጨማሪ',
    planMeeting: 'ስብሰባ አቅድ',
    mySchools: 'የእኔ ትምህርት ቤቶች',
    actionFollowUp: 'እርምጃ እና ክትትል',
    mobilizeSchools: 'ትምህርት ቤቶችን አነሳሳ',
    needsAttention: 'ትኩረትዎን ይፈልጋል',
    progressReports: 'እድገት እና ሪፖርቶች',
    offlineQueue: 'ከመስመር ውጭ ማመሳሰል',
  },
  om: {
    home: 'Fuula Jalqabaa',
    meetings: 'Walgahiiwwan',
    schools: 'Manneen Barnootaa',
    more: 'Dabalata',
    planMeeting: 'Walgahii Karoorsi',
    mySchools: 'Manneen Barnootaa Koo',
    actionFollowUp: 'Tarkaanfii fi Hordoffii',
    mobilizeSchools: 'Manneen Barnootaa Qopheessi',
    needsAttention: 'Xiyyeeffannoo Kee Barbaada',
    progressReports: 'Fooyya’iinsa fi Gabaasa',
    offlineQueue: 'Tartiiba Wal-simsiisuu',
  },
} as const;

export type MobileKey = keyof typeof STRINGS.en;

export function tMobile(locale: string, key: MobileKey): string {
  const norm = (locale.split('-')[0]?.toLowerCase() ?? 'en') as MobileLocale;
  const dict = STRINGS[norm] ?? STRINGS.en;
  return dict[key] ?? STRINGS.en[key];
}
