'use client';

/*
 * A school's Location & Directions card (Smart Route brief, part 11): its
 * stored point on the map with its name, how sure that point is, directions
 * in the person's own maps app, and its nearby schools in the planner. A
 * school with no usable point says so and stays in every list and plan.
 */
import { create, fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import Link from 'next/link';
import { useMemo } from 'react';

import { GetSchoolLocationResponseSchema, ItineraryStopSchema } from '@/gen/edify/routes/v1/routes_pb';
import { directionsUrl } from '@/lib/routePlanner';

import { RouteIcon } from './RouteIcons';
import { RouteMap } from './RouteMap';

const STATUS: Record<string, string> = {
  verified: 'Verified location',
  recorded: 'From the School Directory (not yet verified)',
  missing: 'No location recorded',
  invalid: 'The recorded location looks wrong',
};

export function LocationCard({ answer: json }: { answer: JsonValue }) {
  const answer = useMemo(() => fromJson(GetSchoolLocationResponseSchema, json), [json]);
  const school = answer.school;
  const stops = useMemo(() => (school?.point ? [create(ItineraryStopSchema, { order: 0, school, kind: 'location' })] : []), [school]);
  if (!school) return null;
  const point = school.point;
  const directions = directionsUrl([school]);
  return (
    <section className="rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-4" aria-labelledby="location-title" data-block="school-location">
      <h2 id="location-title" className="flex items-center gap-2 text-[16px] font-semibold">
        <RouteIcon name="pin" className="h-5 w-5 text-[#1d6fe0]" /> Location &amp; Directions
      </h2>
      {point ? (
        <div className="mt-3 grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,18rem)]">
          <div className="relative h-[260px] overflow-hidden rounded-[10px] border border-[var(--edify-border)]">
            <RouteMap stops={stops} path={[]} others={[]} chip={null} onSelect={() => undefined} className="absolute inset-0" showLegend={false} />
          </div>
          <dl className="space-y-3 text-[14px]">
            <div>
              <dt className="text-[var(--edify-text-muted)]">GPS location</dt>
              <dd className="font-medium tabular-nums">
                {point.lat.toFixed(6)}, {point.lng.toFixed(6)}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--edify-text-muted)]">Location status</dt>
              <dd className="font-medium">{STATUS[school.locationStatus] ?? school.locationStatus}</dd>
            </div>
            <div>
              <dt className="text-[var(--edify-text-muted)]">Nearby</dt>
              <dd className="font-medium">
                {answer.nearbySchools} of your schools within {answer.nearbyRadiusKm} km (straight line)
              </dd>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {directions ? (
                <a href={directions} target="_blank" rel="noopener noreferrer" className="inline-flex h-10 items-center gap-2 rounded-[8px] bg-[#1d6fe0] px-4 font-semibold text-white">
                  <RouteIcon name="navigate" className="h-4 w-4" /> Get Directions
                </a>
              ) : null}
              {answer.canPlan ? (
                <Link href={`/my-plan/smart-route?near=${encodeURIComponent(school.schoolId)}`} className="inline-flex h-10 items-center gap-2 rounded-[8px] border border-[#1d6fe0] px-4 font-semibold text-[#1d6fe0]">
                  <RouteIcon name="route" className="h-4 w-4" /> Find Nearby Schools
                </Link>
              ) : null}
            </div>
          </dl>
        </div>
      ) : (
        <p className="mt-2 rounded-[8px] bg-amber-50 px-3 py-2 text-[14px] text-amber-900" role="status">
          {STATUS[school.locationStatus]}. Directions and route planning need a location; the school still appears in every list
          and plan.
        </p>
      )}
    </section>
  );
}
