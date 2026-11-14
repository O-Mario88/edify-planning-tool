import { create } from '@bufbuild/protobuf';

import { RouteLegSchema, RouteTotalsSchema, SchoolPinSchema } from '../gen/edify/routes/v1/routes_pb';
import { ROUTE_URL, directionsUrl, hrMin, isRouteUrl, legText, routeSection, shortName, totalFigures } from '../screens/route/routeData';

describe('the route planner in the app', () => {
  it('is listed for field staff only, natively', () => {
    expect(routeSection('CCEO')?.items.map((i) => [i.url, i.native])).toEqual([[ROUTE_URL, true]]);
    expect(routeSection('MfiLoanOfficer')).toBeNull();
    expect(isRouteUrl('route:planner?date=2026-11-17')).toBe(true);
    expect(isRouteUrl('/my-plan')).toBe(false);
  });

  it('writes times as the design does', () => {
    expect(hrMin(85 * 60)).toBe('1 hr 25 min');
    expect(hrMin(18 * 60)).toBe('18 min');
    expect(shortName('Nakasero Primary School')).toBe('Nakasero P/S');
  });

  it('never shows a straight line as a road', () => {
    expect(legText(create(RouteLegSchema, { roadAvailable: true, roadMeters: 12_500n, roadSeconds: 1320n }))).toBe('12.5 km • 22 min');
    expect(legText(create(RouteLegSchema, { straightLineMeters: 8800n, estimateSeconds: 1080n }))).toBe('8.8 km • 18 min (straight line)');
    expect(totalFigures(create(RouteTotalsSchema, { roadComplete: false, roadMeters: 1n, straightLineMeters: 9000n })).road).toBe(false);
  });

  it('hands directions to the person’s own maps app without a key', () => {
    const stops = [create(SchoolPinSchema, { point: { lat: 0.3, lng: 32.7 } }), create(SchoolPinSchema, { point: { lat: 0.4, lng: 32.8 } })];
    expect(directionsUrl(stops, 'google')).toContain('waypoints=0.300000%2C32.700000');
    expect(directionsUrl(stops, 'apple')).toBe('https://maps.apple.com/?daddr=0.300000,32.700000&dirflg=d');
    expect(directionsUrl([], 'waze')).toBeNull();
  });
});
