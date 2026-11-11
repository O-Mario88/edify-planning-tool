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
const withoutOversight = create(GetNavigationResponseSchema, { sections: [] });

describe('where signing in lands, as on the web (apps/core/landing.py)', () => {
  test('the country readers start on Country Oversight', () => {
    for (const role of ['ImpactAssessment', 'CountryDirector', 'RegionalVicePresident', 'RegionalProgramLead']) {
      expect(landingUrl(role, withOversight)).toBe('/country-planning-oversight/');
    }
  });

  test('a country reader whose menu lacks the page lands on Home, never on a refusal', () => {
    expect(landingUrl('CountryDirector', withoutOversight)).toBe('/home');
  });

  test('everyone else starts on Home, even with the page in their menu', () => {
    for (const role of ['CCEO', 'Program Lead', 'Admin', 'Accountant']) {
      expect(landingUrl(role, withOversight)).toBe('/home');
    }
  });

  test('before the menu has loaded, Home', () => {
    expect(landingUrl('CountryDirector', null)).toBe('/home');
  });
});
