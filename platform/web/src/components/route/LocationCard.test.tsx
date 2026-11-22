import { create, toJson } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { GetSchoolLocationResponseSchema, PointSchema, SchoolPinSchema } from '@/gen/edify/routes/v1/routes_pb';

import { LocationCard } from './LocationCard';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

vi.mock('./RouteMap', () => ({
  RouteMap: () => <div data-testid="mock-route-map" />,
}));

describe('LocationCard conditional GPS capture UI (Section 2)', () => {
  it('shows GPS Missing badge and Tap to Add GPS Coordinates when school has no coordinates', () => {
    const answer = create(GetSchoolLocationResponseSchema, {
      school: create(SchoolPinSchema, {
        schoolId: 'school-1008',
        code: '1008',
        name: 'Koome Islands Primary School',
        locationStatus: 'missing',
      }),
      canCapture: true,
    });
    const html = renderToStaticMarkup(<LocationCard answer={toJson(GetSchoolLocationResponseSchema, answer)} />);

    expect(html).toContain('GPS Missing');
    expect(html).toContain('Tap to Add GPS Coordinates');
    expect(html).not.toContain('Update GPS Coordinates');
    expect(html).not.toMatch(/google\.com\/maps|maps\.apple\.com|waze\.com/i);
  });

  it('shows GPS Recorded badge, stored coordinates, Update GPS Coordinates, and in-app Get Directions when coordinates exist', () => {
    const answer = create(GetSchoolLocationResponseSchema, {
      school: create(SchoolPinSchema, {
        schoolId: 'school-1001',
        code: '1001',
        name: 'St. Mary Primary School',
        locationStatus: 'verified',
        point: create(PointSchema, { lat: 0.347612, lng: 32.582541 }),
      }),
      version: 2,
      verifiedAt: '2026-11-22T09:15:00Z',
      verifiedByName: 'C. Kato',
      canCapture: true,
    });
    const html = renderToStaticMarkup(<LocationCard answer={toJson(GetSchoolLocationResponseSchema, answer)} />);

    expect(html).toContain('GPS Recorded');
    expect(html).toContain('0.347612, 32.582541');
    expect(html).toContain('Device location services');
    expect(html).toContain('Update GPS Coordinates');
    expect(html).not.toContain('Tap to Add GPS Coordinates');
    expect(html).toContain('/my-plan/smart-route');
    expect(html).not.toMatch(/google\.com\/maps|maps\.apple\.com|waze\.com/i);
  });
});
