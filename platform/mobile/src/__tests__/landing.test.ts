import { create } from '@bufbuild/protobuf';

import { GetNavigationResponseSchema, NavItemSchema, NavSectionSchema } from '../gen/edify/screens/v1/navigation_pb';
import { landingUrl } from '../landing';

const withOversight = create(GetNavigationResponseSchema, {
  sections: [
    create(NavSectionSchema, {
      label: 'Oversight',
      items: [create(NavItemSchema, { label: 'Country Oversight', url: '/country-planning-oversight/' })],
    }),
  ],
});

describe('where signing in lands (owner, 2026-11-19: own role home)', () => {
  test('the country readers land on their own Home, even with Country Oversight in their menu', () => {
    for (const role of ['ImpactAssessment', 'CountryDirector', 'RegionalVicePresident', 'RegionalProgramLead']) {
      expect(landingUrl(role, withOversight)).toBe('/home');
    }
  });

  test('everyone else lands on Home too, and so does anyone before the menu has loaded', () => {
    for (const role of ['CCEO', 'Program Lead', 'Admin', 'Accountant']) {
      expect(landingUrl(role, withOversight)).toBe('/home');
    }
    expect(landingUrl('CountryDirector', null)).toBe('/home');
  });
});
