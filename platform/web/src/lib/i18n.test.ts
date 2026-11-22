import { describe, expect, it } from 'vitest';

import { COUNTRY_PROFILES, formatCurrency, formatDateForCountry, t, toEthiopianDate } from './i18n';

describe('Multi-country i18n, currency and Ethiopian calendar', () => {
  it('translates UI labels across all 6 Edify Global languages', () => {
    expect(t('en', 'schoolDirectory')).toBe('School Directory');
    expect(t('sw', 'schoolDirectory')).toBe('Orodha ya Shule');
    expect(t('rw', 'schoolDirectory')).toBe('Urutonde rw’Amashuri');
    expect(t('fr', 'schoolDirectory')).toBe('Répertoire des écoles');
    expect(t('am', 'schoolDirectory')).toBe('የትምህርት ቤቶች ዝርዝር');
    expect(t('om', 'schoolDirectory')).toBe('Tarree Manneen Barnootaa');
    expect(t('xx', 'dashboard')).toBe('Dashboard');
  });

  it('formats country currencies with country-specific minor units', () => {
    expect(formatCurrency(125000, 'UG')).toBe('UGX 125,000');
    expect(formatCurrency(1500.5, 'KE')).toBe('KES 1,500.50');
    expect(formatCurrency(42000, 'RW')).toBe('RWF 42,000');
    expect(formatCurrency(850, 'ET')).toBe('ETB 850.00');
  });

  it('converts and formats Ethiopian calendar dates accurately', () => {
    const nov22 = new Date(Date.UTC(2026, 10, 22));
    expect(toEthiopianDate(nov22)).toEqual({ year: 2019, month: 3, day: 13 });
    expect(toEthiopianDate(new Date(Date.UTC(2023, 8, 11)))).toEqual({ year: 2015, month: 13, day: 6 });
    expect(formatDateForCountry(nov22, 'ET', 'en')).toBe('Hidar 13, 2019 EC');
    expect(formatDateForCountry(nov22, 'ET', 'am')).toBe('ኅዳር 13, 2019 ዓ.ም');
    expect(COUNTRY_PROFILES.KE.geographyLevels).toEqual(['County', 'Sub-county', 'Ward']);
  });
});
